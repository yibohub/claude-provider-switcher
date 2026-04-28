# 新增供应商管理功能

## Context

当前 claude-provider-switcher 只支持预定义的两个供应商（GLM、M27），供应商元数据硬编码在 `provider_manager.py` 的 `PROVIDER_META` 字典中。需要支持动态添加/编辑/删除供应商，实现多供应商管理。

## 改动范围

### 1. provider_manager.py — 核心改动

**元数据持久化**：将硬编码的 `PROVIDER_META` 改为从 `providers/providers.json` 加载，支持动态增删改。

- 新增 `_load_meta()` / `_save_meta()` — 读写 `providers/providers.json`
- 新增 `add_provider(name, label, color, icon, env_vars)` — 创建 `.env` 文件 + 更新 meta
- 新增 `update_provider(name, env_vars)` — 更新已有供应商的 env 配置
- 新增 `delete_provider(name)` — 删除 `.env` 文件 + 从 meta 移除
- 修改所有使用 `PROVIDER_META` 的函数，改为调用 `_load_meta()`
- 首次运行时自动将现有 glm/m27 迁移到 `providers.json`（向后兼容）

**providers.json 格式**：
```json
{
  "glm": {"label": "智谱 AI (GLM)", "color": "#4A90D9", "icon": "G"},
  "m27": {"label": "MiniMax (M2.7)", "color": "#E67E22", "icon": "M"}
}
```

### 2. app.py — 新增 API 路由

- `POST /api/providers` — 添加供应商
- `PUT /api/providers/<name>` — 编辑供应商
- `DELETE /api/providers/<name>` — 删除供应商

### 3. templates/index.html — UI 增强

- 供应商区域新增"添加供应商"按钮
- 添加/编辑用同一个模态框（Modal），包含：
  - 名称（ID，用于 .env 文件名）
  - 显示名称
  - 颜色选择器
  - 图标（单字符）
  - 5 个环境变量输入框（Auth Token、Base URL、3 个模型名）
- 每个供应商卡片新增编辑/删除按钮（hover 时显示）
- 编辑时自动填充当前值

## 关键文件

- `/home/yeebo/myproject/claude-provider-switcher/provider_manager.py`
- `/home/yeebo/myproject/claude-provider-switcher/app.py`
- `/home/yeebo/myproject/claude-provider-switcher/templates/index.html`

## 验证方式

1. 启动服务，打开 UI
2. 点击"添加供应商"，填写信息，提交 → 新卡片出现
3. 切换到新供应商 → settings.json env 块正确更新
4. 编辑新供应商 → 修改生效
5. 删除新供应商 → 卡片消失，.env 文件删除
6. 刷新页面 → 数据持久化正确
