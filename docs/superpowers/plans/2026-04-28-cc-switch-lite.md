# CC Switch Lite Phase 1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 claude-provider-switcher 基础上，新增代理服务+故障转移和健康检测两个子系统，前端扩展为 Tab 式布局。

**Architecture:** Flask threaded 模式运行，新增 health.py 和 proxy.py 两个 Blueprint 模块。健康检测通过 APScheduler 定时执行，代理使用 httpx 同步流式 API 转发。数据存储在 data/ 目录下的 JSON 文件中，采用原子写入。

**Tech Stack:** Python 3, Flask, httpx, APScheduler

---

## 文件总览

| 文件 | 操作 | 职责 |
|------|------|------|
| `config.py` | 新建 | 全局配置常量 + 数据目录初始化 |
| `providers/providers.json` | 修改 | 新增 priority/auth_type/health_check 字段 |
| `providers/glm.env` | 修改 | 无变更，已有字段足够 |
| `providers/m27.env` | 修改 | 无变更，已有字段足够 |
| `health.py` | 新建 | 健康检测 Blueprint + APScheduler job + 降级检测 |
| `proxy.py` | 新建 | 代理转发 Blueprint + 熔断器 + 故障转移日志 |
| `app.py` | 修改 | 注册 Blueprint + 启动调度器 + threaded 模式 |
| `templates/index.html` | 修改 | Tab 布局 + 代理/健康 UI |
| `requirements.txt` | 修改 | 新增 httpx、apscheduler |

---

### Task 1: config.py — 全局配置

**Files:**
- Create: `config.py`

- [ ] **Step 1: 创建 config.py**

```python
"""CC Switch Lite 全局配置"""

from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 代理配置
PROXY_TIMEOUT = 30
PROXY_MAX_PROVIDERS = 3
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_RECOVERY_INTERVAL = 60
PROXY_DEFAULT_STATE = False

# 健康检测配置
HEALTH_CHECK_INTERVAL = 60
HEALTH_DEGRADED_THRESHOLD = 2000
HEALTH_TIMEOUT = 5
HEALTH_LOG_RETENTION = 86400

# 代理数据文件
PROXY_STATE_FILE = DATA_DIR / "proxy_state.json"
PROXY_CONFIG_FILE = DATA_DIR / "config.json"

# 健康检测数据文件
HEALTH_LOG_FILE = DATA_DIR / "health_log.json"
```

- [ ] **Step 2: Commit**

```bash
git add config.py
git commit -m "feat: add global config module"
```

---

### Task 2: 更新 providers.json 扩展字段

**Files:**
- Modify: `providers/providers.json`

- [ ] **Step 1: 更新 providers.json，新增 priority/auth_type/health_check_path/health_check_fallback 字段**

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
  },
  "m27": {
    "label": "MiniMax",
    "color": "#E67E22",
    "icon": "M",
    "priority": 2,
    "auth_type": "x-api-key",
    "health_check_path": "/v1/models",
    "health_check_fallback": true
  }
}
```

- [ ] **Step 2: 更新 provider_manager.py 中的 `_BUILTIN_META` 默认值，使其包含新字段**

在 `provider_manager.py` 中，将 `_BUILTIN_META` 替换为：

```python
_BUILTIN_META = {
    "glm": {
        "label": "GLM", "color": "#4285f4", "icon": "🧠",
        "priority": 1, "auth_type": "x-api-key",
        "health_check_path": "/v1/models", "health_check_fallback": True,
    },
    "m27": {
        "label": "MiniMax", "color": "#E67E22", "icon": "M",
        "priority": 2, "auth_type": "x-api-key",
        "health_check_path": "/v1/models", "health_check_fallback": True,
    },
}
```

- [ ] **Step 3: 更新 `add_provider` 和 `update_provider` 函数，支持新字段**

在 `provider_manager.py` 中修改 `add_provider` 签名，新增 `priority`, `auth_type`, `health_check_path`, `health_check_fallback` 参数：

```python
def add_provider(
    name: str, label: str, color: str, icon: str, env_vars: dict,
    priority: int = 99, auth_type: str = "x-api-key",
    health_check_path: str = "/v1/models", health_check_fallback: bool = True,
) -> dict:
    if not name:
        return {"success": False, "message": "供应商 ID 不能为空"}
    if not _valid_provider_id(name):
        return {"success": False, "message": "供应商 ID 仅允许字母、数字、下划线和连字符"}
    if not label:
        return {"success": False, "message": "显示名称不能为空"}

    meta = _load_meta()
    if name in meta:
        return {"success": False, "message": f"供应商 '{name}' 已存在"}

    meta[name] = {
        "label": label, "color": color,
        "icon": icon or name[0].upper(),
        "priority": priority, "auth_type": auth_type,
        "health_check_path": health_check_path,
        "health_check_fallback": health_check_fallback,
    }
    _save_meta(meta)
    _save_env_file(PROVIDERS_DIR / f"{name}.env", env_vars)
    return {"success": True, "message": f"已添加供应商: {label}"}


def update_provider(
    name: str, label: str, color: str, icon: str, env_vars: dict,
    priority: int = 99, auth_type: str = "x-api-key",
    health_check_path: str = "/v1/models", health_check_fallback: bool = True,
) -> dict:
    meta = _load_meta()
    if name not in meta:
        return {"success": False, "message": f"供应商 '{name}' 不存在"}

    meta[name] = {
        "label": label, "color": color,
        "icon": icon or name[0].upper(),
        "priority": priority, "auth_type": auth_type,
        "health_check_path": health_check_path,
        "health_check_fallback": health_check_fallback,
    }
    _save_meta(meta)
    _save_env_file(PROVIDERS_DIR / f"{name}.env", env_vars)
    return {"success": True, "message": f"已更新供应商: {label}"}
