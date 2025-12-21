#!/bin/bash
# ProWaveDAQ 智慧啟動腳本
#
# 使用方式：
#   ./run.sh                  # 預設：Port 8080，開啟日誌存檔
#   ./run.sh 3000             # 指定 Port 3000，開啟日誌存檔
#   ./run.sh 8080 nolog       # 指定 Port 8080，不存檔

# ================= 設定區 =================
LOG_DIR="logs"
RETENTION_DAYS=3  # 日誌保留天數，超過自動刪除
# =========================================

# 1. 設定 USB Latency
if [ -e /sys/bus/usb-serial/devices/ttyUSB0/latency_timer ]; then
    sudo bash -c "echo 1 > /sys/bus/usb-serial/devices/ttyUSB0/latency_timer"
else
    # 這裡只顯示警告但不中止，方便在沒有設備的環境測試
    echo "警告: 未偵測到 ttyUSB0，略過 Latency 設定。"
fi

# 2. 參數處理
PORT=${1:-8080}
MODE=${2:-log}  # 第二個參數預設為 log，輸入 "nolog" 則不存檔

# 驗證 Port
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "錯誤：無效的埠號 '$PORT'"
    exit 1
fi

# 3. 準備環境
source venv/bin/activate
clear

echo "============================================================"
echo "ProWaveDAQ System Launcher"
echo "============================================================"
echo "Web Interface : http://0.0.0.0:${PORT}/"

# 4. 執行邏輯判斷
if [ "$MODE" == "nolog" ]; then
    # --- 模式 A: 不存日誌 (適合超長期掛機，怕硬碟滿) ---
    echo "Log Mode      : DISABLED (僅顯示於螢幕)"
    echo "============================================================"
    echo "警告：此模式下若發生錯誤，將無法回溯查修。"
    echo ""
    python src/main.py --port ${PORT}

else
    # --- 模式 B: 存日誌 (預設，適合除錯與一般使用) ---
    mkdir -p ${LOG_DIR}
    
    # 自動清理舊日誌 (刪除修改時間超過 30 天的 .log 檔案)
    find ${LOG_DIR} -name "*.log" -mtime +${RETENTION_DAYS} -delete
    
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    LOG_FILE="${LOG_DIR}/app_${TIMESTAMP}.log"
    
    echo "Log Mode      : ENABLED"
    echo "Log File      : ${LOG_FILE}"
    echo "Retention     : 保留最近 ${RETENTION_DAYS} 天的日誌"
    echo "============================================================"
    echo ""
    
    # 使用 tee 同時輸出到螢幕與檔案
    python src/main.py --port ${PORT} 2>&1 | tee ${LOG_FILE}
fi