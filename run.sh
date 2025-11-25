#!/bin/bash
# ProWaveDAQ 啟動腳本
# 使用方式：
#   ./run.sh              # 使用預設 port 8080
#   ./run.sh 3000         # 使用自訂 port 3000

sudo bash -c "echo 1 > /sys/bus/usb-serial/devices/ttyUSB0/latency_timer"

# 取得 port 參數（如果提供）
PORT=${1:-8080}

# 驗證 port 是否為有效數字
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "錯誤：無效的埠號 '$PORT'，請使用 1-65535 之間的數字"
    echo "使用方式："
    echo "  ./run.sh              # 使用預設 port 8080"
    echo "  ./run.sh 3000         # 使用自訂 port 3000"
    exit 1
fi

clear && echo "Starting ProWaveDAQ Real-time Data Visualization System..." && echo "Press Ctrl+C to stop the server" && echo "Web interface will be available at http://0.0.0.0:${PORT}/" && echo "================================================" && echo ""
source venv/bin/activate
python src/main.py --port ${PORT}