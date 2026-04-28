# CC Switch Lite — 第一阶段设计 Spec

## 概述

在现有 claude-provider-switcher 基础上，渐进扩展三个核心子系统：代理服务+故障转移、健康检测、用量查询。采用方案 A（渐进扩展），在 Flask 内新增 Blueprint 模块，aiohttp 代理线程，前端单文件 Tab 切换。

## 项目结构

```
app.py                    ← Flask 入口，注册 Blueprint，启动 APScheduler
provider_manager.py       ← 现有，不动
config.py                 ← 新增：全局配置常量
proxy.py                  ← 新增：代理服务 + 故障转移（Blueprint + aiohttp 线程）
health.py                 ← 新增：健康检测（Blueprint + APScheduler job）
usage.py                  ← 新增：用量查询（Blueprint + 缓存）
providers/                ← 现有，不动
data/                     ← 新增：运行时数据
  health_log.json         ← 健康检测历史（24h）
  usage_cache.json        ← 用量缓存（5min TTL）
templates/
  index.html              ← 扩展 Tab 页
requirements.txt          ← 新增依赖
```

## 1. config.py — 全局配置

约 30 行，定义所有可配置常量：

```python
# 代理配置
PROXY_TIMEOUT = 30          # 请求超时秒数
PROXY_MAX_RETRIES = 3       # 最大重试次数（遍历供应商）
CIRCUIT_FAILURE_THRESHOLD = 3  # 连续失败 N 次触发熔断
CIRCUIT_RECOVERY_INTERVAL = 60  # 熔断恢复检测间隔秒数

# 健康检测配置
HEALTH_CHECK_INTERVAL = 60  # 定时检测间隔秒数
HEALTH_DEGRADED_THRESHOLD = 2000  # 延迟超过此值(ms)标记为 degraded
HEALTH_TIMEOUT = 5          # 检测请求超时秒数
HEALTH_LOG_RETENTION = 86400  # 历史记录保留秒数（24h）

# 用量缓存配置
USAGE_CACHE_TTL = 300       # 缓存有效期秒数（5min）

# 数据目录
DATA_DIR = Path(__file__).parent / "data"
```

## 2. proxy.py — 代理服务 + 故障转移

### 架构

代理路径挂载在 Flask `/proxy/v1/*`。Flask 收到代理请求后，通过 `asyncio.run_coroutine_threadsafe` 转发到 aiohttp 线程。

### 代理转发流程

1. 收到请求 → 读取请求体和 headers
2. 获取所有供应商列表，按 providers.json 键序排列
3. 跳过被熔断标记的供应商（查询 health.py 的状态）
4. 对每个可用供应商：
   a. 从供应商 .env 文件读取 AUTH_TOKEN，注入到请求 Authorization header
   b. 替换目标 URL 的 host 为供应商的 base_url
   c. 转发请求，流式透传 SSE 响应
   d. 失败判定：连接超时（30s）、HTTP 429/500/502/503
   e. 成功 → 记录为活跃供应商，结束
5. 所有供应商都失败 → 返回 503 + 最后一个错误信息

### 熔断器

每个供应商维护独立状态：

- `healthy`：正常可用
- `unhealthy`：连续失败 ≥ 3 次，跳过
- `recovering`：60s 后发一次轻量检测（GET /v1/models），成功则恢复 healthy

状态存在内存中（模块级变量），不持久化。

### 故障转移上下文

- 同一请求重试不同供应商 → 请求体不变，上下文不丢
- 供应商 A 的部分响应已返回 → 这部分丢失，供应商 B 从头生成
- 响应到一半断开 → Claude Code 自身有重试机制

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/proxy/v1/<path:path>` | ALL | 代理转发（透传到当前/备用供应商） |
| `/api/proxy/status` | GET | 代理状态 + 各供应商健康度 + 当前活跃供应商 |
| `/api/proxy/config` | PUT | 更新代理配置（超时/重试/熔断参数） |
| `/api/proxy/log` | GET | 最近 20 条故障转移日志 |

### 代理启动

代理模式下，Claude Code 的 `ANTHROPIC_BASE_URL` 指向 `http://localhost:5000/proxy/v1`。代理自动从当前供应商 .env 读取 `AUTH_TOKEN` 注入请求头。

## 3. health.py — 健康检测

### 检测机制

- APScheduler `IntervalJob`，每 60s 执行一次全量检测
- 对每个供应商发送 `GET {base_url}/v1/models`（OpenAI 兼容格式）
- 使用 `httpx.AsyncClient` 异步并发检测所有供应商

