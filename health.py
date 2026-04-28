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
