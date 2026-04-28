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


def _log_failover(from_provider: str, to_provider: str, reason: str, status_code: int | None, latency_ms: int | None):
    with _lock:
        _failover_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "from_provider": from_provider,
            "to_provider": to_provider,
            "reason": reason,
            "status_code": status_code,
            "latency_ms": latency_ms,
        })


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

    prev_provider = None
    for name, meta_entry in available:
        env = _load_provider_env(name)
        base_url = env.get("ANTHROPIC_BASE_URL", "").rstrip("/")
        token = env.get("ANTHROPIC_AUTH_TOKEN", "")
        auth_type = meta_entry.get("auth_type", "x-api-key")
        target_url = f"{base_url}/{path}"
        headers = _get_auth_headers(token, auth_type)

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
                        if prev_provider is not None:
                            _log_failover(prev_provider, name, f"HTTP {resp.status_code}", resp.status_code, None)
                        prev_provider = name
                        continue

                    _record_success(name)
                    if prev_provider is not None:
                        _log_failover(prev_provider, name, "recovery", None, None)

                    def generate():
                        for chunk in resp.iter_bytes():
                            yield chunk

                    excluded = {"transfer-encoding", "content-encoding", "connection"}
                    resp_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]
                    return Response(generate(), status=resp.status_code, headers=resp_headers)

        except httpx.TimeoutException:
            _record_failure(name, None)
            if prev_provider is not None:
                _log_failover(prev_provider, name, "超时", None, None)
            prev_provider = name
            continue
        except httpx.ConnectError:
            _record_failure(name, None)
            if prev_provider is not None:
                _log_failover(prev_provider, name, "连接失败", None, None)
            prev_provider = name
            continue
        except Exception as e:
            _record_failure(name, None)
            print(f"[proxy] {name} 转发异常: {e}")
            if prev_provider is not None:
                _log_failover(prev_provider, name, str(e), None, None)
            prev_provider = name
            continue

    print(f"[proxy] 所有供应商请求均失败, providers={available}")
    return jsonify({"error": "所有供应商请求均失败"}), 503


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


@proxy_bp.route("/api/proxy/config", methods=["GET", "PUT"])
def api_proxy_config():
    if request.method == "GET":
        return jsonify(_load_proxy_config())

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
