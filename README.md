# Claude Code 供应商切换工具

通过 Web UI 一键切换 Claude Code 的模型供应商。仅替换 `~/.claude/settings.json` 中的环境变量，其他设置保持不变。

## 功能

- 可视化管理多个 Claude Code 模型供应商
- 一键切换，自动备份当前配置
- 查看切换历史记录
- 查看当前配置状态（Base URL、模型、插件、权限等）
- 内置支持智谱 AI、MiniMax、DeepSeek 等国产供应商

## 快速开始

```bash
pip install -r requirements.txt
python app.py
```

打开浏览器访问 http://127.0.0.1:5000

## 启动参数

```bash
python app.py --host 0.0.0.0 --port 8080 --debug
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | 127.0.0.1 | 监听地址 |
| `--port` | 5000 | 监听端口 |
| `--debug` | 关闭 | 开启调试模式 |

## 工作原理

```
providers/glm.env          providers/deepseek.env       providers/m27.env
      │                          │                          │
      ▼                          ▼                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    点击切换供应商卡片                          │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
              ~/.claude/settings.json
              ┌─────────────────┐
              │ env:            │
              │   AUTH_TOKEN    │ ← 替换
              │   BASE_URL      │ ← 替换
              │   HAIKU_MODEL   │ ← 替换
              │   OPUS_MODEL    │ ← 替换
              │   SONNET_MODEL  │ ← 替换
              │ ...             │ ← 不动
              └─────────────────┘
```

1. 每个供应商对应一个 `.env` 文件，存储该供应商的 API Token、Base URL 和模型映射
2. 切换时，工具读取目标 `.env`，将其中的环境变量写入 `~/.claude/settings.json` 的 `env` 块
3. 切换前自动备份当前配置到 `~/.claude/provider-backups/`

## 管理的文件

| 路径 | 用途 |
|------|------|
| `providers/providers.json` | 供应商元数据（名称、颜色、图标） |
| `providers/<name>.env` | 各供应商的环境变量配置 |
| `~/.claude/settings.json` | Claude Code 配置（读写） |
| `~/.claude/provider-backups/` | 切换历史备份 |

## 添加自定义供应商

1. 在 Web UI 中点击「添加供应商」
2. 填写供应商信息：
   - **供应商 ID**：英文标识（如 `myprovider`）
   - **显示名称**：如 `我的供应商`
   - **Auth Token**：API 认证令牌
   - **Base URL**：API 地址（如 `https://api.example.com/anthropic`）
   - **模型映射**：Haiku / Opus / Sonnet 分别对应的模型标识

或手动创建文件：

```bash
# 创建元数据
echo '{"myprovider": {"label": "我的供应商", "color": "#4A90D9", "icon": "M"}}' >> providers/providers.json

# 创建环境变量文件
cat > providers/myprovider.env << 'EOF'
ANTHROPIC_AUTH_TOKEN=your-token-here
ANTHROPIC_BASE_URL=https://api.example.com/anthropic
ANTHROPIC_DEFAULT_HAIKU_MODEL=your-haiku-model
ANTHROPIC_DEFAULT_OPUS_MODEL=your-opus-model
ANTHROPIC_DEFAULT_SONNET_MODEL=your-sonnet-model
EOF
```

## 环境变量说明

| 变量 | 说明 |
|------|------|
| `ANTHROPIC_AUTH_TOKEN` | API 认证令牌 |
| `ANTHROPIC_BASE_URL` | API 基础地址 |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Haiku 模型标识 |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Opus 模型标识 |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Sonnet 模型标识 |

## 技术栈

- **后端**：Python + Flask
- **前端**：原生 HTML/CSS/JS（无框架依赖）
- **存储**：JSON + .env 文件（无数据库）

## API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/providers` | GET | 获取所有供应商 |
| `/api/providers/<name>` | GET | 获取供应商详情 |
| `/api/providers` | POST | 添加供应商 |
| `/api/providers/<name>` | PUT | 更新供应商 |
| `/api/providers/<name>` | DELETE | 删除供应商 |
| `/api/switch/<name>` | POST | 切换供应商 |
| `/api/status` | GET | 当前状态 |
| `/api/history` | GET | 切换历史 |

## 开机启动（systemd）

```bash
# 安装服务（复制 service 文件并重载 systemd）
sudo cp claude-provider-switcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable claude-provider-switcher   # 开机自启
sudo systemctl start claude-provider-switcher    # 立即启动

# 常用命令
sudo systemctl status claude-provider-switcher   # 查看状态
sudo systemctl restart claude-provider-switcher   # 重启
sudo systemctl stop claude-provider-switcher      # 停止
sudo systemctl disable claude-provider-switcher   # 禁用开机启动
```

默认监听 `0.0.0.0:5000`，支持局域网访问。

### 卸载

```bash
# 停止并禁用服务
sudo systemctl stop claude-provider-switcher
sudo systemctl disable claude-provider-switcher

# 删除 service 文件
sudo rm /etc/systemd/system/claude-provider-switcher.service
sudo systemctl daemon-reload

# （可选）清理备份目录
rm -rf ~/.claude/provider-backups/
```

## License

MIT
