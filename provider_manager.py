"""Claude Code 模型供应商切换核心逻辑"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
BACKUP_DIR = CLAUDE_DIR / "provider-backups"
PROVIDERS_DIR = Path(__file__).parent / "providers"
META_FILE = PROVIDERS_DIR / "providers.json"

# 需要切换的 env 字段
SWITCHABLE_ENV_KEYS = [
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
]

# 内置默认元数据（首次运行迁移用）
_BUILTIN_META = {
    "glm": {"label": "智谱 AI (GLM)", "color": "#4A90D9", "icon": "G"},
    "m27": {"label": "MiniMax (M2.7)", "color": "#E67E22", "icon": "M"},
}


def _load_meta() -> dict:
    """加载供应商元数据，首次运行时自动迁移"""
    if not META_FILE.exists():
        _save_meta(_BUILTIN_META)
    with open(META_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_meta(meta: dict) -> None:
    """保存供应商元数据"""
    PROVIDERS_DIR.mkdir(parents=True, exist_ok=True)
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _load_env_file(env_path: Path) -> dict:
    """解析 .env 文件为字典"""
    env = {}
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def _save_env_file(env_path: Path, env: dict) -> None:
    """写入 .env 文件"""
    with open(env_path, "w") as f:
        for key in SWITCHABLE_ENV_KEYS:
            if key in env:
                f.write(f"{key}={env[key]}\n")


def _load_settings() -> dict:
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_settings(data: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _backup_settings() -> str:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"settings_{timestamp}.json"
    shutil.copy2(SETTINGS_FILE, backup_path)
    return str(backup_path)


def _valid_provider_id(name: str) -> bool:
    """检查供应商 ID 是否合法（仅允许字母、数字、下划线、连字符）"""
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', name))


def _load_provider_env(name: str) -> dict:
    """加载指定供应商的 .env 文件"""
    env_file = PROVIDERS_DIR / f"{name}.env"
    return _load_env_file(env_file) if env_file.exists() else {}


def _provider_summary(name: str, m: dict) -> dict:
    """构建供应商摘要字典"""
    return {
        "id": name,
        "label": m["label"],
        "color": m.get("color", "#888"),
        "icon": m.get("icon", name[0].upper()),
    }


def _extract_models(env: dict) -> dict:
    """从 env 字典中提取模型信息"""
    return {
        "haiku": env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", ""),
        "opus": env.get("ANTHROPIC_DEFAULT_OPUS_MODEL", ""),
        "sonnet": env.get("ANTHROPIC_DEFAULT_SONNET_MODEL", ""),
    }


def _build_url_to_provider(meta: dict) -> dict:
    """构建 base_url -> provider_name 的查找表"""
    mapping = {}
    for pname in meta:
        env = _load_provider_env(pname)
        url = env.get("ANTHROPIC_BASE_URL")
        if url:
            mapping[url] = pname
    return mapping

def get_all_providers() -> dict:
    """返回 {providers: [...], current_id: str}"""
    meta = _load_meta()
    settings = _load_settings()
    current_url = settings.get("env", {}).get("ANTHROPIC_BASE_URL", "")
    url_map = _build_url_to_provider(meta)
    current_id = url_map.get(current_url, "unknown")

    providers = []
    for name in sorted(meta):
        m = meta[name]
        env = _load_provider_env(name)
        entry = _provider_summary(name, m)
        entry["base_url"] = env.get("ANTHROPIC_BASE_URL", "")
        entry["models"] = _extract_models(env)
        providers.append(entry)
    return {"providers": providers, "current_id": current_id}


def get_current_provider() -> dict:
    settings = _load_settings()
    base_url = settings.get("env", {}).get("ANTHROPIC_BASE_URL", "")
    meta = _load_meta()
    url_map = _build_url_to_provider(meta)

    name = url_map.get(base_url)
    if name and name in meta:
        result = _provider_summary(name, meta[name])
        return result

    return {"id": "unknown", "label": "未知", "color": "#888", "icon": "?"}


def get_provider_detail(name: str) -> dict | None:
    """获取单个供应商的完整信息（用于编辑回显）"""
    meta = _load_meta()
    if name not in meta:
        return None
    env = _load_provider_env(name)
    result = _provider_summary(name, meta[name])
    result["env"] = {k: env.get(k, "") for k in SWITCHABLE_ENV_KEYS}
    return result


def get_settings_info() -> dict:
    settings = _load_settings()
    env = settings.get("env", {})
    plugins = settings.get("enabledPlugins", {})
    enabled_count = sum(1 for v in plugins.values() if v)
    total_count = len(plugins)
    return {
        "base_url": env.get("ANTHROPIC_BASE_URL", ""),
        "models": _extract_models(env),
        "plugins": {"enabled": enabled_count, "total": total_count},
        "language": settings.get("language", ""),
        "permission_mode": settings.get("permissions", {}).get("defaultMode", ""),
        "has_hooks": bool(settings.get("hooks")),
    }


def switch_provider(name: str) -> dict:
    meta = _load_meta()
    if name not in meta:
        return {"success": False, "message": f"未知供应商: {name}"}

    env_file = PROVIDERS_DIR / f"{name}.env"
    if not env_file.exists():
        return {"success": False, "message": f"配置文件不存在: {env_file}"}

    current = get_current_provider()
    if current["id"] == name:
        return {"success": True, "message": f"当前已是 {meta[name]['label']}，无需切换", "backup": ""}

    backup_path = _backup_settings()
    env_values = _load_env_file(env_file)
    settings = _load_settings()

    for key in SWITCHABLE_ENV_KEYS:
        if key in env_values:
            settings["env"][key] = env_values[key]

    _save_settings(settings)
    return {"success": True, "message": f"已切换到 {meta[name]['label']}", "backup": backup_path}


def add_provider(name: str, label: str, color: str, icon: str, env_vars: dict) -> dict:
    if not name:
        return {"success": False, "message": "供应商 ID 不能为空"}
    if not _valid_provider_id(name):
        return {"success": False, "message": "供应商 ID 仅允许字母、数字、下划线和连字符"}
    if not label:
        return {"success": False, "message": "显示名称不能为空"}

    meta = _load_meta()
    if name in meta:
        return {"success": False, "message": f"供应商 '{name}' 已存在"}

    meta[name] = {"label": label, "color": color, "icon": icon or name[0].upper()}
    _save_meta(meta)
    _save_env_file(PROVIDERS_DIR / f"{name}.env", env_vars)

    return {"success": True, "message": f"已添加供应商: {label}"}


def update_provider(name: str, label: str, color: str, icon: str, env_vars: dict) -> dict:
    meta = _load_meta()
    if name not in meta:
        return {"success": False, "message": f"供应商 '{name}' 不存在"}

    meta[name] = {"label": label, "color": color, "icon": icon or name[0].upper()}
    _save_meta(meta)
    _save_env_file(PROVIDERS_DIR / f"{name}.env", env_vars)

    return {"success": True, "message": f"已更新供应商: {label}"}


def delete_provider(name: str) -> dict:
    meta = _load_meta()
    if name not in meta:
        return {"success": False, "message": f"供应商 '{name}' 不存在"}

    current = get_current_provider()
    if current["id"] == name:
        return {"success": False, "message": "无法删除当前正在使用的供应商"}

    label = meta[name]["label"]
    del meta[name]
    _save_meta(meta)

    env_file = PROVIDERS_DIR / f"{name}.env"
    if env_file.exists():
        env_file.unlink()

    return {"success": True, "message": f"已删除供应商: {label}"}


def get_switch_history(limit: int = 10) -> list:
    if not BACKUP_DIR.exists():
        return []

    meta = _load_meta()
    url_map = _build_url_to_provider(meta)
    backups = sorted(BACKUP_DIR.glob("settings_*.json"), reverse=True)[:limit]
    history = []
    for bp in backups:
        try:
            with open(bp, "r") as f:
                data = json.load(f)
            base_url = data.get("env", {}).get("ANTHROPIC_BASE_URL", "")
            provider = url_map.get(base_url, "unknown")

            timestamp_str = bp.stem.replace("settings_", "")
            pm = meta.get(provider, {})
            history.append({
                "provider": provider,
                "label": pm.get("label", "未知"),
                "color": pm.get("color", "#888"),
                "timestamp": timestamp_str,
                "file": bp.name,
            })
        except (json.JSONDecodeError, KeyError):
            continue

    return history
