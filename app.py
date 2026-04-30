"""Claude Code 模型供应商切换 Web UI — CC Switch Lite"""

import argparse
import signal
import sys
import traceback

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


def _handle_exception(exc_type, exc_value, exc_tb):
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print(f"[FATAL] Uncaught exception:\n{msg}", file=sys.stderr, flush=True)


sys.excepthook = _handle_exception


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return "", 204


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

    print(f"启动 CC Switch Lite: http://{args.host}:{args.port}", flush=True)

    if args.debug:
        app.run(host=args.host, port=args.port, debug=True, threaded=True)
    else:
        import waitress
        waitress.serve(app, host=args.host, port=args.port, threads=8)