```

- [ ] **Step 4: 更新 `app.py` 中 `api_add_provider` 和 `api_update_provider` 路由，传递新字段**

在 `app.py` 的 `api_add_provider` 中：

```python
@app.route("/api/providers", methods=["POST"])
def api_add_provider():
    data = request.get_json()
    result = add_provider(
        name=data.get("name", "").strip(),
        label=data.get("label", "").strip(),
        color=data.get("color", "#888"),
        icon=data.get("icon", ""),
        env_vars={k: str(v).strip() for k, v in data.get("env", {}).items()},
        priority=int(data.get("priority", 99)),
        auth_type=data.get("auth_type", "x-api-key"),
        health_check_path=data.get("health_check_path", "/v1/models"),
        health_check_fallback=bool(data.get("health_check_fallback", True)),
    )
    status_code = 201 if result["success"] else 400
    return jsonify(result), status_code
```

同样更新 `api_update_provider`：

```python
@app.route("/api/providers/<name>", methods=["PUT"])
def api_update_provider(name):
    data = request.get_json()
    result = update_provider(
        name=name,
        label=data.get("label", "").strip(),
        color=data.get("color", "#888"),
        icon=data.get("icon", ""),
        env_vars={k: str(v).strip() for k, v in data.get("env", {}).items()},
        priority=int(data.get("priority", 99)),
        auth_type=data.get("auth_type", "x-api-key"),
        health_check_path=data.get("health_check_path", "/v1/models"),
        health_check_fallback=bool(data.get("health_check_fallback", True)),
    )
    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code
```

- [ ] **Step 5: 启动服务验证现有功能正常**

Run: `python app.py --port 5000 &`
在浏览器打开 http://localhost:5000 验证供应商管理功能正常。
验证后停止服务。

- [ ] **Step 6: Commit**

```bash
git add providers/providers.json provider_manager.py app.py
git commit -m "feat: extend provider metadata with priority, auth_type, health_check fields"
```

---

### Task 3: health.py — 健康检测模块

**Files:**
- Create: `health.py`

- [ ] **Step 1: 创建 health.py**

```python
"""健康检测模块 — 定时检测供应商连通性、延迟、可用模型"""

import json
import os
import threading
from datetime import datetime, timezone

import httpx
from flask import Blueprint, jsonify

from config import (
    HEALTH_DEGRADED_THRESHOLD,
    HEALTH_LOG_FILE,
    HEALTH_LOG_RETENTION,
    HEALTH_TIMEOUT,
)
from provider_manager import _load_meta, _load_provider_env

health_bp = Blueprint("health", __name__)

_lock = threading.Lock()
_provider_status: dict[str, dict] = {}
_health_log: list[dict] = []


