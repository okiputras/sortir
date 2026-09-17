#!/bin/bash
# Dijalankan launchd. Semua yang disentuh ada di ~/Library/Application Support/sortir
# -- BUKAN di ~/Documents, karena macOS melarang proses launchd membaca folder itu
# (python kena "Operation not permitted" walaupun bash-nya bisa cd ke sana).
SUP="$HOME/Library/Application Support/sortir"
LOG="$HOME/Library/Logs/kasirpintar-sortir.log"
cd "$SUP" || exit 1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"

if [ "$1" = "keepalive" ]; then
  /usr/bin/python3 kasirpintar_session.py cek >> "$LOG" 2>&1
  exit 0
fi

STAMP=$(date +%Y-%m-%d)
TARGET="data/DATA_BARANG_${STAMP}.xls"
[ -f "$TARGET" ] && { echo "sudah ada $TARGET, dilewati" >> "$LOG"; exit 0; }
/usr/bin/python3 kasirpintar_session.py barang "$TARGET" >> "$LOG" 2>&1
