#!/usr/bin/env bash
# Chạy tool trên macOS / Linux (tự tạo môi trường ảo và cài thư viện nếu cần)
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "==> Đang tạo môi trường ảo .venv ..."
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
fi

# Luôn đồng bộ dependency để các thư viện mới trong requirements.txt
# được cài ngay cả khi .venv đã tồn tại từ lần chạy trước.
./.venv/bin/python -m pip install -r requirements.txt

if [ "$(uname -s)" = "Darwin" ] && command -v caffeinate >/dev/null 2>&1; then
  # Giữ máy thức trong toàn bộ lượt chạy để Chrome/ADB không mất phiên khi chờ OTP hoặc QR.
  exec caffeinate -i ./.venv/bin/python regtiktok_multithread.py "$@"
fi

exec ./.venv/bin/python regtiktok_multithread.py "$@"