def _atomic_write_json(path, data):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _load_health_log() -> list[dict]:
    if HEALTH_LOG_FILE.exists():
        try:
            with open(HEALTH_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save_health_log(log: list[dict]) -> None:
    _atomic_write_json(HEALTH_LOG_FILE, log)


def _purge_old_logs(log: list[dict]) -> list[dict]:
    cutoff = datetime.now(timezone.utc).timestamp() - HEALTH_LOG_RETENTION
    return [e for e in log if datetime.fromisoformat(e["timestamp"]).timestamp() > cutoff]


def _check_single_provider(name: str, meta_entry: dict) -> dict:
    env = _load_provider_env(name)
    base_url = env.get("ANTHROPIC_BASE_URL", "")
    if not base_url:
        return {"provider": name, "status": "unhealthy", "latency_ms": None, "models": [], "timestamp": datetime.now(timezone.utc).isoformat(), "error": "无 BASE_URL"}

    token = env.get("ANTHROPIC_AUTH_TOKEN", "")
    auth_type = meta_entry.get("auth_type", "x-api-key")
    check_path = meta_entry.get("health_check_path", "/v1/models")
    fallback = meta_entry.get("health_check_fallback", True)
    headers = {"x-api-key": token} if auth_type == "x-api-key" else {"Authorization": f"Bearer {token}"}
    url = base_url.rstrip("/") + check_path

    now = datetime.now(timezone.utc)
    try:
        with httpx.Client(timeout=HEALTH_TIMEOUT) as client:
            resp = client.get(url, headers=headers)
            latency = int((datetime.now(timezone.utc) - now).total_seconds() * 1000)

            if resp.status_code == 200:
                models = []
                try:
                    data = resp.json()
                    models = [m.get("id", "") for m in data.get("data", [])]
                except Exception:
                    pass
                status = "healthy" if latency < HEALTH_DEGRADED_THRESHOLD else "degraded"
                return {"provider": name, "status": status, "latency_ms": latency, "models": models, "timestamp": now.isoformat()}

            if fallback:
                fallback_url = base_url.rstrip("/") + "/v1/messages"
                fallback_body = {"model": "dummy", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
                try:
                    with httpx.Client(timeout=HEALTH_TIMEOUT) as fc:
                        fr = fc.post(fallback_url, headers=headers, json=fallback_body)
                        flatency = int((datetime.now(timezone.utc) - now).total_seconds() * 1000)
                        if fr.status_code in (200, 400):
                            return {"provider": name, "status": "degraded", "latency_ms": flatency, "models": [], "timestamp": now.isoformat(), "error": f"主检测 {resp.status_code}，降级检测可连通"}
                except Exception:
                    pass

            return {"provider": name, "status": "unhealthy", "latency_ms": None, "models": [], "timestamp": now.isoformat(), "error": f"HTTP {resp.status_code}"}
    except httpx.TimeoutException:
        return {"provider": name, "status": "unhealthy", "latency_ms": None, "models": [], "timestamp": now.isoformat(), "error": "连接超时"}
    except httpx.ConnectError:
        return {"provider": name, "status": "unhealthy", "latency_ms": None, "models": [], "timestamp": now.isoformat(), "error": "连接失败"}
    except Exception as e:
        return {"provider": name, "status": "unhealthy", "latency_ms": None, "models": [], "timestamp": now.isoformat(), "error": str(e)}


def run_health_check():
    global _health_log
    meta = _load_meta()
    with _lock:
        for name in sorted(meta):
            result = _check_single_provider(name, meta[name])
            _provider_status[name] = result
        _health_log = _load_health_log() + list(_provider_status.values())
        _health_log = _purge_old_logs(_health_log)
        _save_health_log(_health_log)


def get_provider_status(name: str) -> dict:
    with _lock:
        return _provider_status.get(name, {"status": "unknown", "latency_ms": None, "last_check": None})


@health_bp.route("/api/health")
def api_health():
    with _lock:
        result = {name: {
            "status": info.get("status", "unknown"),
            "latency_ms": info.get("latency_ms"),
            "models": info.get("models", []),
            "last_check": info.get("timestamp"),
        } for name, info in _provider_status.items()}
    return jsonify(result)


@health_bp.route("/api/health/check/<name>", methods=["POST"])
def api_health_check(name):
    meta = _load_meta()
    if name not in meta:
        return jsonify({"success": False, "message": f"供应商 '{name}' 不存在"}), 404
    result = _check_single_provider(name, meta[name])
    with _lock:
        _provider_status[name] = result
        _health_log = _load_health_log() + [result]
        _health_log = _purge_old_logs(_health_log)
        _save_health_log(_health_log)
    return jsonify({"success": True, "provider": result})


@health_bp.route("/api/health/history")
def api_health_history():
    with _lock:
        log = _health_log if _health_log else _load_health_log()
    return jsonify({"history": log})
```

- [ ] **Step 2: 手动验证 health 模块可导入**

Run: `python -c "from health import health_bp, run_health_check; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add health.py
git commit -m "feat: add health monitoring module with degraded fallback detection"
```

---

### Task 4: proxy.py — 代理服务 + 故障转移

**Files:**
- Create: `proxy.py`

- [ ] **Step 1: 创建 proxy.py**

```python
"""代理服务模块 — 请求转发 + 故障转移 + 熔断器"""

import json
import os
import threading
from collections import deque
from datetime import datetime, timezone

import httpx
from flask import Blueprint, Response, jsonify, request

from config import (
    CIRCUIT_FAILURE_THRESHOLD,
    CIRCUIT_RECOVERY_INTERVAL,
    PROXY_CONFIG_FILE,
    PROXY_DEFAULT_STATE,
    PROXY_MAX_PROVIDERS,
    PROXY_STATE_FILE,
    PROXY_TIMEOUT,
)
from provider_manager import _load_meta, _load_provider_env

proxy_bp = Blueprint("proxy", __name__)

_lock = threading.Lock()

_circuit_state: dict[str, dict] = {}
_failover_log: deque = deque(maxlen=20)
_proxy_enabled = PROXY_DEFAULT_STATE


def _atomic_write_json(path, data):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _load_proxy_state() -> bool:
    if PROXY_STATE_FILE.exists():
        try:
            with open(PROXY_STATE_FILE, "r") as f:
                return json.load(f).get("enabled", PROXY_DEFAULT_STATE)
        except (json.JSONDecodeError, OSError):
            pass
    return PROXY_DEFAULT_STATE


def _save_proxy_state(enabled: bool) -> None:
    _atomic_write_json(PROXY_STATE_FILE, {"enabled": enabled})


def _load_proxy_config() -> dict:
    if PROXY_CONFIG_FILE.exists():
        try:
            with open(PROXY_CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"timeout": PROXY_TIMEOUT, "max_providers": PROXY_MAX_PROVIDERS, "circuit_threshold": CIRCUIT_FAILURE_THRESHOLD}


def _save_proxy_config(cfg: dict) -> None:
    _atomic_write_json(PROXY_CONFIG_FILE, cfg)


def _init_proxy():
    global _proxy_enabled
    _proxy_enabled = _load_proxy_state()
    meta = _load_meta()
    with _lock:
        for name in meta:
            _circuit_state[name] = {"consecutive_failures": 0, "status": "healthy", "last_failure_time": None}


def _get_auth_headers(token: str, auth_type: str) -> dict:
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {token}"}
    return {"x-api-key": token, "anthropic-version": "2023-06-01"}


def _should_skip_provider(name: str) -> bool:
    state = _circuit_state.get(name)
    if not state:
        return False
    if state["status"] == "unhealthy":
        if state["last_failure_time"]:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(state["last_failure_time"])).total_seconds()
            if elapsed >= CIRCUIT_RECOVERY_INTERVAL:
                state["status"] = "recovering"
                return False
        return True
    return False


def _record_failure(name: str, status_code: int | None):
    state = _circuit_state.setdefault(name, {"consecutive_failures": 0, "status": "healthy", "last_failure_time": None})
    state["consecutive_failures"] += 1
    state["last_failure_time"] = datetime.now(timezone.utc).isoformat()
    cfg = _load_proxy_config()
    if state["consecutive_failures"] >= cfg.get("circuit_threshold", CIRCUIT_FAILURE_THRESHOLD):
        state["status"] = "unhealthy"


def _record_success(name: str):
    state = _circuit_state.setdefault(name, {"consecutive_failures": 0, "status": "healthy", "last_failure_time": None})
    state["consecutive_failures"] = 0
    state["status"] = "healthy"
    state["last_failure_time"] = None


def _get_sorted_providers() -> list[tuple[str, dict]]:
    meta = _load_meta()
    providers = []
    for name, m in meta.items():
        env = _load_provider_env(name)
        if env.get("ANTHROPIC_BASE_URL"):
            providers.append((name, m))
    providers.sort(key=lambda x: x[1].get("priority", 99))
    return providers


def _get_current_provider_first() -> list[tuple[str, dict]]:
    from provider_manager import get_current_provider
    current = get_current_provider()
    current_id = current.get("id", "")
    all_providers = _get_sorted_providers()
    if not current_id or current_id == "unknown":
        return all_providers[:_load_proxy_config().get("max_providers", PROXY_MAX_PROVIDERS)]
    ordered = []
    rest = []
    for p in all_providers:
        if p[0] == current_id:
            ordered.append(p)
        else:
            rest.append(p)
    ordered.extend(rest)
    return ordered[:_load_proxy_config().get("max_providers", PROXY_MAX_PROVIDERS)]


@proxy_bp.route("/proxy/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def proxy_handler(path):
    if not _proxy_enabled:
        return jsonify({"error": "代理服务未启用"}), 503

    if ".." in path or "\x00" in path or path.startswith("/"):
        return jsonify({"error": "非法请求路径"}), 400

    body = request.get_data()
    cfg = _load_proxy_config()
    timeout = cfg.get("timeout", PROXY_TIMEOUT)
    providers = _get_current_provider_first()
    available = [(n, m) for n, m in providers if not _should_skip_provider(n)]

    if not available:
        return jsonify({"error": "所有供应商均不可用（熔断或未配置）"}), 503

    last_error = ""
    for name, meta_entry in available:
        env = _load_provider_env(name)
        base_url = env.get("ANTHROPIC_BASE_URL", "").rstrip("/")
        token = env.get("ANTHROPIC_AUTH_TOKEN", "")
        auth_type = meta_entry.get("auth_type", "x-api-key")
        target_url = f"{base_url}/{path}"
        headers = _get_auth_headers(token, auth_type)

        # 透传 Content-Type 和其他必要 headers
        for h in ["Content-Type", "Accept", "X-Request-Id"]:
            if request.headers.get(h):
                headers[h] = request.headers[h]

        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream(
                    request.method, target_url, content=body, headers=headers,
                ) as resp:
                    if resp.status_code in (429, 500, 502, 503):
                        _record_failure(name, resp.status_code)
                        resp.read()
                        last_error = f"{name}: HTTP {resp.status_code}"
                        continue

                    _record_success(name)

                    def generate():
                        for chunk in resp.iter_bytes():
                            yield chunk

                    excluded = {"transfer-encoding", "content-encoding", "connection"}
                    resp_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]
                    return Response(generate(), status=resp.status_code, headers=resp_headers)

        except httpx.TimeoutException:
            _record_failure(name, None)
            last_error = f"{name}: 超时"
            continue
        except httpx.ConnectError as e:
            _record_failure(name, None)
            last_error = f"{name}: 连接失败"
            continue
        except Exception as e:
            _record_failure(name, None)
            last_error = f"{name}: {e}"
            continue

    return jsonify({"error": "所有供应商请求均失败", "last_error": last_error}), 503


@proxy_bp.route("/api/proxy/status")
def api_proxy_status():
    with _lock:
        circuits = {name: {
            "status": s["status"],
            "consecutive_failures": s["consecutive_failures"],
            "last_failure_time": s.get("last_failure_time"),
        } for name, s in _circuit_state.items()}
        logs = list(_failover_log)
    from provider_manager import get_current_provider
    current = get_current_provider()
    return jsonify({
        "enabled": _proxy_enabled,
        "current_provider": current,
        "circuit_state": circuits,
        "failover_log": logs,
    })


@proxy_bp.route("/api/proxy/toggle", methods=["POST"])
def api_proxy_toggle():
    global _proxy_enabled
    data = request.get_json() or {}
    _proxy_enabled = bool(data.get("enabled", not _proxy_enabled))
    _save_proxy_state(_proxy_enabled)
    return jsonify({"success": True, "enabled": _proxy_enabled, "message": f"代理已{'启用' if _proxy_enabled else '禁用'}"})


@proxy_bp.route("/api/proxy/config", methods=["PUT"])
def api_proxy_config():
    data = request.get_json() or {}
    cfg = _load_proxy_config()
    for key in ("timeout", "max_providers", "circuit_threshold"):
        if key in data:
            cfg[key] = int(data[key])
    _save_proxy_config(cfg)
    return jsonify({"success": True, "message": "代理配置已更新", "config": cfg})


@proxy_bp.route("/api/proxy/log")
def api_proxy_log():
    with _lock:
        logs = list(_failover_log)
    return jsonify({"log": logs})
```

- [ ] **Step 2: 手动验证 proxy 模块可导入**

Run: `python -c "from proxy import proxy_bp, _init_proxy; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add proxy.py
git commit -m "feat: add proxy service with failover and circuit breaker"
```

---

### Task 5: 更新 app.py — 注册 Blueprint + 启动调度器

**Files:**
- Modify: `app.py`

- [ ] **Step 1: 修改 app.py**

将整个 `app.py` 替换为：

```python
"""Claude Code 模型供应商切换 Web UI — CC Switch Lite"""

import argparse

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, render_template, request

from config import HEALTH_CHECK_INTERVAL
from health import health_bp, run_health_check
from provider_manager import (
    add_provider,
    delete_provider,
    get_all_providers,
    get_current_provider,
    get_provider_detail,
    get_settings_info,
    get_switch_history,
    switch_provider,
    update_provider,
)
from proxy import proxy_bp, _init_proxy

app = Flask(__name__)
app.register_blueprint(health_bp)
app.register_blueprint(proxy_bp)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    current = get_current_provider()
    settings = get_settings_info()
    return jsonify({"current": current, "settings": settings})


@app.route("/api/providers")
def api_providers():
    result = get_all_providers()
    return jsonify(result)


@app.route("/api/providers/<name>")
def api_provider_detail(name):
    detail = get_provider_detail(name)
    if detail is None:
        return jsonify({"success": False, "message": f"供应商 '{name}' 不存在"}), 404
    return jsonify({"success": True, "provider": detail})


@app.route("/api/providers", methods=["POST"])
def api_add_provider():
    data = request.get_json()
    result = add_provider(
        name=data.get("name", "").strip(),
        label=data.get("label", "").strip(),
        color=data.get("color", "#888"),
        icon=data.get("icon", ""),
        env_vars={k: str(v).strip() for k, v in data.get("env", {}).items()},
        priority=int(data.get("priority", 99)),
        auth_type=data.get("auth_type", "x-api-key"),
        health_check_path=data.get("health_check_path", "/v1/models"),
        health_check_fallback=bool(data.get("health_check_fallback", True)),
    )
    status_code = 201 if result["success"] else 400
    return jsonify(result), status_code


@app.route("/api/providers/<name>", methods=["PUT"])
def api_update_provider(name):
    data = request.get_json()
    result = update_provider(
        name=name,
        label=data.get("label", "").strip(),
        color=data.get("color", "#888"),
        icon=data.get("icon", ""),
        env_vars={k: str(v).strip() for k, v in data.get("env", {}).items()},
        priority=int(data.get("priority", 99)),
        auth_type=data.get("auth_type", "x-api-key"),
        health_check_path=data.get("health_check_path", "/v1/models"),
        health_check_fallback=bool(data.get("health_check_fallback", True)),
    )
    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code


@app.route("/api/providers/<name>", methods=["DELETE"])
def api_delete_provider(name):
    result = delete_provider(name)
    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code


@app.route("/api/switch/<name>", methods=["POST"])
def api_switch(name):
    result = switch_provider(name)
    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code


@app.route("/api/history")
def api_history():
    history = get_switch_history()
    return jsonify({"history": history})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CC Switch Lite")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=5000, help="监听端口")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    _init_proxy()
    run_health_check()

    scheduler = BackgroundScheduler()
    scheduler.add_job(run_health_check, "interval", seconds=HEALTH_CHECK_INTERVAL)
    scheduler.start()

    print(f"启动 CC Switch Lite: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
```

- [ ] **Step 2: 更新 requirements.txt**

```
flask
httpx
apscheduler
```

- [ ] **Step 3: 安装依赖**

Run: `pip install httpx apscheduler`

- [ ] **Step 4: 启动服务验证后端 API**

Run: `python app.py --port 5000 &`

验证以下端点：
- `curl http://localhost:5000/api/health` — 应返回健康状态
- `curl http://localhost:5000/api/proxy/status` — 应返回代理状态
- `curl -X POST http://localhost:5000/api/proxy/toggle` — 应启用代理
- `curl http://localhost:5000/api/providers` — 应返回供应商列表

验证后停止服务。

- [ ] **Step 5: Commit**

```bash
git add app.py requirements.txt
git commit -m "feat: wire up health and proxy blueprints with APScheduler"
```

---

### Task 6: 前端 Tab 扩展

**Files:**
- Modify: `templates/index.html`

这是最大的一个 Task。需要：
1. 添加 Tab 导航 CSS
2. 添加 Tab 切换 JS
3. 添加代理服务 Tab 内容
4. 添加健康监控 Tab 内容
5. 供应商卡片新增健康状态灯

- [ ] **Step 1: 在 `<style>` 中添加 Tab 导航和新增组件样式**

在现有 CSS 末尾、`</style>` 前添加：

```css
/* Tab 导航 */
.tab-nav {
  display: flex;
  gap: 4px;
  margin-bottom: 20px;
  border-bottom: 2px solid var(--border);
  padding-bottom: 0;
}

.tab-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 0.9rem;
  font-weight: 500;
  padding: 10px 20px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: all 0.2s;
}

.tab-btn:hover { color: var(--text-primary); }
.tab-btn.active { color: var(--text-primary); border-bottom-color: var(--success); }

.tab-panel { display: none; }
.tab-panel.active { display: block; }

/* 健康状态灯 */
.health-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.health-dot.healthy { background: var(--success); }
.health-dot.degraded { background: var(--warning); }
.health-dot.unhealthy { background: var(--danger); }
.health-dot.unknown { background: var(--border); }

/* 代理面板 */
.proxy-panel { margin-bottom: 24px; }

.proxy-toggle {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.toggle-switch {
  position: relative;
  width: 48px;
  height: 26px;
  background: var(--border);
  border-radius: 13px;
  cursor: pointer;
  transition: background 0.3s;
}

.toggle-switch.on { background: var(--success); }

.toggle-switch::after {
  content: '';
  position: absolute;
  width: 22px;
  height: 22px;
  background: #fff;
  border-radius: 50%;
  top: 2px;
  left: 2px;
  transition: transform 0.3s;
}

.toggle-switch.on::after { transform: translateX(22px); }

.proxy-info {
  background: var(--bg-card);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 16px;
}

.proxy-tip {
  background: rgba(46, 204, 113, 0.1);
  border: 1px solid var(--success);
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 16px;
  font-size: 0.85rem;
  color: var(--success);
  display: none;
}

.proxy-tip.show { display: block; }

.proxy-tip code {
  background: var(--bg-card);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}

/* 故障转移日志 */
.log-list { max-height: 300px; overflow-y: auto; }

.log-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--bg-card);
  border-radius: 6px;
  margin-bottom: 4px;
  font-size: 0.82rem;
}

.log-time { color: var(--text-secondary); flex-shrink: 0; }
.log-arrow { color: var(--warning); }
.log-reason { color: var(--danger); margin-left: auto; }

/* 健康监控卡片 */
.health-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px; }

.health-card {
  background: var(--bg-card);
  border-radius: 10px;
  padding: 16px;
}

.health-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.health-card-name { font-weight: 600; font-size: 0.95rem; }
.health-card-latency { font-size: 0.82rem; color: var(--text-secondary); }

.health-models {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.health-model-tag {
  background: var(--bg-primary);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.72rem;
  color: var(--text-secondary);
}

.btn-check {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border);
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 0.82rem;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-check:hover { opacity: 0.85; }

/* 代理配置 */
.config-panel {
  background: var(--bg-card);
  border-radius: 10px;
  padding: 16px;
}

.config-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.config-row label {
  font-size: 0.82rem;
  color: var(--text-secondary);
  min-width: 120px;
}

.config-row input {
  width: 80px;
  padding: 6px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 0.85rem;
  outline: none;
}

.config-row input:focus { border-color: var(--success); }

.btn-save-config {
  background: var(--success);
  color: #fff;
  border: none;
  padding: 6px 16px;
  border-radius: 8px;
  font-size: 0.85rem;
  cursor: pointer;
}

/* 供应商卡片上的优先级和健康灯 */
.provider-priority {
  position: absolute;
  top: 12px;
  left: 12px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-size: 0.7rem;
  padding: 1px 6px;
  border-radius: 8px;
}

.provider-health-dot {
  position: absolute;
  top: 12px;
  right: 12px;
}

.provider-card.active .provider-health-dot { right: 60px; }

@media (max-width: 600px) {
  .health-grid { grid-template-columns: 1fr; }
}
```

- [ ] **Step 2: 修改 HTML body — 添加 Tab 导航，将现有内容包裹进第一个 Tab**

将 `<div class="container">` 内部替换为 Tab 结构。保留原有 Modal、Toast、Loading 不变，只改 container 内容：

```html
<div class="container">
  <h1><span class="dot" id="statusDot"></span>CC Switch Lite</h1>
  <p class="subtitle">Claude Code 供应商管理、代理转发与健康监控</p>

  <nav class="tab-nav">
    <button class="tab-btn active" onclick="switchTab('providers')">供应商管理</button>
    <button class="tab-btn" onclick="switchTab('proxy')">代理服务</button>
    <button class="tab-btn" onclick="switchTab('health')">健康监控</button>
  </nav>

  <div id="tab-providers" class="tab-panel active">
    <div class="section-header">
      <div class="section-title">供应商</div>
      <button class="btn-add" onclick="openAddModal()">+ 添加供应商</button>
    </div>
    <div class="provider-grid" id="providerGrid"></div>
    <div class="section-title">当前配置</div>
    <div class="info-grid" id="infoGrid"></div>
    <div class="section-title">切换历史</div>
    <div class="history-list" id="historyList"></div>
  </div>

  <div id="tab-proxy" class="tab-panel">
    <div class="proxy-panel">
      <div class="proxy-toggle">
        <div class="toggle-switch" id="proxyToggle" onclick="toggleProxy()"></div>
        <span id="proxyStatusLabel">代理服务已关闭</span>
      </div>
      <div class="proxy-tip" id="proxyTip">
        请将 Claude Code 的 <code>ANTHROPIC_BASE_URL</code> 设为 <code>http://localhost:5000/proxy</code>
      </div>
      <div class="proxy-info" id="proxyInfo"></div>
      <div class="section-title">故障转移日志</div>
      <div class="log-list" id="failoverLog"></div>
    </div>
    <div class="section-title">代理配置</div>
    <div class="config-panel">
      <div class="config-row">
        <label>请求超时（秒）</label>
        <input type="number" id="cfgTimeout" value="30" min="5" max="120">
      </div>
      <div class="config-row">
        <label>最大尝试供应商</label>
        <input type="number" id="cfgMaxProviders" value="3" min="1" max="10">
      </div>
      <div class="config-row">
        <label>熔断阈值（次）</label>
        <input type="number" id="cfgCircuit" value="3" min="1" max="10">
      </div>
      <div class="config-row">
        <label></label>
        <button class="btn-save-config" onclick="saveProxyConfig()">保存配置</button>
      </div>
    </div>
  </div>

  <div id="tab-health" class="tab-panel">
    <div class="section-header">
      <div class="section-title">供应商健康状态</div>
      <button class="btn-check" onclick="checkAllHealth()">全部检测</button>
    </div>
    <div class="health-grid" id="healthGrid"></div>
  </div>
</div>
```

Modal、Toast、Loading 的 HTML 保持不变。

- [ ] **Step 3: 在 `<script>` 中添加 Tab 切换、代理面板、健康面板 JS**

在现有 `refresh()` 函数之后、`document.addEventListener` 之前，添加以下代码：

```javascript
// ---- Tab ----

function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach((b, i) => {
    b.classList.toggle('active', ['providers','proxy','health'][i] === name);
  });
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  $('tab-' + name).classList.add('active');
  if (name === 'proxy') loadProxyPanel();
  if (name === 'health') loadHealthPanel();
}

// ---- Proxy ----

let proxyStatus = null;

async function loadProxyPanel() {
  try {
    const res = await api('proxy/status');
    proxyStatus = res;
    const toggle = $('proxyToggle');
    toggle.classList.toggle('on', res.enabled);
    $('proxyStatusLabel').textContent = res.enabled ? '代理服务已启用' : '代理服务已关闭';
    $('proxyTip').classList.toggle('show', res.enabled);

    const current = res.current_provider || {};
    $('proxyInfo').innerHTML = `
      <div class="info-label">当前活跃供应商</div>
      <div class="info-value" style="color:${current.color || '#fff'}">${escapeHtml(current.label || '无')}</div>
      <div style="margin-top:8px">
        ${Object.entries(res.circuit_state || {}).map(([n, s]) =>
          `<span class="health-dot ${s.status}"></span> ${escapeHtml(n)}`
        ).join('&nbsp;&nbsp;')}
      </div>
    `;

    $('failoverLog').innerHTML = (res.failover_log || []).length
      ? res.failover_log.map(l => `
        <div class="log-item">
          <span class="log-time">${escapeHtml(l.timestamp || '')}</span>
          <span>${escapeHtml(l.from_provider || '')}</span>
          <span class="log-arrow">→</span>
          <span>${escapeHtml(l.to_provider || '')}</span>
          <span class="log-reason">${escapeHtml(l.reason || '')}</span>
        </div>
      `).join('')
      : '<div class="info-item" style="color:var(--text-secondary)">暂无故障转移记录</div>';

    const cfg = await (await fetch('/api/proxy/config')).json();
    $('cfgTimeout').value = cfg.timeout || 30;
    $('cfgMaxProviders').value = cfg.max_providers || 3;
    $('cfgCircuit').value = cfg.circuit_threshold || 3;
  } catch (e) {
    showToast('加载代理状态失败: ' + e.message, 'error');
  }
}

async function toggleProxy() {
  const newState = proxyStatus ? !proxyStatus.enabled : true;
  try {
    const res = await api('proxy/toggle', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ enabled: newState }),
    });
    if (res.success) {
      showToast(res.message);
      await loadProxyPanel();
    }
  } catch (e) {
    showToast('切换代理失败: ' + e.message, 'error');
  }
}

async function saveProxyConfig() {
  try {
    const res = await api('proxy/config', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        timeout: parseInt($('cfgTimeout').value),
        max_providers: parseInt($('cfgMaxProviders').value),
        circuit_threshold: parseInt($('cfgCircuit').value),
      }),
    });
    if (res.success) showToast(res.message);
  } catch (e) {
    showToast('保存配置失败: ' + e.message, 'error');
  }
}

// ---- Health ----

let healthStatus = {};
let healthPollTimer = null;

async function loadHealthPanel() {
  try {
    const res = await fetch('/api/health');
    healthStatus = await res.json();
    renderHealthCards();
    if (!healthPollTimer) {
      healthPollTimer = setInterval(loadHealthPanel, 60000);
    }
  } catch (e) {
    showToast('加载健康状态失败: ' + e.message, 'error');
  }
}

function renderHealthCards() {
  const providersRes = providersRes_cache;
  if (!providersRes) return;

  $('healthGrid').innerHTML = Object.entries(healthStatus).map(([name, info]) => {
    const p = (providersRes.providers || []).find(x => x.id === name);
    return `
    <div class="health-card">
      <div class="health-card-header">
        <span class="health-dot ${info.status}"></span>
        <span class="health-card-name">${escapeHtml(p ? p.label : name)}</span>
        <span class="health-card-latency">${info.latency_ms != null ? info.latency_ms + 'ms' : '-'}</span>
        <button class="btn-check" onclick="checkSingleHealth('${escapeHtml(name)}')">检测</button>
      </div>
      ${(info.models || []).length ? `
        <div class="health-models">
          ${info.models.map(m => `<span class="health-model-tag">${escapeHtml(m)}</span>`).join('')}
        </div>
      ` : ''}
    </div>`;
  }).join('');
}

async function checkSingleHealth(name) {
  try {
    await fetch(`/api/health/check/${name}`, { method: 'POST' });
    await loadHealthPanel();
  } catch (e) {
    showToast('检测失败: ' + e.message, 'error');
  }
}

async function checkAllHealth() {
  try {
    await fetch('/api/health/check/all', { method: 'POST' }).catch(() => {});
    await loadHealthPanel();
  } catch (e) {
    showToast('检测失败: ' + e.message, 'error');
  }
}
```

- [ ] **Step 4: 修改 `refresh()` 函数，缓存 providers 数据供健康面板使用，并在供应商卡片上显示健康状态灯**

在 `<script>` 顶部变量声明区域添加：

```javascript
let providersRes_cache = null;
```

修改 `renderProviders` 函数，在卡片 HTML 中添加优先级和健康灯：

```javascript
function renderProviders(providers, currentId) {
  $('providerGrid').innerHTML = providers.map(p => {
    const h = healthStatus[p.id];
    const healthClass = h ? h.status : 'unknown';
    return `
    <div class="provider-card ${p.id === currentId ? 'active' : ''}" onclick="doSwitch('${escapeHtml(p.id)}')">
      <span class="provider-priority">P${escapeHtml(String(p.priority || 99))}</span>
      <span class="provider-health-dot health-dot ${healthClass}"></span>
      <div class="card-actions">
        <button class="btn-card-edit" onclick="event.stopPropagation();openEditModal('${escapeHtml(p.id)}')" title="编辑">&#9998;</button>
        <button class="btn-card-delete" onclick="event.stopPropagation();doDelete('${escapeHtml(p.id)}')" title="删除">&#10005;</button>
      </div>
      <div class="provider-icon" style="background:${escapeHtml(p.color)}">${escapeHtml(p.icon)}</div>
      <div class="provider-name">${escapeHtml(p.label)}</div>
      <div class="provider-url">${escapeHtml(p.base_url)}</div>
      <div class="model-tags">
        <div class="model-tag">H: <span>${escapeHtml(p.models.haiku)}</span></div>
        <div class="model-tag">O: <span>${escapeHtml(p.models.opus)}</span></div>
        <div class="model-tag">S: <span>${escapeHtml(p.models.sonnet)}</span></div>
      </div>
    </div>`;
  }).join('');
}
```

修改 `refresh()` 函数，添加缓存和健康数据并行加载：

```javascript
async function refresh() {
  try {
    const [providersRes, statusRes, historyRes] = await Promise.all([
      api('providers'),
      api('status'),
      api('history'),
    ]);
    providersRes_cache = providersRes;
    currentId = providersRes.current_id;
    $('statusDot').style.background = statusRes.current.color;
    renderProviders(providersRes.providers, currentId);
    renderSettings(statusRes.settings);
    renderHistory(historyRes.history);

    // 后台加载健康状态（不阻塞渲染）
    fetch('/api/health').then(r => r.json()).then(d => {
      healthStatus = d;
      renderProviders(providersRes.providers, currentId);
    }).catch(() => {});
  } catch (e) {
    showToast('加载失败: ' + e.message, 'error');
  }
}
```

- [ ] **Step 5: 在 `get_provider_detail` API 响应中包含新字段**

在 `provider_manager.py` 中修改 `get_provider_detail` 函数，使其也返回 priority/auth_type 等字段：

```python
def get_provider_detail(name: str) -> dict | None:
    meta = _load_meta()
    if name not in meta:
        return None
    env = _load_provider_env(name)
    result = _provider_summary(name, meta[name])
    result["env"] = {k: env.get(k, "") for k in SWITCHABLE_ENV_KEYS}
    result["priority"] = meta[name].get("priority", 99)
    result["auth_type"] = meta[name].get("auth_type", "x-api-key")
    result["health_check_path"] = meta[name].get("health_check_path", "/v1/models")
    result["health_check_fallback"] = meta[name].get("health_check_fallback", True)
    return result
```

同样修改 `get_all_providers` 函数，在 `entry` 中包含 `priority`：

在 `get_all_providers` 函数的 `entry` 构建后添加：

```python
    entry["priority"] = m.get("priority", 99)
```

- [ ] **Step 6: 更新 Modal 表单，添加新字段的输入框**

在 Modal 的 `</div>` (icon form-group) 之后、`<hr class="form-divider">` 之前添加：

```html
      <div class="form-row">
        <div class="form-group">
          <label>代理优先级（数字越小越优先）</label>
          <input type="number" id="fPriority" value="99" min="0" max="99">
        </div>
        <div class="form-group">
          <label>认证方式</label>
          <select id="fAuthType">
            <option value="x-api-key">x-api-key（Anthropic 兼容）</option>
            <option value="bearer">Bearer Token（OpenAI 兼容）</option>
          </select>
        </div>
      </div>
```

在 `openAddModal()` 中添加重置：

```javascript
$('fPriority').value = '99';
$('fAuthType').value = 'x-api-key';
```

在 `openEditModal()` 中添加回显（在 `$('fSonnet').value` 之后）：

```javascript
$('fPriority').value = p.priority || 99;
$('fAuthType').value = p.auth_type || 'x-api-key';
```

在 `submitForm()` 中添加提交字段（在 `env` 对象之后）：

```javascript
  const priority = parseInt($('fPriority').value) || 99;
  const auth_type = $('fAuthType').value;
```

并修改 POST/PUT body，添加 `priority` 和 `auth_type`：

```javascript
    if (editingId) {
      res = await api(`providers/${editingId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label, color, icon, env, priority, auth_type }),
      });
    } else {
      res = await api('providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, label, color, icon, env, priority, auth_type }),
      });
    }
