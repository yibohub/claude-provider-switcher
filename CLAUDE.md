# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作时提供指导。

## 项目概述

Claude Code 模型供应商切换 Web UI — 本地 Flask 工具，通过替换 `~/.claude/settings.json` 中的环境变量来切换 Claude Code 的模型供应商。仅修改 `env` 部分，其他设置保持不变。

## 运行

```bash
pip install -r requirements.txt
python app.py [--host 127.0.0.1] [--port 5000] [--debug]
```

无测试、无 lint、无构建步骤。

## 外部文件

本工具会读写项目目录之外的文件：
- `~/.claude/settings.json` — 读写（切换供应商环境变量，切换前自动备份）
- `~/.claude/provider-backups/` — 每次切换时创建带时间戳的 settings.json 备份副本

## 架构

```
app.py                  # Flask 路由 — 薄 JSON API 层，不含业务逻辑
provider_manager.py     # 全部核心逻辑：增删改查、切换、历史记录
templates/index.html    # 单页前端（内联 CSS + JS，无框架）
providers/              # 运行时数据（providers.json 元数据 + 每个供应商的 .env 文件）
```

**数据流：**
- 每个供应商在 `providers/` 下有一个 `.env` 文件，在 `providers/providers.json` 中有一条元数据（label、color、icon）。
- `switch_provider()` 读取目标 `.env`，将其中的键合并到 `~/.claude/settings.json` 的 `env` 块中，并将旧设置备份到 `~/.claude/provider-backups/`。
- `get_switch_history()` 通过 `_build_url_to_provider()` 查找表匹配备份文件与供应商。
- `get_all_providers()` 返回 `{"providers": [...], "current_id": str}` — 单次遍历同时确定当前供应商。
- `provider_manager.py` 中的 `SWITCHABLE_ENV_KEYS` 列表定义了受管理的环境变量。添加新的 env 键只需追加到该列表。

**关键辅助函数**（均为私有，位于 `provider_manager.py`）：
- `_load_provider_env(name)` — 加载供应商的 .env 文件
- `_provider_summary(name, m)` — 构建通用的 `{id, label, color, icon}` 字典
- `_extract_models(env)` — 从 env 字典提取 `{haiku, opus, sonnet}`
- `_build_url_to_provider(meta)` — 构建 `base_url -> provider_name` 查找表

## API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/providers` | GET | 所有供应商 + 当前供应商 ID |
| `/api/providers/<name>` | GET | 单个供应商详情 |
| `/api/providers` | POST | 添加供应商 |
| `/api/providers/<name>` | PUT | 更新供应商 |
| `/api/providers/<name>` | DELETE | 删除供应商 |
| `/api/switch/<name>` | POST | 切换到指定供应商 |
| `/api/status` | GET | 当前供应商 + 配置信息 |
| `/api/history` | GET | 最近 10 条切换记录 |

## 前端

单个 HTML 文件，使用原生 JS。通过 `fetch` 调用 JSON API。`refresh()` 函数通过 `Promise.all` 并行请求三个端点（`/api/providers`、`/api/status`、`/api/history`）。供应商卡片使用 `escapeHtml()` 防止 XSS。

## 约定

- Python：公开函数使用类型注解，返回字典中的消息使用中文
- API：所有端点返回 `{"success": bool, "message": str}` 格式；`app.py` 仅负责路由，所有逻辑在 `provider_manager.py` 中
- 无 ORM、无数据库 — 全部基于文件（JSON + .env）
