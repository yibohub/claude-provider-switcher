# CC Switch Lite — 第一阶段设计 Spec（v2）

## 概述

在现有 claude-provider-switcher 基础上，渐进扩展两个核心子系统：代理服务+故障转移、健康检测。用量查询推迟到第二阶段（当前供应商均不支持 OpenAI billing 端点）。

采用方案 A（渐进扩展），在 Flask 内新增 Blueprint 模块，统一使用 httpx 处理所有异步 HTTP（代理转发、健康检测），前端单文件 Tab 切换。Flask 以 threaded 模式运行，代理转发使用 httpx 同步流式 API，无需独立事件循环线程。

## 项目结构

```
app.py                    ← Flask 入口（threaded=True），注册 Blueprint，启动 APScheduler
provider_manager.py       ← 现有，不动
config.py                 ← 新增：全局配置常量
proxy.py                  ← 新增：代理服务 + 故障转移（Blueprint + httpx）
health.py                 ← 新增：健康检测（Blueprint + APScheduler job + httpx）
providers/                ← 现有，不动
data/                     ← 新增：运行时数据
  health_log.json         ← 健康检测历史（24h）
  proxy_state.json        ← 代理开关状态
  config.json             ← 代理运行时配置（PUT /api/proxy/config 持久化）
templates/
  index.html              ← 扩展 Tab 页
requirements.txt          ← 新增依赖
```

## providers.json 扩展字段

现有 `providers/providers.json` 元数据新增以下字段：

```json
{
  "glm": {
    "label": "GLM",
    "color": "#4285f4",
    "icon": "🧠",
    "priority": 1,
    "auth_type": "x-api-key",
    "health_check_path": "/v1/models",
    "health_check_fallback": true
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `priority` | int | 代理故障转移优先级，数字越小越优先 |
| `auth_type` | string | `x-api-key`（Anthropic 兼容，默认）或 `bearer`（OpenAI 兼容） |
| `health_check_path` | string | 健康检测端点路径，默认 `/v1/models` |
| `health_check_fallback` | bool | 主检测失败时是否尝试降级检测（轻量 messages 请求） |

## 1. config.py — 全局配置

约 30 行，定义所有可配置常量：

```python
# 代理配置
PROXY_TIMEOUT = 30          # 请求超时秒数
PROXY_MAX_PROVIDERS = 3    # 最大尝试供应商数量
CIRCUIT_FAILURE_THRESHOLD = 3  # 连续失败 N 次触发熔断
CIRCUIT_RECOVERY_INTERVAL = 60  # 熔断恢复检测间隔秒数
PROXY_DEFAULT_STATE = False   # 默认代理关闭（需手动启用）

# 健康检测配置
HEALTH_CHECK_INTERVAL = 60  # 定时检测间隔秒数
HEALTH_DEGRADED_THRESHOLD = 2000  # 延迟超过此值(ms)标记为 degraded
HEALTH_TIMEOUT = 5          # 检测请求超时秒数
HEALTH_LOG_RETENTION = 86400  # 历史记录保留秒数（24h）