```

- [ ] **Step 7: 启动服务，浏览器验证全部功能**

Run: `python app.py --port 5000 &`

验证清单：
1. 供应商管理 Tab — 卡片显示优先级标签和健康灯
2. 添加供应商 Modal — 新增优先级和认证方式字段
3. 代理服务 Tab — toggle 开关、配置面板
4. 健康监控 Tab — 健康卡片、检测按钮
5. Tab 切换流畅无闪烁

- [ ] **Step 8: Commit**

```bash
git add templates/index.html provider_manager.py
git commit -m "feat: add tab UI for proxy, health monitoring, and provider priority display"
```

---

### Task 7: 集成测试 + 最终提交

**Files:**
- 所有已修改文件

- [ ] **Step 1: 端到端验证**

启动服务：`python app.py --port 5000`

测试流程：
1. 打开 UI，确认三个 Tab 都能正常切换
2. 在健康监控 Tab 点击"全部检测"，确认供应商状态灯变化
3. 在代理服务 Tab 打开代理开关，确认提示信息显示
4. 手动将 Claude Code BASE_URL 设为 `http://localhost:5000/proxy`，发送一个测试请求，确认代理转发正常
5. 在供应商管理 Tab 添加一个新供应商（配置一个不存在的 URL），确认添加成功
6. 在健康监控确认新供应商显示为不健康
7. 删除测试供应商

- [ ] **Step 2: 停止服务，最终 Commit**

```bash
git add -A
git commit -m "feat: CC Switch Lite Phase 1 complete - proxy failover + health monitoring"
```