### 状态判定

| 条件 | 状态 | 颜色 |
|------|------|------|
| HTTP 200，延迟 < 2s | healthy | 绿 |
| HTTP 非 200，或延迟 2-5s | degraded | 黄 |
| 超时（5s）或连接失败 | unhealthy | 红 |

### 数据存储

`data/health_log.json`：最近 24h 检测记录数组，每条：

```json
{
  "provider": "glm",
  "status": "healthy",
  "latency_ms": 156,
  "models": ["GLM-4.5-air", "GLM-5.1"],
  "timestamp": "2026-04-28T20:00:00"
}
```

超过 24h 的记录在每次检测后自动清理。

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 所有供应商当前健康状态 |
| `/api/health/check/<name>` | POST | 手动触发单个供应商检测 |
| `/api/health/history` | GET | 最近 24h 历史记录 |

### 与代理联动

`health.py` 暴露 `get_provider_health(name) -> dict` 函数，`proxy.py` 在选择供应商时查询此函数判断是否跳过。

## 4. usage.py — 用量查询

### 查询方式

1. 读取供应商 base_url 和 auth_token
2. 发送 `GET {base_url}/v1/dashboard/billing/usage`（OpenAI 兼容格式）
3. 如果返回非 200，返回 `{"supported": false}`
4. 解析响应，提取用量/余额信息

### 缓存策略

- 缓存文件：`data/usage_cache.json`
- 每条记录：`{provider, data, fetched_at}`
- TTL 5 分钟，超时后下次请求重新查询
- 启动时从文件加载缓存
- 使用 `httpx.AsyncClient` 并发查询所有供应商

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/usage` | GET | 所有供应商用量汇总 |
| `/api/usage/<name>` | GET | 单个供应商用量 |
| `/api/usage/refresh` | POST | 强制刷新所有缓存 |

## 5. 前端 Tab 扩展

### Tab 结构

```
[供应商管理] [代理服务] [健康监控] [用量查询]
```

### 各 Tab 内容

**供应商管理（现有）：**
- 保持现有功能不变
- 卡片上新增健康状态灯（从 health API 读取）
- 新增"代理优先级"数字标识（对应 providers.json 键序）

**代理服务：**
- 代理开关（ON/OFF toggle）
- 当前活跃供应商 + 实时请求统计
- 故障转移日志列表（最近 20 条，含时间、供应商、原因）
- 配置面板：超时、重试次数、熔断阈值
- 开启代理后显示提示："请将 BASE_URL 设为 http://localhost:5000/proxy/v1"

**健康监控：**
- 供应商健康卡片网格（状态灯 + 延迟 ms + 可用模型列表）
- "全部检测"按钮 + 每个卡片的独立检测按钮
- 24h 延迟趋势图（纯 CSS 柱状图或 SVG，不引入 Chart.js）

**用量查询：**
- 各供应商用量卡片（剩余额度、已用量）
- "刷新全部"按钮
- 不支持的供应商显示提示信息

### 交互

- Tab 内容首次点击时懒加载
- 健康数据每 60s 自动刷新（轮询 `/api/health`）
- 前端保持单文件 index.html，复用现有 CSS 变量和深色主题

## 6. 依赖

```
flask              ← 已有
aiohttp            ← 新增：代理层异步 HTTP
httpx              ← 新增：健康检测和用量查询异步 HTTP
apscheduler        ← 新增：定时任务
```

## 7. 实施顺序

1. `config.py` — 全局配置常量
2. `health.py` — 健康检测（不依赖代理，可独立开发测试）
3. `proxy.py` — 代理服务 + 故障转移（依赖 health 状态）
4. `usage.py` — 用量查询（完全独立）
5. `app.py` — 注册 Blueprint + 启动调度器
6. `templates/index.html` — Tab 扩展 + 各功能 UI

## 8. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| SSE 流式转发不完整 | 使用 aiohttp 的流式 API，逐 chunk 转发 |
| Flask 同步 + aiohttp 异步线程安全 | 通过 asyncio.run_coroutine_threadsafe 桥接，共享数据用 queue |
| 多供应商 auth header 格式差异 | 统一注入 `Authorization: Bearer {token}` |
| 代理转发和手动切换冲突 | 代理模式下禁用手动切换按钮，或切换后自动重启代理 |
| index.html 行数增长 | 严格按 Tab 分区，每个 Tab 的 JS/CSS 独立函数 |
