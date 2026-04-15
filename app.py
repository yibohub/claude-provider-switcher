"""Claude Code 模型供应商切换 Web UI"""

import argparse

from flask import Flask, jsonify, render_template, request

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

app = Flask(__name__)


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
    parser = argparse.ArgumentParser(description="Claude Code Provider Switcher")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=5000, help="监听端口")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    print(f"启动 Claude Code 供应商切换工具: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