# 数据目录
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
```

## 2. proxy.py — 代理服务 + 故障转移

### 架构

代理路径挂载在 Flask `/proxy/*`。Flask 以 `threaded=True` 运行，代理使用 httpx 同步客户端进行流式转发，无需独立事件循环线程。

### 代理转发流程

1. 收到请求 → 路径校验：拒绝包含 `..`、null 字节、绝对路径覆盖的请求路径
2. 读取请求体和 headers，剥离客户端原始 auth header
3. 获取所有供应商列表：**当前供应商优先**，其余按 `priority` 升序排列
4. 跳过被熔断标记的供应商（查询 `health.get_provider_status()`）
5. 对前 `PROXY_MAX_PROVIDERS` 个可用供应商：
   a. 从供应商 `.env` 文件读取 `ANTHROPIC_AUTH_TOKEN`
   b. 按 `auth_type` 注入 auth header：`x-api-key` 或 `Authorization: Bearer`
   c. 将请求路径拼接到供应商 `base_url`，转发请求
   d. 流式透传 SSE 响应（`httpx.Client.stream()` + `response.iter_bytes()`）
   e. 失败判定：连接超时（30s）、HTTP 429/500/502/503
   f. 成功 → 记录为活跃供应商，结束
6. 所有供应商都失败 → 返回 503 + 通用错误信息（详细信息仅记录到服务端日志）

### Auth header 注入

按供应商 `auth_type` 字段决定注入方式：

| auth_type | 注入 Header | 适用供应商 |
|-----------|-------------|-----------|
| `x-api-key` | `x-api-key: {token}` | Anthropic 兼容（GLM、MiniMax） |
| `bearer` | `Authorization: Bearer {token}` | OpenAI 兼容（DeepSeek、Qwen） |

### 熔断器

每个供应商维护独立状态：

- `healthy`：正常可用
- `unhealthy`：连续失败达到 `CIRCUIT_FAILURE_THRESHOLD` (3) 次，跳过
- `recovering`：60s 后发一次轻量检测，成功则恢复 `healthy`

状态存在内存中（模块级变量），不持久化。重启后所有供应商恢复为 `healthy`，首次健康检测周期（60s 内）会重新标记异常供应商。

### 故障转移上下文

- 同一请求重试不同供应商 → 请求体不变，上下文不丢
- 供应商 A 的部分响应已返回 → 这部分丢失，供应商 B 从头生成
- 代理模式下手动切换供应商 → 切换即时生效，代理下次请求使用新当前供应商（无需重启代理）

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/proxy/<path:path>` | ALL | 代理转发（透传到当前/备用供应商） |
| `/api/proxy/status` | GET | 代理状态（ON/OFF）+ 各供应商健康度 + 当前活跃供应商 |
| `/api/proxy/toggle` | POST | 切换代理 ON/OFF，状态持久化到 `data/proxy_state.json` |
| `/api/proxy/config` | PUT | 更新代理配置（超时/重试/熔断参数），持久化到 `data/config.json` |
| `/api/proxy/log` | GET | 最近 20 条故障转移日志（内存保留，不持久化） |

故障转移日志条目格式：

```json
{
  "timestamp": "2026-04-28T20:00:00",
  "from_provider": "glm",
  "to_provider": "minimax",
  "reason": "HTTP 500",
  "status_code": 500,
  "latency_ms": null
}
```

### 代理启动

代理开启后，Claude Code 的 `ANTHROPIC_BASE_URL` 设为 `http://localhost:5000/proxy`。Claude Code SDK 自动在 base_url 后拼接 `/v1/messages`，代理收到 `/proxy/v1/messages` 请求，将路径 `v1/messages` 转发到供应商。

## 3. health.py — 健康检测

### 检测机制

- APScheduler `BackgroundScheduler`，每 60s 执行一次全量检测
- 对每个供应商按 `health_check_path` 发送请求（默认 `GET /v1/models`）
- 使用 `httpx.Client`（同步）在调度器线程中执行

### 降级检测策略

当 `health_check_fallback: true` 时：

1. 尝试主检测端点（如 `GET /v1/models`）
2. 如果返回非 200 → 发送降级检测：`POST /v1/messages`，`max_tokens=1`，内容为 "hi"
3. 降级检测成功 → 标记为 `degraded`（可用但有延迟/功能限制）
4. 降级检测也失败 → 标记为 `unhealthy`

### 状态判定

| 条件 | 状态 | 颜色 |
|------|------|------|
| HTTP 200，延迟 < `HEALTH_DEGRADED_THRESHOLD` (2s) | healthy | 绿 |
| 降级检测成功，或延迟 2s-`HEALTH_TIMEOUT` (5s) | degraded | 黄 |
| 超时（`HEALTH_TIMEOUT`）或连接失败 | unhealthy | 红 |

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

超过 24h 的记录在每次检测后自动清理。所有 `data/` 下的 JSON 文件写入采用原子模式（写入临时文件后 `os.replace`），避免并发读写导致数据损坏。

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 所有供应商当前健康状态 |
| `/api/health/check/<name>` | POST | 立即触发单个供应商检测（同步执行，非调度） |
| `/api/health/history` | GET | 最近 24h 历史记录 |

### 与代理联动

`health.py` 暴露 `get_provider_status(name) -> dict` 函数，返回 `{status, latency_ms, last_check}`。`proxy.py` 在选择供应商时查询此函数判断是否跳过。

## 4. 用量查询（Phase 2）

当前供应商（GLM、MiniMax）均不支持 OpenAI billing 端点，Phase 1 不实现此功能。待至少一个供应商支持 billing API 后，在 Phase 2 中添加：

- 每供应商可配置 `billing_endpoint` 路径
- 5 分钟缓存，`supported: false` 结果同样缓存
- 标准化用量字段：`{balance, used, total}`

## 5. 前端 Tab 扩展

### Tab 结构

```
[供应商管理] [代理服务] [健康监控]
```

### 各 Tab 内容

**供应商管理（现有）：**
- 保持现有功能不变
- 卡片上新增健康状态灯（从 health API 读取）
- 新增"代理优先级"数字标识（对应 providers.json 的 `priority` 字段）

**代理服务：**
- 代理开关（ON/OFF toggle，调用 `/api/proxy/toggle`）
- 当前活跃供应商 + 实时请求统计
- 故障转移日志列表（最近 20 条，含时间、供应商、原因）
- 配置面板：超时、最大尝试数量、熔断阈值
- 开启代理后显示提示："请将 `ANTHROPIC_BASE_URL` 设为 `http://localhost:5000/proxy`"

**健康监控：**
- 供应商健康卡片网格（状态灯 + 延迟 ms + 可用模型列表）
- "全部检测"按钮 + 每个卡片的独立检测按钮
- 24h 延迟趋势图（纯 CSS 柱状图或 SVG，不引入 Chart.js）

### 交互

- Tab 内容首次点击时懒加载（延迟加载对应 Tab 的 JS 渲染函数）
- 健康数据每 60s 自动刷新（轮询 `/api/health`）
- 前端保持单文件 index.html，复用现有 CSS 变量和深色主题
- 代理 ON 时手动切换供应商仍然可用（代理下次请求自动使用新选择）

## 6. 依赖

```
flask              ← 已有
httpx              ← 新增：所有异步 HTTP（代理转发、健康检测）
apscheduler        ← 新增：定时任务
```

去掉了 aiohttp，统一使用 httpx。httpx 同时支持同步/异步客户端，代理转发用同步流式 API（`httpx.Client.stream()`），健康检测在调度器线程中同样用同步客户端。

## 7. 实施顺序

1. `config.py` — 全局配置常量
2. `providers/providers.json` — 扩展元数据字段（`priority`、`auth_type`、`health_check_path`、`health_check_fallback`）
3. `health.py` — 健康检测（不依赖代理，可独立开发测试）
4. `proxy.py` — 代理服务 + 故障转移（依赖 health 状态）
5. `app.py` — 注册 Blueprint + 启动调度器（`threaded=True`）
6. `templates/index.html` — Tab 扩展 + 各功能 UI

## 8. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| SSE 流式转发不完整 | 使用 httpx 同步流式 API（`Client.stream()` + `iter_bytes()`），逐 chunk 转发 |
| /v1/models 端点不存在 | 健康检测路径可配置 + 降级检测策略（轻量 messages 请求） |
| 多供应商 auth header 格式差异 | `auth_type` 字段按供应商配置：`x-api-key` 或 `Authorization: Bearer` |
| Claude Code SSE 中途断开的部分响应丢失 | 代理仅做透传，部分响应丢失不可避免；Claude Code 自身有重试机制 |
| index.html 行数增长 | 严格按 Tab 分区，每个 Tab 的 JS/CSS 独立函数 |
| Flask 单线程阻塞 | `app.run(threaded=True)` 允许并发处理代理长连接和 API 请求 |
| data/ JSON 文件并发读写 | 原子写入模式（临时文件 + `os.replace`） |
| 代理与手动切换冲突 | 代理从当前供应商开始尝试，手动切换即时生效，无需禁用/重启 |
