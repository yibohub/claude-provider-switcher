#!/bin/bash
cd "$(dirname "$0")"
while true; do
    if ! lsof -ti:5000 > /dev/null 2>&1; then
        echo "[$(date)] Server not running, restarting..." >> /tmp/cc-switch.log
        nohup python3 app.py --host 0.0.0.0 --port 5000 >> /tmp/cc-switch.log 2>&1 &
        echo "[$(date)] Started PID $!" >> /tmp/cc-switch.log
    fi
    sleep 5
done
