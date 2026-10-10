#!/usr/bin/env bash
# Chạy tool trên macOS / Linux (tự tạo môi trường ảo và cài thư viện nếu cần)
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "==> Đang tạo môi trường ảo .venv ..."
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/python -m pip install -r requirements.txt
fi

exec ./.venv/bin/python regtiktok_multithread.py
