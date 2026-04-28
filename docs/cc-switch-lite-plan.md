# claude-provider-switcher → CC Switch Lite 改造方案

## 一、现状分析

### 项目概况
基于 yibohub/claude-provider-switcher，现有功能：
- 可视化管理多个 Claude Code 模型供应商
- 一键切换，自动备份当前配置
- 查看切换历史记录
- 查看当前配置状态（Base URL、模型、插件、权限等）
- 内置支持智谱 AI、MiniMax、DeepSeek 等国产供应商

### 技术栈
- 后端：Python + Flask
- 前端：原生 HTML/CSS/JS（无框架依赖）
- 存储：JSON + .env 文件（无数据库）
- 依赖：仅 flask

### 代码结构
```plaintext
app.py                 ← Flask 入口（约 100 行）
provider_manager.py    ← 核心逻辑（约 200 行）
providers/             ← .env 配置文件
templates/index.html   ← 前端
requirements.txt       ← 仅 flask
```

### 优势与瓶颈
- 优势：架构简洁，模块化好，无外部数据库依赖
- 瓶颈：纯 Flask 同步、无代理层、无健康检测、无用量统计

## 二、功能对比（现有 vs CC Switch）

- 供应商管理（增删改切）— 已有
- 用量查询（余额/配额）— 缺，工作量：中
- MCP 服务器管理 — 缺，工作量：大
- Prompts 提示词管理 — 缺，工作量：中
- Skills 技能管理 — 缺，工作量：大
- 会话管理器 — 缺，工作量：大
- 代理服务（本地转发）— 缺，工作量：中
- 故障转移（熔断/重试）— 缺，工作量：中
- 模型健康检测/延迟测试 — 缺，工作量：小
- 用量统计图表 — 缺，工作量：中

## 三、第一阶段：核心增强（建议优先，约 2-3 天）

### 3.1 代理服务 + 故障转移（proxy.py，新建）

架构：
```plaintext
Claude Code → localhost:5001（代理）→ 供应商A（主）
                                      ↓ 失败
                                      供应商B（备）
                                      ↓ 失败
                                      供应商C（备）
```

核心逻辑：
- 读取所有已配置供应商，按优先级排列
- 请求转发 + 流式响应透传（SSE）
- 失败判定：超时（可配置，默认 30s）、HTTP 429/500/502/503
- 熔断器：连续失败 N 次（默认 3）→ 标记不健康，跳过
- 健康恢复：每 60s 对不健康供应商发一次轻量检测（/v1/models）
- 代理模式下 BASE_URL 指向 http://localhost:5001，AUTH_TOKEN 由代理按当前活跃供应商自动填入

新增 API：
- POST /api/proxy/start — 启动代理
- POST /api/proxy/stop — 停止代理
- GET /api/proxy/status — 代理状态 + 各供应商健康度
- PUT /api/proxy/config — 配置超时、重试次数、熔断阈值

技术选型：aiohttp（异步 + 流式转发）或 Flask + requests（简单但流式稍弱）

### 3.2 健康检测 + 模型检查（health.py，新建）

功能：
- 定时（可配置间隔）对每个供应商发检测请求
- 检测内容：连通性 + 模型列表 + 延迟
- Web UI 显示：绿灯🟢/黄灯🟡/红灯🔴 + 延迟 ms

新增 API：
- GET /api/health — 所有供应商健康状态
- POST /api/health/check/ — 手动触发单个检测
- GET /api/health/history — 历史检测记录（最近 24h）

### 3.3 用量查询（usage.py，新建）

功能：
- 支持 OpenAI 兼容格式：GET /v1/dashboard/billing/usage
- 支持 Anthropic 格式：按需适配
- 部分国产供应商（智谱/MiniMax）可能有专属 API
- 缓存结果（5 分钟不过期就不重新请求）
- Web UI 显示：剩余额度/已用量/用量趋势

新增 API：
- GET /api/usage/ — 单个供应商用量
- GET /api/usage — 所有供应商用量汇总

## 四、第二阶段：扩展功能（按需，每个约 1-2 天）

### 4.1 MCP 服务器管理
- 读写 ~/.claude/settings.json 中的 mcpServers 配置
- 预设常用 MCP 服务器（一键添加）
- 启用/禁用/删除

### 4.2 Prompts 提示词管理
- 读写 ~/.claude/CLAUDE.md 或自定义 prompt 文件
- 创建预设模板，一键切换/激活
- 语法高亮编辑

### 4.3 Skills 技能管理
- 管理 ~/.claude/skills/ 目录
- 从 GitHub 仓库发现/安装技能
- SHA-256 更新检测

### 4.4 会话管理器
- 读取 ~/.claude/projects/ 下的会话历史
- 搜索、浏览、恢复会话
- 会话统计（按日期/项目/供应商）

### 4.5 用量统计图表
- 记录每次 API 调用的 token 用量
- 按天/供应商/模型维度聚合
- 简单折线图（Chart.js 或纯 CSS）

## 五、技术方案

### 依赖升级
```plaintext
flask            ← 已有
flask-cors       ← 新增（如需跨域）
aiohttp          ← 代理层异步
httpx            ← 健康检测（async）
apscheduler      ← 定时任务（健康检测）
```

### 目录结构（改造后）
```plaintext
app.py                    ← Flask 入口（扩展路由）
provider_manager.py       ← 现有，基本不动
proxy.py                  ← 新增：代理服务 + 故障转移
health.py                 ← 新增：健康检测
usage.py                  ← 新增：用量查询
session_manager.py        ← 新增：会话管理（第二阶段）
config.py                 ← 新增：全局配置
templates/
  index.html              ← 现有前端（扩展 Tab 页）
  proxy.html              ← 新增：代理管理页
  health.html             ← 新增：健康监控页
static/
  js/proxy.js
  css/...
providers/                ← 现有，不动
data/
  health_log.json         ← 健康检测记录
  usage_cache.json        ← 用量缓存
```

### 启动方式改造
```python
# app.py 改造
app.register_blueprint(proxy_bp)     # /api/proxy/*
app.register_blueprint(health_bp)    # /api/health/*
app.register_blueprint(usage_bp)     # /api/usage/*

# 代理作为独立线程/进程启动，不阻塞 Flask
```

## 六、实施顺序

- config.py 全局配置 — 0.5 天
- health.py 健康检测 — 0.5 天
- proxy.py 代理 + 故障转移 — 1.5 天
- usage.py 用量查询 — 0.5 天
- 前端扩展（Tab 页 + 健康面板 + 代理面板）— 1 天

## 七、故障转移上下文说明

自动故障转移模式下，上下文处理规则：
- 同一个请求重试到不同供应商 → 上下文不丢（请求体一样）
- 供应商A的部分响应已经返回了一半 → 这一半丢了，供应商B 从头重新生成
- 请求完全失败（429/500）→ 无影响，供应商B 完整生成
- 响应到一半断开 → 会丢内容，但 Claude Code 自身有重试机制

## 八、风险点

1. 流式转发：Claude Code 用 SSE 流式响应，代理必须完整透传，否则体验很差
2. 多供应商认证差异：不同供应商的 auth header 格式可能不同，需要适配
3. 并发冲突：代理转发和手动切换可能冲突，需要加锁或状态同步

---

文档创建时间：2026-04-28
方案提供：云栖墨
