"""
TikTok Account Registration Tool
--------------------------------
Tool tự động đăng ký tài khoản TikTok sử dụng Selenium và hỗ trợ đa luồng
Phát triển bởi Hồ Hiệp x HVHTOOL
Phiên bản cải tiến: 2.19 - 
"""

import os
import re
import sys
import json
import time
import base64
import shutil
import random
import socket
import queue
import tempfile
import threading
import logging
import socketserver
import subprocess
import hashlib
import hmac
import struct
import html
import argparse
from datetime import datetime
from urllib.parse import parse_qs, quote, unquote, urlparse
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict # Import Optional để dùng Type Hinting

import requests
import cv2
import numpy as np
import zxingcpp
import msal
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    ElementClickInterceptedException,
    StaleElementReferenceException
)

# Thiết lập logging
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Tạo file handler với encoding utf-8
file_handler = logging.FileHandler(os.path.join(log_dir, "regtiktok.log"), encoding='utf-8')

# Tạo console handler
import codecs
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)
console_handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
    handlers=[
        file_handler,
        console_handler
    ]
)

logger = logging.getLogger(__name__)

# ===== Tìm đường dẫn Chrome theo hệ điều hành (Windows / macOS / Linux) =====
def find_chrome_binary() -> Optional[str]:
    """Tìm Chrome khả dụng: ưu tiên Chrome portable trong thư mục tool, sau đó Chrome cài trong hệ thống."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = []

    if sys.platform.startswith('win'):
        candidates += [
            os.path.join(script_dir, 'chrome-win64', 'chrome.exe'),   # Chrome portable đi kèm tool
            os.path.join(script_dir, 'chrome', 'chrome.exe'),
            os.path.join(os.environ.get('PROGRAMFILES', r'C:\Program Files'),
                         'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)'),
                         'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        ]
    elif sys.platform == 'darwin':
        candidates += [
            os.path.join(script_dir, 'chrome-mac', 'Google Chrome.app', 'Contents', 'MacOS', 'Google Chrome'),
            os.path.join(script_dir, 'chrome-mac-arm64', 'Google Chrome.app', 'Contents', 'MacOS', 'Google Chrome'),
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            os.path.expanduser('~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
            '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
            '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        ]
    else:
        candidates += [
            shutil.which('google-chrome'),
            shutil.which('google-chrome-stable'),
            shutil.which('chromium'),
            shutil.which('chromium-browser'),
        ]

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None

chrome_path = find_chrome_binary()

# Khóa để bảo vệ truy cập vào tài nguyên chia sẻ
proxy_lock = threading.Lock()
file_lock = threading.Lock()
confirmation_lock = threading.Lock()

# Thêm thông số cấu hình toàn cục (quay về mặc định của 2.15 hoặc phù hợp với yêu cầu)
CONFIG = {
    'CAPTCHA_WAIT_TIME': 600,  # Thời gian chờ khi gặp captcha (giây)
    'PROXY_TIMEOUT': 10,        # Thời gian chờ kết nối proxy (giây)
    'MIN_DELAY': 1.5,           # Độ trễ ngẫu nhiên tối thiểu (giây)
    'MAX_DELAY': 7.0,             # Độ trễ ngẫu nhiên tối đa (giây)
    'ELEMENT_WAIT_TIMEOUT': 20, # Thời gian chờ tối đa cho các phần tử xuất hiện/click được (giây)
    'PAGE_LOAD_TIMEOUT': 45,    # Thời gian tối đa để tải trang (giây)
    'QR_WAIT_TIME': 180,        # Chờ người dùng hoàn tất checkpoint QR trong ứng dụng TikTok
    'ADB_QR_WAIT_TIME': 180,    # Thời gian đợi người dùng xác nhận QR trên điện thoại
    'QR_SKIP_DISCOVERY_TIME': 5, # Cho nút Skip render trước khi kết luận QR là bắt buộc
    'ADB_DEVICE': '',           # Để trống để tự chọn thiết bị ADB TCP đang online
    'OPEN_QR_ON_ANDROID': True, # Tự mở payload QR trên điện thoại qua ADB
    'EMAIL_OTP_WAIT_TIME': 300, # Tổng thời gian chờ OTP email từ TikTok
    'EMAIL_OTP_RESEND_AFTER': 120, # Gửi lại OTP một lần nếu email đến chậm
    'OPEN_DECODED_QR_URL': True, # Mở URL giải mã từ QR trong tab phụ, giữ nguyên tab đăng ký
    # User-Agent cũ/không khớp phiên bản Chrome làm tăng khả năng bị kiểm tra QR.
    # Mặc định dùng UA thật của Chrome; chỉ bật khi danh sách UA được duy trì mới.
    'USE_CUSTOM_USER_AGENT': False,
    'BROWSER_WIDTH': 400,       # Chiều rộng cửa sổ trình duyệt (pixels)
    'BROWSER_HEIGHT': 800,      # Chiều cao cửa sổ trình duyệt (pixels)
    # 'CLEANUP_PLUGINS': True,  # Loại bỏ do không dùng proxy có xác thực
}

# Các đường dẫn file
DATA_DIR = 'data'
PROXY_FILE = os.path.join(DATA_DIR, 'proxy.txt')
DOMAIN_NAMES_FILE = os.path.join(DATA_DIR, 'domain_names.txt')
PASSWORDS_FILE = os.path.join(DATA_DIR, 'passwords.txt')
USER_AGENTS_FILE = os.path.join(DATA_DIR, 'useragents-desktop.txt')
OUTLOOK_ACCOUNTS_FILE = os.path.join(DATA_DIR, 'outlook_accounts.txt')
OUTLOOK_TOKEN_DIR = os.path.join(DATA_DIR, '.outlook_tokens')
ACCOUNTS_FILE = 'accounts.txt' # File accounts.txt nằm cùng cấp với file chính

outlook_lock = threading.Lock()
outlook_accounts_queue = queue.Queue()


def load_outlook_accounts():
    """Đọc email Outlook có sẵn: email|Microsoft application client_id."""
    if not os.path.exists(OUTLOOK_ACCOUNTS_FILE):
        return []
    accounts = []
    with open(OUTLOOK_ACCOUNTS_FILE, 'r', encoding='utf-8') as file:
        for line_number, raw_line in enumerate(file, 1):
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            parts = [part.strip() for part in line.split('|')]
            if len(parts) != 2 or '@' not in parts[0] or not parts[1]:
                logger.warning(
                    f"Bỏ qua dòng Outlook {line_number}: cần email|client_id"
                )
                continue
            accounts.append((parts[0], parts[1]))
    return accounts
def _clean_account_field(value) -> str:
    """Giữ mỗi tài khoản trên đúng một dòng, phân tách an toàn bằng dấu |."""
    return str(value or '').replace('|', ' ').replace('\r', ' ').replace('\n', ' ').strip()


def format_account_record(username, tiktok_password, two_factor_secret) -> str:
    """Tạo dòng username|mật khẩu TikTok|secret 2FA đã xác minh."""
    secret = _clean_account_field(two_factor_secret).replace(' ', '').upper()
    if not re.fullmatch(r'[A-Z2-7]{16,}', secret):
        raise ValueError("Secret 2FA không hợp lệ hoặc chưa được thiết lập")
    fields = (username, tiktok_password, secret)
    return '|'.join(_clean_account_field(field) for field in fields)


def generate_totp(secret: str, timestamp: Optional[int] = None) -> str:
    """Tạo mã TOTP 6 số theo RFC 6238 từ secret Base32."""
    normalized = re.sub(r'\s+', '', secret or '').upper()
    if not re.fullmatch(r'[A-Z2-7]{16,}', normalized):
        raise ValueError("Secret TOTP không hợp lệ")
    padding = '=' * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(normalized + padding, casefold=True)
    counter = int(timestamp if timestamp is not None else time.time()) // 30
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"

# Hàm tạo độ trễ ngẫu nhiên
def random_delay():
    """Tạo độ trễ ngẫu nhiên trong khoảng MIN_DELAY và MAX_DELAY."""
    time.sleep(random.uniform(CONFIG['MIN_DELAY'], CONFIG['MAX_DELAY']))

# Tạo file chứa danh sách tên và mật khẩu nếu chưa tồn tại
def create_data_files():
    """Tạo các file dữ liệu cần thiết nếu chưa tồn tại"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    # Tạo file domain_names.txt
    if not os.path.exists(DOMAIN_NAMES_FILE):
        sample_domains = [
            'mailtest', 'emailgen', 'tempmail'
        ]
        with open(DOMAIN_NAMES_FILE, 'w', encoding='utf-8') as f:
            for name in sample_domains:
                f.write(f"{name}\n")
        logger.info(f"Đã tạo file {DOMAIN_NAMES_FILE} với các tên miền mẫu. Vui lòng cập nhật với tên miền của bạn.")

    # Tạo file passwords.txt
    if not os.path.exists(PASSWORDS_FILE):
        passw = [
            'explanation1', 'hypothesize1', 'combination1', 'personality1', 'calculation1',
            'destination1', 'exploration1', 'architecture1', 'university1', 'consequence1',
            'possibility1', 'organization1', 'considerable1', 'protectional1', 'environment1',
            'explanation2', 'hypothesize2', 'combination2', 'personality2', 'calculation2',
            'explanation3', 'hypothesize3', 'combination3', 'personality3', 'calculation3'
        ]
        with open(PASSWORDS_FILE, 'w', encoding='utf-8') as f:
            for pwd in passw:
                f.write(f"{pwd}\n")
        logger.info(f"Đã tạo file {PASSWORDS_FILE} với {len(passw)} mật khẩu")

    # Tạo file useragents-desktop.txt (nếu chưa tồn tại)
    if not os.path.exists(USER_AGENTS_FILE):
        default_user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/100.0.1185.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:98.0) Gecko/20100101 Firefox/98.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:98.0) Gecko/20100101 Firefox/98.0"
        ]
        with open(USER_AGENTS_FILE, 'w', encoding='utf-8') as f:
            for ua in default_user_agents:
                f.write(f"{ua}\n")
        logger.info(f"Đã tạo file {USER_AGENTS_FILE} với các User-Agent mặc định")

    # Tạo file proxy.txt nếu chưa tồn tại
    if not os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, 'w', encoding='utf-8') as f:
            f.write("# Vui lòng thêm danh sách proxy vào đây, mỗi dòng một proxy.\n")
            f.write("# Định dạng: ip:port hoặc ip:port:user:pass (hỗ trợ proxy có xác thực)\n")
        logger.info(f"Đã tạo file {PROXY_FILE}. Vui lòng thêm proxy vào file này.")

# Hàm đọc dữ liệu từ file
def read_data_file(filepath):
    """Đọc dữ liệu từ file và trả về danh sách các dòng"""
    if not os.path.exists(filepath):
        create_data_files() # Đảm bảo file được tạo nếu không tồn tại
        if not os.path.exists(filepath): # Kiểm tra lại sau khi cố gắng tạo
             logger.error(f"File dữ liệu {filepath} không tồn tại sau khi cố gắng tạo.")
             return []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except Exception as e:
        logger.error(f"Lỗi khi đọc file {filepath}: {str(e)}")
        return []

# Hàm lấy danh sách tên miền
def get_domain_names():
    """Trả về danh sách tên miền"""
    return read_data_file(DOMAIN_NAMES_FILE)

# Hàm lấy danh sách mật khẩu
def get_passwords():
    """Trả về danh sách mật khẩu"""
    return read_data_file(PASSWORDS_FILE)

# Hàm lấy User-Agent ngẫu nhiên
def get_random_user_agent() -> str:
    """Lấy một User-Agent ngẫu nhiên từ file useragents-desktop.txt"""
    user_agents = read_data_file(USER_AGENTS_FILE)
    if user_agents:
        return random.choice(user_agents)
    logger.warning(f"Không tìm thấy User-Agent nào trong file {USER_AGENTS_FILE}. Sử dụng User-Agent mặc định.")
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"


# Hàm đánh dấu proxy không hoạt động
def mark_proxy_as_failed(failed_proxy, reason="Unknown"):
    """Đánh dấu proxy không hoạt động trong file proxy.txt"""
    with proxy_lock:
        if os.path.exists(PROXY_FILE):
            try:
                with open(PROXY_FILE, 'r', encoding='utf-8') as file:
                    lines = file.readlines()

                with open(PROXY_FILE, 'w', encoding='utf-8') as file:
                    for line in lines:
                        if line.strip() == failed_proxy:
                            file.write(f"#FAILED [{datetime.now().strftime('%Y-%m-%d %H:%M')}] [{reason}]: {line}")
                            logger.info(f"Đã đánh dấu proxy không hoạt động: {proxy_display(failed_proxy)} - Lý do: {reason}")
                        else:
                            file.write(line)
            except Exception as e:
                logger.error(f"Lỗi khi cập nhật file proxy: {str(e)}")

# ===== Phân tích chuỗi proxy: hỗ trợ cả proxy KHÔNG xác thực và CÓ xác thực =====
def parse_proxy(proxy: str) -> Optional[Dict]:
    """Phân tích chuỗi proxy. Các định dạng được hỗ trợ:
        ip:port
        ip:port:user:pass        (dạng phổ biến của MikoProxy và nhiều nhà cung cấp VN)
        user:pass@ip:port
        http://user:pass@ip:port (kèm scheme http/https/socks4/socks5)
    Trả về dict thông tin proxy, hoặc None nếu chuỗi không hợp lệ."""
    if not proxy:
        return None

    raw = proxy.strip()
    if not raw or raw.startswith('#'):
        return None

    scheme = 'http'
    if '://' in raw:
        scheme, raw = raw.split('://', 1)
        scheme = (scheme or 'http').strip().lower()
        if scheme not in ('http', 'https', 'socks4', 'socks5'):
            scheme = 'http'

    username = None
    password = None
    if '@' in raw:
        creds, raw = raw.rsplit('@', 1)
        if ':' not in creds:
            return None
        username, password = creds.split(':', 1)

    parts = raw.split(':')
    if len(parts) == 2:        # ip:port
        host, port = parts
    elif len(parts) == 4:      # ip:port:user:pass
        host, port, username, password = parts
    elif len(parts) == 3:      # ip:port:user
        host, port, username = parts
    else:
        return None

    host = host.strip()
    port = port.strip()
    if not host or not port.isdigit():
        return None

    port_number = int(port)
    if not 0 < port_number < 65536:
        return None

    return {
        'scheme': scheme,
        'host': host,
        'port': port_number,
        'username': (username or '').strip() or None,
        'password': password if password else None,
    }


def proxy_display(proxy: str) -> str:
    """Hiển thị proxy đã che mật khẩu để ghi log an toàn."""
    info = parse_proxy(proxy)
    if not info:
        return proxy
    if info['username']:
        return f"{info['host']}:{info['port']}:{info['username']}:***"
    return f"{info['host']}:{info['port']}"


def build_proxy_url(info: Dict) -> str:
    """Tạo URL proxy (kèm xác thực nếu có) để dùng cho thư viện requests."""
    if info.get('username'):
        user = quote(info['username'], safe='')
        pwd = quote(info['password'] or '', safe='')
        return f"{info['scheme']}://{user}:{pwd}@{info['host']}:{info['port']}"
    return f"{info['scheme']}://{info['host']}:{info['port']}"


class LocalAuthProxyBridge:
    """Cầu nối proxy nội bộ cho proxy CÓ xác thực.

    Chrome không nhận user/pass proxy qua tham số dòng lệnh, và từ Chrome 137 trở đi
    cờ --load-extension cũng không còn nạp được extension. Vì vậy cách bền vững nhất là:
    Chrome -> proxy nội bộ 127.0.0.1 (không cần xác thực) -> proxy thật (có xác thực).
    Cầu nối tự thêm header Proxy-Authorization trước khi chuyển tiếp.
    """

    def __init__(self, upstream: Dict):
        self.upstream_host = upstream['host']
        self.upstream_port = upstream['port']
        self.username = upstream['username']
        self.password = upstream['password'] or ''
        self._auth_header = 'Basic ' + base64.b64encode(
            f"{self.username}:{self.password}".encode('utf-8')
        ).decode('ascii')
        self._server = None
        self.port = None

    def start(self) -> int:
        """Khởi động cầu nối trên một cổng trống của 127.0.0.1, trả về cổng đó."""
        bridge = self

        class _Handler(socketserver.BaseRequestHandler):
            def handle(self):
                bridge._handle_connection(self.request)

        class _Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._server = _Server(('127.0.0.1', 0), _Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self.port

    def stop(self):
        """Dừng cầu nối."""
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
            self.port = None

    @staticmethod
    def _relay(src, dst):
        """Bơm dữ liệu một chiều từ src sang dst."""
        try:
            while True:
                chunk = src.recv(65536)
                if not chunk:
                    break
                dst.sendall(chunk)
        except Exception:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except Exception:
                pass

    def _handle_connection(self, client):
        upstream = None
        try:
            client.settimeout(CONFIG['PROXY_TIMEOUT'])

            # Đọc phần header của request (CONNECT ... hoặc GET http://...)
            data = b''
            while b'\r\n\r\n' not in data:
                chunk = client.recv(65536)
                if not chunk:
                    return
                data += chunk
                if len(data) > 65536:
                    break

            head, _, body = data.partition(b'\r\n\r\n')
            lines = head.split(b'\r\n')
            request_line = lines[0]
            headers = [
                h for h in lines[1:]
                if h.strip() and not h.lower().startswith(b'proxy-authorization')
            ]
            headers.append(b'Proxy-Authorization: ' + self._auth_header.encode('ascii'))

            upstream = socket.create_connection(
                (self.upstream_host, self.upstream_port), timeout=CONFIG['PROXY_TIMEOUT']
            )
            upstream.settimeout(300)
            upstream.sendall(request_line + b'\r\n' + b'\r\n'.join(headers) + b'\r\n\r\n' + body)

            client.settimeout(300)
            threading.Thread(target=self._relay, args=(client, upstream), daemon=True).start()
            self._relay(upstream, client)

        except Exception as e:
            logger.debug(f"Cầu nối proxy lỗi: {str(e)}")
        finally:
            for sock in (upstream, client):
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass


# Hàm kiểm tra proxy có hoạt động không
def check_proxy(proxy):
    """Kiểm tra proxy có hoạt động không bằng cả socket và HTTP request (hỗ trợ proxy có/không xác thực)"""
    info = parse_proxy(proxy)
    if not info:
        logger.warning(f"Định dạng proxy không hợp lệ: {proxy_display(proxy)}. "
                       f"Hỗ trợ: ip:port, ip:port:user:pass, user:pass@ip:port")
        mark_proxy_as_failed(proxy, "Định dạng không hợp lệ")
        return False

    safe_proxy = proxy_display(proxy)
    ip = info['host']
    port = info['port']

    try:
        logger.debug(f"Kiểm tra kết nối socket tới {ip}:{port}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((ip, port))
        sock.close()

        if result != 0:
            logger.warning(f"Proxy {safe_proxy} không phản hồi qua socket")
            mark_proxy_as_failed(proxy, "Không phản hồi socket")
            return False

        logger.debug(f"Kiểm tra proxy {safe_proxy} bằng HTTP request")

        proxy_url = build_proxy_url(info)
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }

        try:
            response = requests.get(
                "https://www.tiktok.com/robots.txt",
                proxies=proxies,
                timeout=CONFIG['PROXY_TIMEOUT'],
                headers={
                    "User-Agent": get_random_user_agent() # Sử dụng User-Agent ngẫu nhiên cho việc kiểm tra
                }
            )

            if response.status_code in [200, 301, 302, 307, 308]:
                logger.info(f"Proxy {safe_proxy} hoạt động tốt, HTTP status: {response.status_code}")
                return True
            else:
                logger.warning(f"Proxy {safe_proxy} kết nối được nhưng HTTP status: {response.status_code}")
                mark_proxy_as_failed(proxy, f"HTTP status {response.status_code}")
                return False

        except requests.exceptions.ConnectTimeout:
            logger.warning(f"Proxy {safe_proxy} timeout khi kết nối HTTP")
            mark_proxy_as_failed(proxy, "HTTP connect timeout")
            return False
        except requests.exceptions.ProxyError as e:
            if '407' in str(e):
                logger.warning(f"Proxy {safe_proxy} bị từ chối xác thực (407 invalid credentials). "
                               f"Kiểm tra lại user/pass hoặc hạn dùng của proxy.")
                mark_proxy_as_failed(proxy, "Sai tài khoản/mật khẩu proxy (407)")
            else:
                logger.warning(f"Proxy {safe_proxy} lỗi kết nối: {str(e)[:120]}")
                mark_proxy_as_failed(proxy, "Proxy error")
            return False
        except requests.exceptions.SSLError:
            logger.warning(f"Proxy {safe_proxy} lỗi SSL")
            mark_proxy_as_failed(proxy, "SSL error")
            return False
        except Exception as e:
            logger.warning(f"Proxy {safe_proxy} lỗi HTTP request: {str(e)}")
            mark_proxy_as_failed(proxy, f"HTTP error: {str(e)[:50]}")
            return False

    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra proxy {safe_proxy}: {str(e)}")
        mark_proxy_as_failed(proxy, f"Exception: {str(e)[:50]}")
        return False

# Hàm đọc proxy từ file
def get_proxies():
    """Đọc danh sách proxy từ file và trả về danh sách các proxy hoạt động"""
    proxies = []

    if os.path.exists(PROXY_FILE):
        try:
            with open(PROXY_FILE, 'r', encoding='utf-8') as file:
                for line in file:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        proxies.append(line)

            if proxies:
                logger.info(f"Đã đọc được {len(proxies)} proxy từ file {PROXY_FILE}")
                return proxies
            else:
                logger.warning(f"Không tìm thấy proxy nào trong file {PROXY_FILE}")
                return []
        except Exception as e:
            logger.error(f"Lỗi khi đọc file proxy: {str(e)}")
            return []
    else:
        logger.warning(f"File proxy {PROXY_FILE} không tồn tại")
        return []

# Hàm ghi log proxy đã sử dụng
def log_proxy_usage(proxy, success=True, worker_id=None):
    """Ghi log proxy đã sử dụng"""
    with file_lock:
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        log_file = os.path.join(log_dir, 'proxy_log.txt')
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        status = "SUCCESS" if success else "FAILED"
        worker_info = f" | Worker: {worker_id}" if worker_id else ""

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{timestamp} | {status} | Proxy: {proxy_display(proxy)}{worker_info}\n")

# Hàm hiển thị thống kê proxy
def print_proxy_stats():
    """Hiển thị thống kê sử dụng proxy"""
    log_file = os.path.join('logs', 'proxy_log.txt')
    if not os.path.exists(log_file):
        logger.info("Chưa có thống kê proxy")
        return

    success_count = 0
    failed_count = 0
    proxy_stats = {}

    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                if '|' in line:
                    parts = line.strip().split(' | ')
                    if len(parts) >= 3:
                        status = parts[1]
                        proxy_info = parts[2].replace('Proxy: ', '')

                        if proxy_info not in proxy_stats:
                            proxy_stats[proxy_info] = {'success': 0, 'failed': 0}

                        if status == 'SUCCESS':
                            proxy_stats[proxy_info]['success'] += 1
                            success_count += 1
                        elif status == 'FAILED':
                            proxy_stats[proxy_info]['failed'] += 1
                            failed_count += 1

        logger.info("\n===== PROXY STATS =====")
        logger.info(f"Tổng số lần sử dụng proxy thành công: {success_count}")
        logger.info(f"Tổng số lần sử dụng proxy thất bại: {failed_count}")
        logger.info("\nThống kê chi tiết:")

        for proxy, stats in proxy_stats.items():
            total = stats['success'] + stats['failed']
            success_rate = (stats['success'] / total) * 100 if total > 0 else 0
            logger.info(f"Proxy: {proxy} - Thành công: {stats['success']}, Thất bại: {stats['failed']}, Tỉ lệ thành công: {success_rate:.2f}%")

        logger.info("======================\n")
    except Exception as e:
        logger.error(f"Lỗi khi đọc thống kê proxy: {str(e)}")

# Lớp Worker để xử lý từng luồng đăng ký
class TiktokRegWorker:
    """Lớp xử lý đăng ký tài khoản TikTok"""

    def __init__(
        self, worker_id, proxy_queue, use_proxy_global: bool,
        mail_manager=None, max_retries: int = 3,
        desired_username: Optional[str] = None,
        tiktok_password: Optional[str] = None,
        qr_policy: str = 'skip',
    ):
        self.worker_id = worker_id
        self.proxy_queue = proxy_queue
        self.use_proxy_global = use_proxy_global # Biến cờ để kiểm soát việc sử dụng proxy
        self.logger = logging.getLogger(f"Worker-{worker_id}")
        self.driver: Optional[webdriver.Chrome] = None
        self.proxy_used: Optional[str] = None
        self.proxy_bridge: Optional[LocalAuthProxyBridge] = None  # Cầu nối cho proxy có xác thực
        self.post_signup_state = 'unknown'
        self.mail_manager = mail_manager or OutlookMailManager()
        self.max_retries = max(1, int(max_retries))
        self.desired_username = (desired_username or '').strip().lstrip('@') or None
        self.tiktok_password = tiktok_password or f"hvht{random.randint(100000, 999999)}@HoHiep"
        self.qr_policy = qr_policy if qr_policy in ('skip', 'wait') else 'skip'
        
    def log(self, message, level="info"):
        """Ghi log với định dạng worker"""
        log_message = f"[Worker-{self.worker_id}] {message}"
        if level == "debug":
            self.logger.debug(log_message)
        elif level == "warning":
            self.logger.warning(log_message)
        elif level == "error":
            self.logger.error(log_message)
        else:
            self.logger.info(log_message)
    
    def get_proxy(self) -> Optional[str]:
        """Lấy một proxy từ hàng đợi và kiểm tra hoạt động.
        Nếu hàng đợi trống hoặc proxy không hoạt động, trả về None."""
        if not self.use_proxy_global:
            self.log("Chế độ không sử dụng proxy đã được kích hoạt. Bỏ qua việc lấy proxy.", "debug")
            return None # Không cần proxy nếu chế độ không dùng proxy
            
        try:
            proxy = self.proxy_queue.get(block=False)
            self.log(f"Đã lấy proxy: {proxy} từ hàng đợi.")

            if check_proxy(proxy):
                # Không đưa lại vào hàng đợi ngay lập tức, chỉ đưa lại khi thành công
                return proxy
            else:
                self.log(f"Proxy {proxy} không hoạt động. Đánh dấu và không sử dụng.", "warning")
                # Nếu proxy không hoạt động, đưa nó lại vào cuối hàng đợi để tránh lặp lại ngay lập tức
                self.proxy_queue.put(proxy)
                return None
        except queue.Empty:
            self.log("Hàng đợi proxy trống, không còn proxy để sử dụng.", "warning")
            return None
        except Exception as e:
            self.log(f"Lỗi không xác định khi lấy hoặc kiểm tra proxy: {str(e)}", "error")
            return None
        
    def current_username(self, fallback_email: str) -> str:
        """Đọc username TikTok thật từ liên kết Profile sau khi đăng nhập."""
        profile_links = self.driver.find_elements(
            By.CSS_SELECTOR, "a[data-e2e='nav-profile'], a[href*='tiktok.com/@'], a[href^='/@']"
        ) if self.driver else []
        for link in profile_links:
            href = link.get_attribute('href') or ''
            match = re.search(r'/@([^/?#]+)', href)
            if match:
                return unquote(match.group(1))
        return fallback_email.split('@', 1)[0]

    def set_username(self, username: str, timeout=30) -> bool:
        """Đặt username qua trang chỉnh sửa hồ sơ chính thức của TikTok."""
        if not re.fullmatch(r'[A-Za-z0-9._]{2,24}', username or ''):
            self.log("Username yêu cầu không hợp lệ.", "error")
            return False
        try:
            self.driver.get("https://www.tiktok.com/setting/profile")
            field = WebDriverWait(self.driver, timeout).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR,
                    "input[name='username'], input[data-e2e*='username'], "
                    "input[placeholder*='username' i]"))
            )
            field.clear()
            field.send_keys(username)
            save_locators = [
                (By.CSS_SELECTOR, "button[data-e2e*='save']"),
                (By.XPATH, "//button[normalize-space()='Save' or normalize-space()='Lưu']"),
                (By.CSS_SELECTOR, "button[type='submit']"),
            ]
            if not self.click_first_visible(save_locators, timeout, "nút lưu username"):
                return False
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.current_username('') == username:
                    self.log(f"Đã đặt username: {username}")
                    return True
                body = self.driver.find_element(By.TAG_NAME, 'body').text.lower()
                if 'username is taken' in body or 'tên người dùng này đã được sử dụng' in body:
                    self.log(f"Username {username} đã được sử dụng.", "error")
                    return False
                time.sleep(1)
            self.log("TikTok chưa xác nhận username mới.", "error")
            return False
        except Exception as exc:
            self.log(f"Không thể đặt username {username}: {exc}", "error")
            return False

    def save_account(self, username, email_pass, tiktok_pass, two_factor_secret='') -> bool:
        """Chỉ lưu tài khoản khi có secret 2FA thật, không tạo khóa giả."""
        del email_pass
        try:
            record = format_account_record(username, tiktok_pass, two_factor_secret)
        except ValueError as exc:
            self.log(f"Không lưu tài khoản: {exc}", "error")
            return False
        with file_lock:
            with open(ACCOUNTS_FILE, "a", encoding='utf-8') as file:
                file.write(record + "\n")
            try:
                os.chmod(ACCOUNTS_FILE, 0o600)
            except OSError:
                pass
            self.log(f"Đã lưu thông tin tài khoản: {username}")
        return True

    def confirm_real_account_creation(self, email: str) -> bool:
        """Yêu cầu xác nhận ngay trước thao tác tạo tài khoản thật."""
        with confirmation_lock:
            prompt = (
                f"\nSắp bấm Sign up để tạo tài khoản TikTok thật bằng {email}. "
                "Nhập CREATE để xác nhận: "
            )
            try:
                return input(prompt).strip() == 'CREATE'
            except (EOFError, KeyboardInterrupt):
                return False
            
    def close_driver(self):
        """Đóng trình duyệt và dọn sạch tài nguyên tạm (cầu nối proxy)"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                self.log(f"Lỗi khi đóng trình duyệt: {str(e)}", "warning")
            self.driver = None
            self.log("Đã đóng trình duyệt.")

        if self.proxy_bridge:
            self.proxy_bridge.stop()
            self.proxy_bridge = None

    def setup_driver(self, proxy: Optional[str] = None) -> Optional[webdriver.Chrome]:
        """Thiết lập trình duyệt Chrome với các tùy chọn tối ưu và kích thước cửa sổ di động"""
        options = ChromeOptions()

        if chrome_path:
            options.binary_location = chrome_path
        else:
            self.log("Không tìm thấy Chrome trong thư mục tool, để Selenium tự dò Chrome trên hệ thống.", "warning")

        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Thiết lập User-Agent ngẫu nhiên
        if CONFIG['USE_CUSTOM_USER_AGENT']:
            user_agent = get_random_user_agent()
            options.add_argument(f"user-agent={user_agent}")
            self.log(f"Sử dụng User-Agent tùy chỉnh: {user_agent}")
        else:
            self.log("Sử dụng User-Agent gốc khớp với phiên bản Chrome.")

        proxy_info = None
        if proxy and self.use_proxy_global:
            self.log(f"Cố gắng cấu hình proxy: {proxy_display(proxy)}")
            proxy_info = parse_proxy(proxy)
            if not proxy_info:
                self.log(f"Định dạng proxy không hợp lệ: {proxy_display(proxy)}. "
                         f"Hỗ trợ ip:port hoặc ip:port:user:pass", "error")
                log_proxy_usage(proxy, success=False, worker_id=self.worker_id)
                return None

            self.proxy_used = proxy
            try:
                if proxy_info['username']:
                    # Proxy có xác thực -> đi qua cầu nối nội bộ để tự thêm header xác thực
                    self.proxy_bridge = LocalAuthProxyBridge(proxy_info)
                    local_port = self.proxy_bridge.start()
                    options.add_argument(f'--proxy-server=http://127.0.0.1:{local_port}')
                    self.log(f"Đã cấu hình proxy CÓ xác thực: {proxy_info['host']}:{proxy_info['port']} "
                             f"(user: {proxy_info['username']}) qua cầu nối nội bộ 127.0.0.1:{local_port}")
                else:
                    proxy_url = f"{proxy_info['scheme']}://{proxy_info['host']}:{proxy_info['port']}"
                    options.add_argument(f'--proxy-server={proxy_url}')
                    self.log(f"Đã cấu hình proxy không xác thực: {proxy_url}")

            except Exception as e:
                self.log(f"Lỗi khi cấu hình proxy cho driver: {str(e)}", "error")
                log_proxy_usage(proxy, success=False, worker_id=self.worker_id)
                return None
        elif self.use_proxy_global: 
            self.log("Chế độ sử dụng proxy được bật nhưng không có proxy khả dụng để cấu hình.", "warning")
        else: 
            self.log("Chương trình đang chạy ở chế độ không sử dụng proxy.", "info")

        # Thiết lập kích thước cửa sổ thành hình chữ nhật nhỏ gọn
        options.add_argument(f"--window-size={CONFIG['BROWSER_WIDTH']},{CONFIG['BROWSER_HEIGHT']}")
        self.log(f"Đặt kích thước cửa sổ: {CONFIG['BROWSER_WIDTH']}x{CONFIG['BROWSER_HEIGHT']}")

        options.add_argument("--disable-infobars")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.page_load_timeout = CONFIG['PAGE_LOAD_TIMEOUT']
        options.add_argument("--incognito")

        try:
            driver = webdriver.Chrome(options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            random_delay()
            return driver
        except Exception as e:
            self.log(f"Lỗi khi khởi tạo driver: {str(e)}", "error")
            return None
            
    def wait_and_click(self, locator, timeout=CONFIG['ELEMENT_WAIT_TIMEOUT'], description=None) -> bool:
        """Đợi và click vào phần tử khi có thể click được, thử lại bằng JS nếu bị chặn."""
        element_desc = description or f"phần tử {locator}"
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable(locator)
            )
            element.click()
            self.log(f"Đã click vào {element_desc}")
            return True
        except (ElementClickInterceptedException, StaleElementReferenceException) as e:
            self.log(f"Click thường bị chặn/stale cho {element_desc}: {str(e)}. Thử click bằng JavaScript...", "warning")
            try:
                # Try clicking with JavaScript
                element = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located(locator)
                )
                self.driver.execute_script("arguments[0].click();", element)
                self.log(f"Đã click bằng JavaScript vào {element_desc}")
                return True
            except Exception as js_e:
                self.log(f"Không thể click bằng JavaScript vào {element_desc}: {str(js_e)}", "error")
                return False
        except TimeoutException as e:
            self.log(f"Không thể click vào {element_desc} (Timeout): {str(e)}", "error")
            return False
        except NoSuchElementException:
            self.log(f"Không tìm thấy {element_desc}", "error")
            return False
            
    def wait_and_send_keys(self, locator, text, timeout=CONFIG['ELEMENT_WAIT_TIMEOUT'], description=None) -> bool:
        """Đợi và điền giá trị vào phần tử"""
        element_desc = description or f"phần tử {locator}"
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(locator)
            )
            element.clear()
            element.send_keys(text)
            self.log(f"Đã điền '{text}' vào {element_desc}")
            return True
        except (TimeoutException, NoSuchElementException) as e:
            self.log(f"Không thể điền vào {element_desc} (Timeout/NoSuchElement): {str(e)}", "error")
            return False

    def decode_qr_element(self, element) -> Optional[str]:
        """Chụp một phần tử QR trên trang và giải mã nội dung bằng OpenCV."""
        try:
            image_bytes = element.screenshot_as_png
            image_array = np.frombuffer(image_bytes, dtype=np.uint8)
            image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
            if image is None:
                return None
            value, _points, _straight_qr = cv2.QRCodeDetector().detectAndDecode(image)
            if value and value.strip():
                return value.strip()

            # ZXing đọc tốt hơn với QR dày hoặc có logo mà OpenCV bỏ sót.
            barcode = zxingcpp.read_barcode(image)
            if barcode and barcode.text:
                return barcode.text.strip() or None
            return None
        except (StaleElementReferenceException, WebDriverException, cv2.error) as e:
            self.log(f"Không thể giải mã phần tử QR: {str(e)}", "warning")
            return None

    def get_adb_device(self) -> Optional[str]:
        """Tìm thiết bị ADB online, ưu tiên serial TCP/IP."""
        configured = CONFIG.get('ADB_DEVICE', '').strip()
        try:
            result = subprocess.run(
                ['adb', 'devices'], capture_output=True, text=True, timeout=10, check=True
            )
            devices = []
            for line in result.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == 'device':
                    devices.append(parts[0])
            if configured:
                return configured if configured in devices else None
            return next((serial for serial in devices if re.match(r'^\d+\.\d+\.\d+\.\d+:\d+$', serial)), devices[0] if devices else None)
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            self.log(f"Không thể kiểm tra ADB: {str(e)}", "warning")
            return None

    def open_qr_on_android(self, value: str) -> bool:
        """Mở payload QR trên Android qua ADB để người dùng chỉ cần xác nhận."""
        if not re.match(r'^(?:https?|tiktok|snssdk\d*):', value, flags=re.IGNORECASE):
            self.log("Payload QR không phải liên kết có thể mở trên Android.", "warning")
            return False
        serial = self.get_adb_device()
        if not serial:
            self.log("Không tìm thấy thiết bị ADB online để chuyển QR.", "warning")
            return False
        try:
            target_value = value
            # TikTok OneLink thường gói deep-link thật trong tham số af_dp.
            # Mở trực tiếp deep-link để tránh Android chuyển sang App Store.
            query = parse_qs(urlparse(value).query)
            if query.get('af_dp'):
                target_value = unquote(query['af_dp'][0])
            parsed_target = urlparse(target_value)
            if (
                parsed_target.scheme.lower().startswith(('snssdk', 'tiktok'))
                and not parsed_target.netloc
                and parsed_target.path in ('', '/')
                and not parsed_target.query
            ):
                self.log(
                    "QR này chỉ mở trang chủ TikTok, không có token xác nhận; "
                    "bỏ qua ADB và chuyển sang khôi phục email.",
                    "warning",
                )
                return False
            subprocess.run(
                ['adb', '-s', serial, 'shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'],
                capture_output=True, text=True, timeout=10, check=False,
            )
            result = subprocess.run(
                ['adb', '-s', serial, 'shell', 'am', 'start', '-W',
                 '-a', 'android.intent.action.VIEW', '-d', target_value],
                capture_output=True, text=True, timeout=20, check=False,
            )
            if result.returncode == 0 and 'Error:' not in result.stdout:
                self.log(f"Đã chuyển QR sang điện thoại ADB {serial}; hãy bấm xác nhận trong TikTok.")
                return True
            self.log(f"Android không mở được QR: {(result.stderr or result.stdout).strip()}", "warning")
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            self.log(f"Lỗi khi chuyển QR qua ADB: {str(e)}", "warning")
        return False

    def open_decoded_qr_url(self, value: str) -> bool:
        """Mở URL HTTP(S) từ QR trong tab phụ mà không rời tab đăng ký."""
        if not re.match(r'^https?://', value, flags=re.IGNORECASE):
            return False
        try:
            self.driver.execute_script("window.open(arguments[0], '_blank', 'noopener');", value)
            self.log("Đã mở URL từ QR trong tab phụ; tab đăng ký vẫn được giữ nguyên.")
            return True
        except WebDriverException as e:
            self.log(f"Không thể mở URL từ QR: {str(e)}", "warning")
            return False

    def click_first_visible(self, locators, timeout=15, description="phần tử") -> bool:
        """Click locator khả dụng đầu tiên trong danh sách, hỗ trợ giao diện Anh/Việt."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for locator in locators:
                for element in self.driver.find_elements(*locator):
                    try:
                        if not element.is_displayed() or not element.is_enabled():
                            continue
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'});", element
                        )
                        try:
                            element.click()
                        except (ElementClickInterceptedException, StaleElementReferenceException):
                            self.driver.execute_script("arguments[0].click();", element)
                        self.log(f"Đã click {description}.")
                        return True
                    except (StaleElementReferenceException, WebDriverException):
                        continue
            time.sleep(0.5)
        self.log(f"Không tìm thấy {description} sau {timeout} giây.", "warning")
        return False

    def switch_signup_to_email(self, timeout=15) -> bool:
        """Chuyển form đăng ký sang email mà không phụ thuộc XPath tuyệt đối.

        Đây chỉ là lựa chọn kênh đăng ký email được TikTok cung cấp; hàm không
        bỏ qua CAPTCHA, OTP hay bất kỳ bước xác minh bảo mật nào.
        """
        email_input_locator = (
            By.CSS_SELECTOR,
            "input[name='email'], input[type='email'], input[autocomplete='email']",
        )

        # Có phiên bản trang đã mở sẵn form email.
        if any(
            element.is_displayed()
            for element in self.driver.find_elements(*email_input_locator)
        ):
            self.log("Form đăng ký email đã được hiển thị.")
            return True

        email_mode_locators = [
            (By.CSS_SELECTOR, "a[href*='/signup/phone-or-email/email']"),
            (By.CSS_SELECTOR, "a[href*='phone-or-email'][href*='email']"),
            (By.CSS_SELECTOR, "[data-e2e*='email-sign-up']"),
            (By.CSS_SELECTOR, "[data-e2e*='email-signup']"),
            (By.XPATH, "//*[self::a or self::button or @role='button' or @role='tab'][contains(normalize-space(.), 'Sign up with email')]"),
            (By.XPATH, "//*[self::a or self::button or @role='button' or @role='tab'][contains(normalize-space(.), 'Use email')]"),
            (By.XPATH, "//*[self::a or self::button or @role='button' or @role='tab'][contains(normalize-space(.), 'Đăng ký bằng email')]"),
            (By.XPATH, "//*[self::a or self::button or @role='button' or @role='tab'][contains(normalize-space(.), 'Sử dụng email')]"),
        ]
        self.click_first_visible(email_mode_locators, timeout, "lựa chọn đăng ký bằng email")

        # URL chính thức là fallback ổn định khi nhãn giao diện thay đổi.
        if not any(
            element.is_displayed()
            for element in self.driver.find_elements(*email_input_locator)
        ):
            self.log("Chưa thấy form email; mở trực tiếp trang đăng ký email.", "warning")
            self.driver.get("https://www.tiktok.com/signup/phone-or-email/email")

        try:
            WebDriverWait(self.driver, timeout).until(
                EC.visibility_of_element_located(email_input_locator)
            )
            self.log("Đã chuyển sang form đăng ký bằng email.")
            return True
        except TimeoutException:
            self.log(
                "Không tìm thấy ô email. TikTok có thể đang yêu cầu CAPTCHA, "
                "đổi giao diện hoặc giới hạn đăng ký tại IP hiện tại.",
                "error",
            )
            return False

    def reset_password_via_email(self, email: str, new_password: str, timeout=90) -> bool:
        """Thực hiện luồng Quên mật khẩu và nhận OTP qua hộp thư email."""
        self.log(f"Bắt đầu khôi phục mật khẩu TikTok qua email: {email}")
        old_message_ids = self.mail_manager.get_message_ids()
        try:
            self.driver.get("https://www.tiktok.com/login")

            login_method_locators = [
                (By.XPATH, "//*[@role='link' or @role='button' or self::a or self::button][contains(., 'Use phone / email / username')]"),
                (By.XPATH, "//*[@role='link' or @role='button' or self::a or self::button][contains(., 'Use phone or email')]"),
                (By.XPATH, "//*[@role='link' or @role='button' or self::a or self::button][contains(., 'Đăng nhập bằng số điện thoại/email/tên người dùng')]"),
                (By.XPATH, "//*[@role='link' or @role='button' or self::a or self::button][contains(., 'Sử dụng số điện thoại/email/tên người dùng')]"),
                (By.XPATH, "//*[@role='link' or @role='button' or self::a or self::button][contains(., 'Số điện thoại / Email / Tên người dùng')]"),
            ]
            if not self.click_first_visible(login_method_locators, 12, "'Số điện thoại/email/tên người dùng'"):
                self.driver.get("https://www.tiktok.com/login/phone-or-email/email")

            email_tab_locators = [
                (By.XPATH, "//*[@role='tab' or @role='link' or @role='button' or self::a or self::button][contains(., 'Email / Username')]"),
                (By.XPATH, "//*[@role='tab' or @role='link' or @role='button' or self::a or self::button][contains(., 'Email/Username')]"),
                (By.XPATH, "//*[@role='tab' or @role='link' or @role='button' or self::a or self::button][contains(., 'Email / Tên người dùng')]"),
                (By.XPATH, "//*[@role='tab' or @role='link' or @role='button' or self::a or self::button][contains(., 'Email/Tên người dùng')]"),
                (By.XPATH, "//*[@role='tab' or @role='link' or @role='button' or self::a or self::button][contains(., 'Đăng nhập bằng email hoặc tên người dùng')]"),
            ]
            self.click_first_visible(email_tab_locators, 8, "tab 'Email/Tên người dùng'")

            forgot_locators = [
                (By.CSS_SELECTOR, "a[data-e2e*='forgot'], button[data-e2e*='forgot']"),
                (By.XPATH, "//*[self::a or self::button or @role='button'][contains(., 'Forgot password')]"),
                (By.XPATH, "//*[self::a or self::button or @role='button'][contains(., 'Quên mật khẩu')]"),
                (By.XPATH, "//*[@role='link' or @role='button' or self::a or self::button][contains(., 'quên mật khẩu')]"),
            ]
            if not self.click_first_visible(forgot_locators, 15, "'Quên mật khẩu?'"):
                return False

            # Một số phiên bản TikTok hỏi kênh nhận mã sau khi bấm Quên mật khẩu.
            reset_email_locators = [
                (By.XPATH, "//*[self::a or self::button or @role='button'][contains(., 'Reset with email')]"),
                (By.XPATH, "//*[self::a or self::button or @role='button'][contains(., 'Email')]"),
                (By.XPATH, "//*[self::a or self::button or @role='button'][contains(., 'Khôi phục bằng email')]"),
            ]
            self.click_first_visible(reset_email_locators, 5, "nhận mã qua email")

            email_input = WebDriverWait(self.driver, CONFIG['ELEMENT_WAIT_TIMEOUT']).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    "input[name='email'], input[name='username'], input[type='email'], "
                    "input[autocomplete='username']"))
            )
            email_input.clear()
            email_input.send_keys(email)
            self.log("Đã điền email khôi phục.")

            send_code_locators = [
                (By.CSS_SELECTOR, "button[data-e2e='send-code-button']"),
                (By.XPATH, "//button[contains(., 'Send code') or contains(., 'Gửi mã')]"),
                (By.XPATH, "//*[@role='button'][contains(., 'Send code') or contains(., 'Gửi mã')]"),
            ]
            if not self.click_first_visible(send_code_locators, 15, "nút 'Gửi mã'"):
                return False

            verification_code = self.wait_for_email_otp(old_message_ids)
            if not verification_code:
                self.log("Không nhận được OTP khôi phục mật khẩu qua email.", "error")
                return False

            code_input = WebDriverWait(self.driver, CONFIG['ELEMENT_WAIT_TIMEOUT']).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    "input[name*='code' i], input[placeholder*='code' i], "
                    "input[placeholder*='mã' i], input[inputmode='numeric']"))
            )
            code_input.clear()
            code_input.send_keys(verification_code)
            self.log("Đã điền OTP khôi phục từ email.")

            def visible_password_inputs(driver):
                return [
                    element for element in driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
                    if element.is_displayed()
                ]

            try:
                password_inputs = WebDriverWait(self.driver, 5).until(visible_password_inputs)
            except TimeoutException:
                # Có giao diện tách bước: xác nhận OTP trước, sau đó mới hiện ô mật khẩu.
                continue_locators = [
                    (By.XPATH, "//button[contains(., 'Continue') or contains(., 'Next')]"),
                    (By.XPATH, "//button[contains(., 'Tiếp tục') or contains(., 'Tiếp theo')]"),
                    (By.CSS_SELECTOR, "button[type='submit']"),
                ]
                if not self.click_first_visible(continue_locators, 10, "nút tiếp tục sau OTP"):
                    return False
                password_inputs = WebDriverWait(
                    self.driver, CONFIG['ELEMENT_WAIT_TIMEOUT']
                ).until(visible_password_inputs)
            for password_input in password_inputs[:2]:
                password_input.clear()
                password_input.send_keys(new_password)

            submit_locators = [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(., 'Reset') or contains(., 'Continue') or contains(., 'Log in')]"),
                (By.XPATH, "//button[contains(., 'Đặt lại') or contains(., 'Tiếp tục') or contains(., 'Đăng nhập')]"),
            ]
            if not self.click_first_visible(submit_locators, 15, "nút xác nhận mật khẩu mới"):
                return False

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                page_text = ' '.join(self.driver.find_element(By.TAG_NAME, 'body').text.lower().split())
                if any(phrase in page_text for phrase in (
                    'password reset', 'password has been reset', 'reset successfully',
                    'đặt lại mật khẩu thành công', 'mật khẩu đã được đặt lại',
                )):
                    self.log("Đã đặt lại mật khẩu TikTok qua email.")
                    return True
                try:
                    password_form_closed = not password_inputs[0].is_displayed()
                except StaleElementReferenceException:
                    password_form_closed = True
                if '/login' in self.driver.current_url.lower() and password_form_closed:
                    self.log("Luồng đặt lại mật khẩu đã chuyển về trang đăng nhập.")
                    return True
                time.sleep(1)

            self.log("Hết thời gian chờ xác nhận đặt lại mật khẩu.", "error")
            return False
        except Exception as e:
            self.log(f"Lỗi trong luồng Quên mật khẩu qua email: {str(e)}", "error")
            try:
                screenshot = os.path.join(log_dir, f"password_reset_failed_worker_{self.worker_id}.png")
                self.driver.save_screenshot(screenshot)
                self.log(f"Đã lưu ảnh lỗi khôi phục mật khẩu: {screenshot}", "warning")
            except Exception:
                pass
            return False

    def wait_for_email_otp(self, old_message_ids=None) -> Optional[str]:
        """Chờ OTP TikTok theo một deadline duy nhất và gửi lại một lần khi cần."""
        deadline = time.monotonic() + CONFIG['EMAIL_OTP_WAIT_TIME']
        resend_at = time.monotonic() + CONFIG['EMAIL_OTP_RESEND_AFTER']
        resent = False
        attempt = 0
        blocked_phrases = (
            'too many attempts', 'try again later', 'maximum number of attempts',
            'quá nhiều lần thử', 'thử lại sau', 'captcha',
            'drag the slider', 'kéo thanh trượt',
        )

        while time.monotonic() < deadline:
            attempt += 1
            code = self.mail_manager.get_verification_code(
                max_attempts=1,
                delay=0,
                exclude_message_ids=old_message_ids,
                log_final_error=False,
            )
            if code:
                self.log(f"Đã nhận OTP email sau {attempt} lần kiểm tra.")
                return code

            try:
                page_text = ' '.join(
                    self.driver.find_element(By.TAG_NAME, 'body').text.lower().split()
                )
                if any(phrase in page_text for phrase in blocked_phrases):
                    self.log(
                        "TikTok đang chặn yêu cầu OTP hoặc yêu cầu CAPTCHA; "
                        "không tiếp tục gửi lặp.",
                        "error",
                    )
                    break
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            if not resent and time.monotonic() >= resend_at:
                resend_locators = [
                    (By.CSS_SELECTOR, "button[data-e2e='send-code-button']"),
                    (By.XPATH, "//button[contains(., 'Resend code') or contains(., 'Send code')]"),
                    (By.XPATH, "//button[contains(., 'Gửi lại mã') or contains(., 'Gửi mã')]"),
                ]
                if self.click_first_visible(resend_locators, 5, "nút gửi lại OTP"):
                    self.log("Đã yêu cầu TikTok gửi lại OTP một lần.", "warning")
                else:
                    self.log("Nút gửi lại OTP chưa khả dụng.", "warning")
                resent = True

            remaining = max(0, int(deadline - time.monotonic()))
            self.log(f"Chưa có OTP mới; còn chờ tối đa {remaining} giây.")
            time.sleep(min(5, max(0, deadline - time.monotonic())))

        try:
            screenshot = os.path.join(log_dir, f"otp_not_received_worker_{self.worker_id}.png")
            self.driver.save_screenshot(screenshot)
            self.log(f"Đã lưu ảnh trạng thái không nhận OTP: {screenshot}", "warning")
        except Exception:
            pass
        return None

    def click_signup_button(self, timeout=30) -> bool:
        """Tìm và nhấn nút Sign up bằng locator ổn định, không phụ thuộc một XPath tuyệt đối."""
        locators = [
            (By.CSS_SELECTOR, "button[data-e2e='signup-button']"),
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.XPATH, "//button[normalize-space()='Sign up' or normalize-space()='Đăng ký']"),
            (By.XPATH, "//form//button[last()]"),
        ]
        deadline = time.monotonic() + timeout
        last_state = "không tìm thấy nút"

        while time.monotonic() < deadline:
            # Sau khi nhập OTP, TikTok có thể tự submit form và chuyển thẳng
            # sang màn hình QR. Khi đó nút Sign up không còn tồn tại, nhưng
            # đây là một bước chuyển trang hợp lệ chứ không phải lỗi click.
            try:
                body_text = ' '.join(
                    self.driver.find_element(By.TAG_NAME, 'body').text.lower().split()
                )
                auto_submitted = any(phrase in body_text for phrase in (
                    'continue on the tiktok app',
                    'continue with the tiktok app',
                    'for security reasons',
                    'tiếp tục trên ứng dụng tiktok',
                    'vì mục đích bảo mật',
                    'quét mã qr',
                ))
                if auto_submitted:
                    self.log(
                        "Form đã tự chuyển sang bước QR sau khi nhập mã; "
                        "không cần bấm Sign up thêm.",
                        "warning",
                    )
                    return True
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            for locator in locators:
                for button in self.driver.find_elements(*locator):
                    try:
                        if not button.is_displayed():
                            continue
                        label = (button.text or button.get_attribute('aria-label') or 'Sign up').strip()
                        if not button.is_enabled() or button.get_attribute('disabled') is not None:
                            last_state = f"nút '{label}' đang bị vô hiệu hóa"
                            continue
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'});", button
                        )
                        try:
                            button.click()
                        except (ElementClickInterceptedException, StaleElementReferenceException):
                            self.driver.execute_script("arguments[0].click();", button)
                        self.log(f"Đã click nút '{label}'.")
                        return True
                    except (StaleElementReferenceException, WebDriverException):
                        continue
            time.sleep(1)

        try:
            screenshot = os.path.join(log_dir, f"signup_failed_worker_{self.worker_id}.png")
            self.driver.save_screenshot(screenshot)
            self.log(f"Đã lưu ảnh lỗi bước Sign up: {screenshot}", "warning")
        except Exception:
            pass
        self.log(f"Không thể nhấn Sign up sau {timeout} giây: {last_state}.", "error")
        return False

    def click_optional_post_signup_skip(self) -> Optional[str]:
        """Bấm nút Skip chính thức, kể cả khi nó nằm trong shadow DOM/iframe cùng origin.

        Hàm chỉ tìm control có nhãn bỏ qua rõ ràng. Nó không sửa trạng thái trang,
        cookie hoặc response để giả lập việc đã vượt qua checkpoint bảo mật.
        """
        skip_locators = [
            (By.CSS_SELECTOR, "button[data-e2e*='skip' i], [role='button'][data-e2e*='skip' i]"),
            (By.CSS_SELECTOR, "button[aria-label*='skip' i], [role='button'][aria-label*='skip' i]"),
            (By.XPATH, "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'skip')]"),
            (By.XPATH, "//*[self::button or self::a or @role='button' or @role='link' or @tabindex][normalize-space()='Not now' or normalize-space()='Maybe later' or normalize-space()='Bỏ qua' or normalize-space()='Để sau']"),
            # Một số bản giao diện Việt render "Bỏ qua" bằng div/span có
            # click handler thay vì button/link có semantic role.
            (By.XPATH, "//*[normalize-space()='Bỏ qua' or normalize-space()='Để sau']"),
        ]
        for locator in skip_locators:
            for element in self.driver.find_elements(*locator):
                try:
                    if not element.is_displayed() or not element.is_enabled():
                        continue
                    label = (
                        element.text
                        or element.get_attribute('aria-label')
                        or element.get_attribute('data-e2e')
                        or 'Skip'
                    ).strip()
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});", element
                    )
                    try:
                        element.click()
                    except (ElementClickInterceptedException, StaleElementReferenceException):
                        self.driver.execute_script("arguments[0].click();", element)
                    return label
                except (StaleElementReferenceException, WebDriverException):
                    continue

        # TikTok đôi khi render onboarding trong open shadow root hoặc iframe
        # cùng origin. Selenium locator thường không đi xuyên qua hai lớp này.
        script = r"""
            const accepted = new Set([
                'skip', 'skip for now', 'not now', 'maybe later',
                'bỏ qua', 'để sau'
            ]);
            const normalize = value => (value || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const visible = node => {
                const rect = node.getBoundingClientRect();
                const style = node.ownerDocument.defaultView.getComputedStyle(node);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
                    style.visibility !== 'hidden' && style.pointerEvents !== 'none';
            };
            const roots = [document];
            const seen = new Set();
            while (roots.length) {
                const root = roots.shift();
                if (!root || seen.has(root)) continue;
                seen.add(root);
                for (const node of root.querySelectorAll('*')) {
                    if (node.shadowRoot) roots.push(node.shadowRoot);
                    if (node.tagName === 'IFRAME') {
                        try { if (node.contentDocument) roots.push(node.contentDocument); } catch (_) {}
                    }
                }
                for (const node of root.querySelectorAll(
                    "button, [role='button'], [role='link'], a, [tabindex], " +
                    "[data-e2e*='skip' i], div, span"
                )) {
                    const label = normalize(
                        node.innerText || node.textContent || node.getAttribute('aria-label') ||
                        node.getAttribute('title') || node.getAttribute('data-e2e')
                    );
                    const officialSkip = accepted.has(label) || label.startsWith('skip ')
                        || normalize(node.getAttribute('data-e2e')).includes('skip');
                    if (officialSkip && !node.disabled && visible(node)) {
                        node.scrollIntoView({block: 'center'});
                        node.click();
                        return label || 'skip';
                    }
                }
            }
            return null;
        """
        try:
            return self.driver.execute_script(script)
        except WebDriverException:
            return None

    def handle_post_signup(self, timeout=30) -> bool:
        """Xử lý các màn hình xuất hiện sau khi đăng ký.

        TikTok có thể hiển thị một bước QR bắt buộc vì lý do bảo mật, hoặc một
        bước giới thiệu có nút Skip/Not now. Chỉ bỏ qua bước tùy chọn; QR bảo
        mật bắt buộc phải được hoàn tất trên điện thoại và không được coi là
        đăng ký thành công.
        """
        success_locators = [
            (By.CSS_SELECTOR, "[data-e2e='profile-icon']"),
            (By.CSS_SELECTOR, "[data-e2e='nav-profile']"),
            (By.CSS_SELECTOR, "[data-e2e='nav-upload']"),
        ]
        security_phrases = (
            "for security reasons", "continue on your phone", "scan the qr code",
            "continue with the tiktok app", "vì lý do bảo mật", "tiếp tục trên điện thoại",
            "tiếp tục trên ứng dụng tiktok", "quét mã qr",
        )
        signup_rejected_phrases = (
            "something went wrong", "please try again later", "try again later",
            "sorry, something went wrong", "couldn't sign up", "unable to sign up",
            "rất tiếc, đã xảy ra lỗi", "vui lòng thử lại sau",
            "không thể đăng ký", "đăng ký không thành công",
        )
        self.post_signup_state = 'waiting'
        deadline = time.monotonic() + timeout
        saw_security_qr = False
        qr_wait_announced = False
        decoded_qr_value = None
        qr_sent_to_phone = False
        skip_clicked_at = None
        security_detected_at = None
        last_progress_log = time.monotonic()

        while time.monotonic() < deadline:
            # Ưu tiên nút bỏ qua chính thức nếu đây chỉ là onboarding tùy chọn.
            if skip_clicked_at is None:
                skip_label = self.click_optional_post_signup_skip()
                if skip_label:
                    skip_clicked_at = time.monotonic()
                    # Không bấm lặp lại mỗi vòng: việc reset mốc 10 giây liên tục
                    # chính là một nguyên nhân khiến luồng cũ trông như bị đứng.
                    self.log(f"Đã bấm nút bỏ qua onboarding: '{skip_label}'.")

            page_text = ""
            try:
                raw_page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
                # Selenium giữ ký tự xuống dòng theo layout. Chuẩn hóa khoảng
                # trắng để các câu như "tiếp tục trên \n ứng dụng" vẫn khớp.
                page_text = ' '.join(raw_page_text.split())
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            # Nếu TikTok giữ nguyên form và hiển thị lỗi sau khi submit thì tài
            # khoản chưa được tạo. Dừng sớm để worker có thể mở một phiên mới,
            # tạo hộp thư mới và thử lại; không chuyển sang trang đăng nhập.
            still_on_signup = '/signup' in self.driver.current_url.lower()
            if still_on_signup and any(
                phrase in page_text for phrase in signup_rejected_phrases
            ):
                self.post_signup_state = 'signup_rejected'
                self.log(
                    "TikTok đã từ chối form đăng ký; sẽ dùng phiên và email mới "
                    "ở lần thử kế tiếp.",
                    "warning",
                )
                try:
                    screenshot = os.path.join(
                        log_dir, f"signup_rejected_worker_{self.worker_id}.png"
                    )
                    self.driver.save_screenshot(screenshot)
                    self.log(f"Đã lưu ảnh form bị từ chối: {screenshot}", "warning")
                except Exception:
                    pass
                return False

            qr_elements = self.driver.find_elements(
                By.CSS_SELECTOR,
                "[data-e2e*='qr-code'], [class*='qr-code' i], [id*='qr-code' i], "
                "img[alt*='QR code' i], img[src*='qr' i], canvas[data-e2e*='qr']"
            )
            has_qr_element = any(
                element.is_displayed()
                and element.size.get('width', 0) >= 120
                and element.size.get('height', 0) >= 120
                for element in qr_elements
            )
            if has_qr_element and decoded_qr_value is None:
                for element in qr_elements:
                    try:
                        if (
                            not element.is_displayed()
                            or element.size.get('width', 0) < 120
                            or element.size.get('height', 0) < 120
                        ):
                            continue
                    except StaleElementReferenceException:
                        continue

                    decoded_qr_value = self.decode_qr_element(element)
                    if decoded_qr_value:
                        self.log(f"Đã giải mã QR: {decoded_qr_value}")
                        if CONFIG['OPEN_DECODED_QR_URL']:
                            self.open_decoded_qr_url(decoded_qr_value)
                        if CONFIG['OPEN_QR_ON_ANDROID']:
                            qr_sent_to_phone = self.open_qr_on_android(decoded_qr_value)
                        break
            has_security_text = any(phrase in page_text for phrase in security_phrases)
            skip_transitioning = (
                skip_clicked_at is not None
                and time.monotonic() - skip_clicked_at < 10
            )
            # Một QR đơn lẻ có thể là QR onboarding tùy chọn hoặc phần tử cũ
            # đang fade-out. Chỉ kéo dài thời gian chờ khi trang nói rõ đây là
            # bước xác minh, và không vừa bấm nút Skip chính thức. Không bắt
            # buộc detector phải thấy QR vì TikTok có thể vẽ nó trong shadow DOM.
            is_security_checkpoint = (
                has_security_text and not skip_transitioning
            )
            if is_security_checkpoint:
                saw_security_qr = True
                self.post_signup_state = 'security_qr'
                if self.qr_policy == 'skip':
                    if security_detected_at is None:
                        security_detected_at = time.monotonic()
                        self.log(
                            "Đã thấy màn QR; đang chờ ngắn để tìm nút Skip chính thức...",
                            "warning",
                        )
                    discovery_elapsed = time.monotonic() - security_detected_at
                    if discovery_elapsed < CONFIG['QR_SKIP_DISCOVERY_TIME']:
                        time.sleep(0.5)
                        continue
                    self.post_signup_state = 'security_qr_required'
                    try:
                        screenshot = os.path.join(log_dir, f"qr_required_worker_{self.worker_id}.png")
                        self.driver.save_screenshot(screenshot)
                        self.log(f"Đã lưu ảnh checkpoint QR: {screenshot}", "warning")
                    except Exception:
                        pass
                    self.log(
                        "QR này là checkpoint bảo mật và không có nút Skip chính thức; "
                        "dừng lượt hiện tại ngay thay vì đứng chờ hoặc giả lập xác minh.",
                        "error",
                    )
                    return False
                if not qr_wait_announced:
                    try:
                        screenshot = os.path.join(log_dir, f"qr_worker_{self.worker_id}.png")
                        self.driver.save_screenshot(screenshot)
                        self.log(f"Đã lưu ảnh QR cần xử lý: {screenshot}", "warning")
                    except Exception:
                        pass
                    # QR web của TikTok đôi khi chỉ là deep-link mở ứng dụng,
                    # không mang token trong URL. Vẫn phải giữ nguyên phiên web
                    # để người dùng hoàn tất checkpoint trong app; không chuyển
                    # sang Quên mật khẩu vì đó không phải flow xác minh tương đương.
                    wait_time = CONFIG['ADB_QR_WAIT_TIME'] if qr_sent_to_phone else CONFIG['QR_WAIT_TIME']
                    action = (
                        "QR đã được mở trên điện thoại; hãy bấm xác nhận"
                        if qr_sent_to_phone
                        else "mở TikTok trên điện thoại để hoàn tất bước bảo mật"
                    )
                    self.log(
                        f"TikTok yêu cầu tiếp tục trên ứng dụng; {action} "
                        f"(tối đa {wait_time} giây).",
                        "warning",
                    )
                    deadline = time.monotonic() + wait_time
                    qr_wait_announced = True

            has_visible_account_ui = any(
                any(element.is_displayed() for element in self.driver.find_elements(*locator))
                for locator in success_locators
            )
            has_session_cookie = any(
                cookie.get('name', '').lower() in ('sessionid', 'sessionid_ss')
                and cookie.get('value')
                for cookie in self.driver.get_cookies()
            )
            # TikTok có thể tạo session thành công rồi giữ URL /signup để hỏi
            # TikTok ID. Đây là onboarding tùy chọn (có nút "Bỏ qua"), không
            # phải trạng thái đăng ký thất bại.
            has_optional_username_onboarding = any(phrase in page_text for phrase in (
                'create tiktok id', 'create a tiktok id',
                'tạo tiktok id', 'you can always change this later',
                'bạn luôn có thể thay đổi điều này sau',
            ))
            qr_was_completed = (
                saw_security_qr
                and not has_security_text
                and not has_qr_element
                and has_session_cookie
                and '/signup' not in self.driver.current_url.lower()
                and '/login' not in self.driver.current_url.lower()
            )
            if (
                (has_visible_account_ui and has_session_cookie)
                or (has_optional_username_onboarding and has_session_cookie)
                or qr_was_completed
            ):
                self.post_signup_state = 'confirmed'
                if has_optional_username_onboarding:
                    self.log("TikTok đã tạo session và chuyển sang bước TikTok ID tùy chọn.")
                else:
                    self.log("Đã vào trạng thái tài khoản sau đăng ký.")
                return True

            # Sau Skip, nhiều phiên chuyển về trang chủ trước khi icon profile
            # được render. Session cookie + rời khỏi trang signup là đủ để thoát
            # vòng chờ; bước đăng nhập/2FA phía sau vẫn kiểm tra tài khoản thật.
            left_signup_after_skip = (
                skip_clicked_at is not None
                and has_session_cookie
                and '/signup' not in self.driver.current_url.lower()
                and '/login' not in self.driver.current_url.lower()
            )
            if left_signup_after_skip:
                self.post_signup_state = 'confirmed'
                self.log("Đã bỏ qua onboarding và vào phiên tài khoản.")
                return True

            if time.monotonic() - last_progress_log >= 15:
                remaining = max(0, int(deadline - time.monotonic()))
                state = "checkpoint QR" if saw_security_qr else "chuyển trang sau đăng ký"
                self.log(f"Đang chờ {state}; còn tối đa {remaining} giây...", "warning")
                last_progress_log = time.monotonic()

            time.sleep(1)

        if saw_security_qr:
            self.post_signup_state = 'security_qr_timeout'
            self.log(
                "TikTok yêu cầu QR bảo mật bắt buộc và không cung cấp nút Skip. "
                "Cần hoàn tất bước này trên điện thoại; chương trình sẽ không lưu nhầm tài khoản là thành công.",
                "warning",
            )
        else:
            self.post_signup_state = 'unconfirmed'
            self.log("Không thể xác nhận trạng thái sau đăng ký trong thời gian chờ.", "error")
        try:
            screenshot = os.path.join(log_dir, f"post_signup_worker_{self.worker_id}.png")
            self.driver.save_screenshot(screenshot)
            self.log(f"Đã lưu ảnh trạng thái sau đăng ký: {screenshot}", "warning")
        except Exception:
            pass
        return False

    def enable_authenticator_2fa(self, timeout=120) -> Optional[str]:
        """Bật Authenticator bằng giao diện chính thức và trả về secret thật.

        Hàm chỉ tiếp tục khi QR chứa URI ``otpauth://`` và TikTok xác nhận mã
        TOTP. CAPTCHA hoặc yêu cầu xác nhận trên thiết bị vẫn phải do người dùng
        hoàn tất; không có cơ chế bỏ qua.
        """
        self.log("Mở phần Security để bật xác thực Authenticator...")
        try:
            self.driver.get("https://www.tiktok.com/setting/security")
            WebDriverWait(self.driver, CONFIG['ELEMENT_WAIT_TIMEOUT']).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            two_step_locators = [
                (By.XPATH, "//*[self::button or self::a or @role='button'][contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '2-step verification')]"),
                (By.XPATH, "//*[self::button or self::a or @role='button'][contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'two-step verification')]"),
                (By.XPATH, "//*[self::button or self::a or @role='button'][contains(., 'Xác minh 2 bước') or contains(., 'Xác thực 2 bước')]"),
            ]
            self.click_first_visible(two_step_locators, 20, "Xác minh 2 bước")

            authenticator_locators = [
                (By.XPATH, "//*[self::button or self::label or @role='button' or @role='checkbox'][contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'authenticator')]"),
                (By.XPATH, "//*[self::button or self::label or @role='button' or @role='checkbox'][contains(., 'Ứng dụng xác thực')]"),
            ]
            if not self.click_first_visible(authenticator_locators, 20, "Authenticator app"):
                return None

            next_locators = [
                (By.XPATH, "//button[normalize-space()='Next' or normalize-space()='Continue' or normalize-space()='Tiếp' or normalize-space()='Tiếp tục']"),
                (By.CSS_SELECTOR, "button[type='submit']"),
            ]
            self.click_first_visible(next_locators, 8, "nút tiếp tục")

            deadline = time.monotonic() + timeout
            secret = None
            while time.monotonic() < deadline and not secret:
                # Ưu tiên secret dạng chữ nếu TikTok hiển thị nút copy/manual key.
                candidates = self.driver.find_elements(
                    By.XPATH,
                    "//*[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'SETUP KEY') or contains(., 'Khóa thiết lập') or contains(., 'Enter this key')]",
                )
                for candidate in candidates:
                    text = candidate.text or candidate.get_attribute('textContent') or ''
                    match = re.search(r'\b([A-Z2-7](?:[ A-Z2-7]{14,}[A-Z2-7]))\b', text.upper())
                    if match:
                        possible = re.sub(r'\s+', '', match.group(1))
                        if re.fullmatch(r'[A-Z2-7]{16,}', possible):
                            secret = possible
                            break

                if not secret:
                    qr_elements = self.driver.find_elements(
                        By.CSS_SELECTOR, "canvas, img[src*='qr'], [data-e2e*='qr'] canvas, [data-e2e*='qr'] img"
                    )
                    for element in qr_elements:
                        if not element.is_displayed():
                            continue
                        value = self.decode_qr_element(element)
                        if not value or not value.lower().startswith('otpauth://'):
                            continue
                        query = parse_qs(urlparse(value).query)
                        possible = (query.get('secret') or [''])[0].replace(' ', '').upper()
                        if re.fullmatch(r'[A-Z2-7]{16,}', possible):
                            secret = possible
                            break
                if not secret:
                    time.sleep(1)

            if not secret:
                self.log("Không đọc được khóa Authenticator thật từ trang TikTok.", "error")
                return None

            code = generate_totp(secret)
            code_inputs = self.driver.find_elements(
                By.CSS_SELECTOR,
                "input[autocomplete='one-time-code'], input[inputmode='numeric'], input[placeholder*='code' i]",
            )
            visible_inputs = [item for item in code_inputs if item.is_displayed() and item.is_enabled()]
            if not visible_inputs:
                self.log("Không tìm thấy ô nhập mã Authenticator.", "error")
                return None
            visible_inputs[-1].clear()
            visible_inputs[-1].send_keys(code)

            confirm_locators = [
                (By.XPATH, "//button[normalize-space()='Confirm' or normalize-space()='Verify' or normalize-space()='Turn on' or normalize-space()='Xác nhận' or normalize-space()='Xác minh' or normalize-space()='Bật']"),
                (By.CSS_SELECTOR, "button[type='submit']"),
            ]
            if not self.click_first_visible(confirm_locators, 15, "xác nhận Authenticator"):
                return None

            success_deadline = time.monotonic() + 25
            success_phrases = (
                'authenticator app is on', 'authenticator enabled', 'successfully enabled',
                'đã bật ứng dụng xác thực', 'đã bật trình xác thực', 'thiết lập thành công',
            )
            while time.monotonic() < success_deadline:
                body = ' '.join(self.driver.find_element(By.TAG_NAME, 'body').text.lower().split())
                if any(phrase in body for phrase in success_phrases):
                    self.log("TikTok đã xác nhận bật Authenticator thành công.")
                    return secret
                time.sleep(1)
            self.log("Đã gửi mã nhưng chưa thấy TikTok xác nhận bật Authenticator.", "error")
            return None
        except Exception as exc:
            self.log(f"Không thể bật Authenticator: {exc}", "error")
            return None

    def verify_login_credentials(self, email: str, password: str, timeout=45) -> bool:
        """Xóa phiên hiện tại và đăng nhập lại để xác nhận tài khoản tồn tại thật.

        Tài khoản chỉ được lưu khi TikTok tạo session đăng nhập mới. Việc đổi URL
        đơn thuần không được xem là thành công vì có thể là trang lỗi/QR/CAPTCHA.
        """
        self.log(f"Kiểm tra lại tài khoản bằng đăng nhập mới: {email}")
        try:
            self.driver.delete_all_cookies()
            try:
                self.driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
            except WebDriverException:
                pass

            self.driver.get("https://www.tiktok.com/login/phone-or-email/email")

            username = WebDriverWait(self.driver, CONFIG['ELEMENT_WAIT_TIMEOUT']).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    "input[name='username'], input[name='email'], "
                    "input[autocomplete='username'], input[type='text']"))
            )
            password_input = WebDriverWait(self.driver, CONFIG['ELEMENT_WAIT_TIMEOUT']).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
            )
            username.clear()
            username.send_keys(email)
            password_input.clear()
            password_input.send_keys(password)

            login_button = WebDriverWait(self.driver, CONFIG['ELEMENT_WAIT_TIMEOUT']).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR,
                    "button[data-e2e='login-button'], button[type='submit']"))
            )
            login_button.click()

            failure_phrases = (
                "account doesn't exist", "account does not exist", "couldn't log in",
                "incorrect password", "wrong password", "tài khoản không tồn tại",
                "mật khẩu không chính xác", "quá nhiều lần thử", "too many attempts",
            )
            security_phrases = (
                "scan the qr code", "continue on your phone", "verify to continue",
                "drag the slider", "quét mã qr", "tiếp tục trên điện thoại",
                "xác minh để tiếp tục",
            )
            account_locators = [
                (By.CSS_SELECTOR, "[data-e2e='profile-icon']"),
                (By.CSS_SELECTOR, "[data-e2e='nav-profile']"),
                (By.CSS_SELECTOR, "[data-e2e='nav-upload']"),
            ]
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                page_text = ""
                try:
                    page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
                except (NoSuchElementException, StaleElementReferenceException):
                    pass

                if any(phrase in page_text for phrase in failure_phrases):
                    self.log("Đăng nhập kiểm tra thất bại: TikTok không chấp nhận tài khoản/mật khẩu.", "error")
                    return False

                if any(phrase in page_text for phrase in security_phrases):
                    self.log("Đăng nhập kiểm tra đang bị chặn bởi bước xác minh bảo mật/QR.", "warning")
                    return False

                has_session_cookie = any(
                    cookie.get('name', '').lower() in ('sessionid', 'sessionid_ss')
                    and cookie.get('value')
                    for cookie in self.driver.get_cookies()
                )
                has_visible_account_ui = any(
                    any(element.is_displayed() for element in self.driver.find_elements(*locator))
                    for locator in account_locators
                )
                if has_session_cookie and has_visible_account_ui:
                    self.log("Đăng nhập lại thành công; tài khoản đã được TikTok xác nhận.")
                    return True

                time.sleep(1)

            self.log("Hết thời gian chờ xác nhận đăng nhập lại; không lưu tài khoản.", "error")
            try:
                screenshot = os.path.join(log_dir, f"login_verify_failed_worker_{self.worker_id}.png")
                self.driver.save_screenshot(screenshot)
                self.log(f"Đã lưu ảnh lỗi đăng nhập kiểm tra: {screenshot}", "warning")
            except Exception:
                pass
            return False
        except Exception as e:
            self.log(f"Lỗi khi đăng nhập kiểm tra: {str(e)}", "error")
            return False
    
    def register_tiktok(self) -> bool:
        """Đăng ký tài khoản TikTok - Cập nhật từ logic loginfb copy 2.py"""
        try:
            proxy = None
            if self.use_proxy_global:
                proxy = self.get_proxy()
                if not proxy:
                    self.log("Không có proxy hoạt động để sử dụng cho lần thử này.", "warning")
                    return False

            self.driver = self.setup_driver(proxy)
            
            if not self.driver:
                self.log("Không thể thiết lập trình duyệt", "error")
                return False
            
            try:
                # Tạo tài khoản email trước khi mở trang TikTok
                self.log("Đang chuẩn bị hộp thư nhận OTP...")
                if not self.mail_manager.create_account():
                    self.log("Không thể kết nối hộp thư Outlook/Hotmail", "error")
                    return False
                
                email_info = self.mail_manager.get_email_info()
                self.log(f"Đã chọn hộp thư: {email_info['email']}")
                
                # Truy cập trang đăng ký TikTok
                self.log("Truy cập trang đăng ký TikTok...")
                self.driver.get("https://www.tiktok.com/signup")
                time.sleep(3)
                
                # Kiểm tra URL để xác nhận proxy hoạt động
                current_url = self.driver.current_url
                if "tiktok.com" not in current_url:
                    self.log(f"URL không đúng sau khi truy cập: {current_url}. Có thể bị chặn.", "warning")
                    if self.proxy_used:
                        log_proxy_usage(self.proxy_used, success=False, worker_id=self.worker_id)
                        mark_proxy_as_failed(self.proxy_used, "Chuyển hướng ngoài mong muốn")
                    return False
                
                # Mở luồng phone/email, sau đó chủ động chọn email. Không dùng
                # XPath tuyệt đối vì TikTok thường xuyên đổi cấu trúc trang.
                self.log("Mở lựa chọn 'Use phone or email'...")
                signup_method_locators = [
                    (By.CSS_SELECTOR, "a[href*='/signup/phone-or-email']"),
                    (By.CSS_SELECTOR, "[data-e2e*='phone-email-sign-up']"),
                    (By.CSS_SELECTOR, "[data-e2e*='phone-email-signup']"),
                    (By.XPATH, "//*[self::a or self::button or @role='button'][contains(normalize-space(.), 'Use phone or email')]"),
                    (By.XPATH, "//*[self::a or self::button or @role='button'][contains(normalize-space(.), 'Sử dụng số điện thoại hoặc email')]"),
                    (By.XPATH, "//*[self::a or self::button or @role='button'][contains(normalize-space(.), 'Dùng số điện thoại hoặc email')]"),
                ]
                if not self.click_first_visible(
                    signup_method_locators, 12, "lựa chọn 'Use phone or email'"
                ):
                    self.log("Không thấy lựa chọn phone/email; mở trang đăng ký email trực tiếp.", "warning")
                    self.driver.get("https://www.tiktok.com/signup/phone-or-email")

                # Chọn tháng
                self.log("Chọn tháng...")
                time.sleep(3)
                if not self.wait_and_click((By.XPATH, '/html/body/div[1]/div/div[2]/div[1]/form/div[2]/div[1]/div[1]')):
                    return False
                if not self.wait_and_click((By.ID, 'Month-options-item-8')):
                    return False
                
                # Chọn ngày
                self.log("Chọn ngày...")
                if not self.wait_and_click((By.XPATH, '/html/body/div[1]/div/div[2]/div[1]/form/div[2]/div[2]/div[1]')):
                    return False
                if not self.wait_and_click((By.ID, 'Day-options-item-16')):
                    return False
                
                # Chọn năm
                self.log("Chọn năm...")
                if not self.wait_and_click((By.XPATH, '/html/body/div[1]/div/div[2]/div[1]/form/div[2]/div[3]/div[1]')):
                    return False
                
                try:
                    year_element_locator = (By.ID, 'Year-options-item-31')
                    year_element = WebDriverWait(self.driver, CONFIG['ELEMENT_WAIT_TIMEOUT']).until(
                        EC.presence_of_element_located(year_element_locator)
                    )
                    self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", year_element)
                    time.sleep(2)
                    year_element.click()
                    self.log("Đã chọn năm sinh.")
                except Exception as e:
                    self.log(f"Không thể chọn năm sinh: {str(e)}", "error")
                    return False
                
                time.sleep(2)
                
                # Một số giao diện hỏi ngày sinh trước rồi mới hiện lựa chọn
                # email; giao diện khác đã ở sẵn form email.
                if not any(
                    element.is_displayed()
                    for element in self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "input[name='email'], input[type='email'], input[autocomplete='email']",
                    )
                ):
                    self.log("Chuyển từ ngày sinh sang form email/password...")
                    if not self.switch_signup_to_email():
                        return False

                    time.sleep(2)
                
                # Điền email và mật khẩu
                self.log(f"Điền email: {email_info['email']}...")
                if not self.wait_and_send_keys(
                    (By.CSS_SELECTOR, "input[name='email'], input[type='email'], input[autocomplete='email']"),
                    email_info['email'],
                    description="ô email đăng ký",
                ):
                    return False
                
                self.log(f"Điền mật khẩu TikTok...")
                if not self.wait_and_send_keys((By.XPATH, '/html/body/div[1]/div/div[2]/div[1]/form/div[6]/div/input'), self.tiktok_password):
                    return False
                
                time.sleep(2)
                
                # Click nút Send code
                self.log("Click nút 'Send code'...")
                try:
                    old_message_ids = self.mail_manager.get_message_ids()
                    send_code_btn = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[@data-e2e='send-code-button']"))
                    )
                    send_code_btn.click()
                    self.log("Đã click vào nút 'Send code'")
                except Exception as e:
                    self.log(f"Không thể click nút 'Send code': {str(e)}", "error")
                    return False
                
                self.log("Đợi email xác minh từ TikTok...")
                verification_code = self.wait_for_email_otp(old_message_ids)
                
                if not verification_code:
                    self.log("Không thể lấy mã xác minh từ email sau nhiều lần thử.", "error")
                    return False
                
                self.log(f"Đã nhận mã xác minh: {verification_code}")
                
                # Điền mã xác minh
                if not self.wait_and_send_keys((By.XPATH, '/html/body/div[1]/div/div[2]/div[1]/form/div[7]/div[1]/div/input'), verification_code):
                    return False
                
                time.sleep(2)
                
                # Click vào phần form để kích hoạt như trong loginfb copy 2.py
                try:
                    self.wait_and_click((By.XPATH, '/html/body/div[1]/div/div[2]/div[1]/form/div[3]'), 
                                      timeout=5, description="click vào vùng form để kích hoạt")
                    self.log("Đã click vào vùng form để kích hoạt.")
                except Exception as e:
                    self.log(f"Không thể click vào vùng form để kích hoạt: {str(e)}", "warning")
                
                time.sleep(10)
                
                # Click nút Sign up cuối cùng
                self.log("Click nút 'Sign up' cuối cùng...")
                if not self.confirm_real_account_creation(email_info['email']):
                    self.log("Người dùng chưa xác nhận tạo tài khoản thật; dừng an toàn.", "warning")
                    return False
                if not self.click_signup_button():
                    return False
                
                # Đợi quá trình đăng ký hoàn tất
                self.log("Đợi quá trình đăng ký hoàn tất...")
                post_signup_confirmed = self.handle_post_signup()
                if self.post_signup_state in ('security_qr_required', 'security_qr_timeout'):
                    self.log(
                        "Checkpoint QR không thể bỏ qua bằng nút chính thức; "
                        "không dùng luồng khác để giả lập xác minh thiết bị.",
                        "error",
                    )
                    return False

                if self.post_signup_state == 'signup_rejected':
                    self.log(
                        "Form đăng ký chưa được TikTok chấp nhận; không thực hiện "
                        "đăng nhập kiểm tra cho tài khoản chưa tồn tại.",
                        "warning",
                    )
                    return False

                if not post_signup_confirmed:
                    self.log(
                        "Chưa xác nhận được phiên ngay sau đăng ký; sẽ đăng nhập lại để kiểm tra thực tế.",
                        "warning",
                    )
                    if not self.verify_login_credentials(email_info['email'], self.tiktok_password):
                        self.log("Tài khoản không vượt qua bước đăng nhập kiểm tra nên sẽ không được lưu.", "error")
                        return False
                else:
                    self.log("Phiên đăng ký đã được xác nhận; không xóa cookie để đăng nhập lại.")

                self.log('Đăng ký và đăng nhập kiểm tra thành công')
                if self.desired_username and not self.set_username(self.desired_username):
                    self.log("Tài khoản đã tạo nhưng không đặt được username yêu cầu; không lưu kết quả.", "error")
                    return False
                two_factor_secret = self.enable_authenticator_2fa()
                if not two_factor_secret:
                    self.log(
                        "Tài khoản đã đăng ký nhưng chưa bật/xác nhận được Authenticator; "
                        "không ghi kết quả chưa hoàn chỉnh vào accounts.txt.",
                        "error",
                    )
                    return False

                username = self.current_username(email_info['email'])
                if not self.save_account(
                    username, email_info['password'], self.tiktok_password,
                    two_factor_secret,
                ):
                    return False

                if self.proxy_used:
                    log_proxy_usage(self.proxy_used, success=True, worker_id=self.worker_id)
                    self.proxy_queue.put(self.proxy_used)

                return True
                    
            except WebDriverException as e:
                self.log(f"Lỗi WebDriver trong quá trình đăng ký: {str(e)}", "error")
                return False
            except Exception as e:
                self.log(f'Lỗi không mong muốn trong quá trình đăng ký: {str(e)}', "error")
                return False
            finally:
                self.close_driver()
                    
        except Exception as e:
            self.log(f'Lỗi tổng quát: {str(e)}', "error")
            if self.proxy_used:
                log_proxy_usage(self.proxy_used, success=False, worker_id=self.worker_id)

            self.close_driver()

            return False
            
    def run(self) -> bool:
        """Chạy worker để đăng ký tài khoản"""
        self.log(f"Worker-{self.worker_id} bắt đầu chạy")
        
        for attempt in range(self.max_retries):
            self.log(f"Lần thử {attempt+1}/{self.max_retries}")
            if self.register_tiktok():
                self.log(f"Đăng ký thành công sau {attempt+1} lần thử")
                return True
            else:
                # Proxy đã vượt qua kiểm tra mạng vẫn có thể dùng lại nếu flow đăng ký lỗi.
                # Các proxy lỗi 407/socket không gán vào self.proxy_used nên không bị đưa lại.
                if self.proxy_used:
                    self.proxy_queue.put(self.proxy_used)
                    self.log(f"Đã trả proxy {proxy_display(self.proxy_used)} về hàng đợi để thử lại.")
                    self.proxy_used = None
                if attempt + 1 < self.max_retries:
                    self.log(f"Lần thử {attempt+1} thất bại. Thử lại...", "warning")
                    random_delay()
                
        self.log(
            f"Đã thất bại sau {self.max_retries} lần thử cho worker-{self.worker_id}.",
            "error",
        )
        return False

class OutlookMailManager:
    """Đọc OTP từ một hộp thư Outlook/Hotmail có sẵn qua Microsoft Graph.

    Không lưu mật khẩu Microsoft. Lần đầu sử dụng, MSAL hiển thị device-code
    để chủ hộp thư đăng nhập và hoàn tất 2FA trên trang chính thức Microsoft.
    """

    GRAPH_BASE_URL = 'https://graph.microsoft.com/v1.0'
    SCOPES = ['Mail.Read', 'User.Read']

    def __init__(self):
        self.email = None
        self.password = ''
        self.client_id = None
        self._app = None
        self._cache = msal.SerializableTokenCache()
        self._cache_path = None

    def create_account(self) -> bool:
        """Chọn một mailbox đã cấu hình; không tự tạo tài khoản Microsoft."""
        with outlook_lock:
            if outlook_accounts_queue.empty():
                for account in load_outlook_accounts():
                    outlook_accounts_queue.put(account)
            if outlook_accounts_queue.empty():
                logger.error(
                    f"Chưa có Outlook. Thêm mỗi dòng email|client_id vào "
                    f"{OUTLOOK_ACCOUNTS_FILE}."
                )
                return False
            self.email, self.client_id = outlook_accounts_queue.get()

        os.makedirs(OUTLOOK_TOKEN_DIR, exist_ok=True)
        cache_name = hashlib.sha256(self.email.lower().encode('utf-8')).hexdigest() + '.json'
        self._cache_path = os.path.join(OUTLOOK_TOKEN_DIR, cache_name)
        if os.path.exists(self._cache_path):
            try:
                with open(self._cache_path, 'r', encoding='utf-8') as file:
                    self._cache.deserialize(file.read())
            except Exception as exc:
                logger.warning(f"Không đọc được token cache Outlook: {exc}")

        self._app = msal.PublicClientApplication(
            self.client_id,
            authority='https://login.microsoftonline.com/consumers',
            token_cache=self._cache,
        )
        return bool(self._get_access_token(interactive=True))

    def _save_cache(self):
        if self._cache.has_state_changed and self._cache_path:
            with open(self._cache_path, 'w', encoding='utf-8') as file:
                file.write(self._cache.serialize())
            try:
                os.chmod(self._cache_path, 0o600)
            except OSError:
                pass

    def _get_access_token(self, interactive=False) -> Optional[str]:
        if not self._app:
            return None
        accounts = self._app.get_accounts(username=self.email)
        result = self._app.acquire_token_silent(self.SCOPES, account=accounts[0]) if accounts else None
        if not result and interactive:
            flow = self._app.initiate_device_flow(scopes=self.SCOPES)
            if 'user_code' not in flow:
                logger.error(f"Không tạo được Microsoft device flow: {flow}")
                return None
            logger.warning(flow.get('message', 'Hãy đăng nhập Microsoft để cấp quyền đọc OTP.'))
            result = self._app.acquire_token_by_device_flow(flow)
        self._save_cache()
        if result and result.get('access_token'):
            return result['access_token']
        if result:
            logger.error(
                "Đăng nhập Outlook thất bại: "
                f"{result.get('error_description') or result.get('error')}"
            )
        return None

    def _headers(self) -> Optional[dict]:
        token = self._get_access_token(interactive=True)
        return {'Authorization': f'Bearer {token}'} if token else None

    def get_message_ids(self) -> set:
        headers = self._headers()
        if not headers:
            return set()
        try:
            response = requests.get(
                f"{self.GRAPH_BASE_URL}/me/messages",
                headers=headers,
                params={'$select': 'id', '$top': '25', '$orderby': 'receivedDateTime desc'},
                timeout=15,
            )
            if response.status_code == 200:
                return {item['id'] for item in response.json().get('value', []) if item.get('id')}
            logger.warning(f"Microsoft Graph trả về HTTP {response.status_code}")
        except requests.RequestException as exc:
            logger.warning(f"Không lấy được danh sách Outlook: {exc}")
        return set()

    def get_verification_code(
        self, max_attempts=10, delay=5, exclude_message_ids=None, log_final_error=True
    ) -> Optional[str]:
        excluded_ids = set(exclude_message_ids or [])
        for attempt in range(max_attempts):
            headers = self._headers()
            if not headers:
                return None
            try:
                response = requests.get(
                    f"{self.GRAPH_BASE_URL}/me/messages",
                    headers=headers,
                    params={
                        '$select': 'id,subject,body,from,receivedDateTime',
                        '$top': '25',
                        '$orderby': 'receivedDateTime desc',
                    },
                    timeout=15,
                )
                if response.status_code == 200:
                    for message in response.json().get('value', []):
                        if message.get('id') in excluded_ids:
                            continue
                        sender = (
                            message.get('from', {}).get('emailAddress', {}).get('address', '')
                        ).lower()
                        subject = message.get('subject', '')
                        body = html.unescape(message.get('body', {}).get('content', ''))
                        content = re.sub(r'<[^>]+>', ' ', f"{subject} {body}")
                        if 'tiktok' not in sender and 'tiktok' not in content.lower():
                            continue
                        match = re.search(r'(?<!\d)(\d{6})(?!\d)', content)
                        if match:
                            logger.info(f"Đã lấy OTP TikTok từ Outlook: {self.email}")
                            return match.group(1)
                elif response.status_code == 401:
                    logger.warning("Token Outlook hết hạn; đang yêu cầu đăng nhập lại.")
                else:
                    logger.warning(f"Microsoft Graph trả về HTTP {response.status_code}")
            except requests.RequestException as exc:
                logger.warning(f"Lỗi khi đọc Outlook: {exc}")
            if attempt + 1 < max_attempts:
                time.sleep(delay)
        if log_final_error:
            logger.error("Không tìm thấy OTP TikTok mới trong Outlook.")
        return None

    def get_email_info(self):
        return {'email': self.email, 'password': ''}


class ManualEmailManager:
    """Dùng bất kỳ hộp thư người dùng sở hữu và nhập OTP thủ công."""

    def __init__(self, email: str):
        self.email = email.strip()
        self.password = ''
        self._last_code = None

    def create_account(self) -> bool:
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', self.email):
            logger.error("Địa chỉ email không hợp lệ.")
            return False
        logger.info(f"Sẽ nhận OTP thủ công từ hộp thư: {self.email}")
        return True

    def get_message_ids(self) -> set:
        return set()

    def get_verification_code(
        self, max_attempts=1, delay=0, exclude_message_ids=None, log_final_error=True
    ) -> Optional[str]:
        del max_attempts, delay, exclude_message_ids, log_final_error
        try:
            code = input(
                f"\nMở hộp thư {self.email}, lấy mã TikTok 6 số và nhập vào đây: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not re.fullmatch(r'\d{6}', code):
            logger.error("OTP phải gồm đúng 6 chữ số.")
            return None
        self._last_code = code
        return code

    def get_email_info(self):
        return {'email': self.email, 'password': ''}


class TempMailManager:
    """Lớp quản lý email tạm thời từ mail.tm"""
    
    def __init__(self):
        self.base_url = "https://api.mail.tm"
        self.email = None
        self.password = None
        self.token = None
        self.domain = None
        
    def get_domain(self) -> Optional[str]:
        """Lấy domain hiện tại từ mail.tm"""
        headers = {
            'Referer': 'https://mail.tm/',
            'User-Agent': get_random_user_agent(),
        }
        try:
            response = requests.get(f'{self.base_url}/domains', headers=headers, timeout=10)
            if response.status_code == 200:
                domains_data = response.json()
                if 'hydra:member' in domains_data and domains_data['hydra:member']:
                    self.domain = domains_data['hydra:member'][0]['domain']
                    logger.info(f"Đã lấy domain: {self.domain}")
                    return self.domain
                else:
                    logger.error("Không tìm thấy domain trong phản hồi API mail.tm")
            else:
                logger.error(f"Lỗi khi lấy domain từ mail.tm: {response.status_code} - {response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Lỗi kết nối đến mail.tm khi lấy domain: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Lỗi không xác định khi lấy domain từ mail.tm: {str(e)}")
            return None
            
    def create_account(self) -> bool:
        """Tạo tài khoản email tạm thời"""
        if not self.domain:
            self.domain = self.get_domain()
            if not self.domain:
                logger.error("Không thể lấy domain từ mail.tm để tạo tài khoản email.")
                return False
                
        try:
            domain_names_prefixes = get_domain_names()
            
            if not domain_names_prefixes:
                logger.error("Không có tên miền nào trong file domain_names.txt. Vui lòng thêm tên miền vào.")
                return False

            email_password = f"{random.choice(get_passwords())}{random.randint(10000, 99999)}"
            
            headers = {
                'Referer': 'https://mail.tm/',
                'Content-Type': 'application/json',
                'User-Agent': get_random_user_agent(),
            }
            
            for attempt in range(1, 6):
                raw_prefix = random.choice(domain_names_prefixes)
                # mail.tm chỉ chấp nhận local-part ASCII đơn giản; loại bỏ ký tự lạ.
                safe_prefix = re.sub(r'[^a-z0-9]', '', raw_prefix.lower()) or 'user'
                username = f"{safe_prefix}{random.randint(10000, 99999)}"
                email = f"{username}@{self.domain}"
                response = requests.post(
                    f'{self.base_url}/accounts',
                    headers=headers,
                    json={'address': email, 'password': email_password},
                    timeout=15,
                )

                if response.status_code == 201:
                    account_data = response.json()
                    if 'address' in account_data and 'id' in account_data:
                        self.email = email
                        self.password = email_password
                        # Mỗi lần thử dùng một hộp thư mới; token cũ thuộc hộp thư trước.
                        self.token = None
                        logger.info(f"Đã tạo tài khoản email: {email}")
                        return True

                if response.status_code in (409, 422):
                    logger.warning(
                        f"mail.tm từ chối tên email lần {attempt}/5; đang thử tên khác."
                    )
                    continue

                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After', '').strip()
                    wait_seconds = int(retry_after) if retry_after.isdigit() else min(5 * attempt, 20)
                    logger.warning(
                        f"mail.tm giới hạn yêu cầu (429); chờ {wait_seconds} giây "
                        f"rồi thử lại ({attempt}/5)."
                    )
                    time.sleep(wait_seconds)
                    continue

                logger.error(
                    f"Lỗi khi tạo tài khoản email tạm thời: "
                    f"{response.status_code} - {response.text}"
                )
                return False

            logger.error("mail.tm từ chối 5 tên email liên tiếp.")
            
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Lỗi kết nối đến mail.tm khi tạo tài khoản: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Lỗi không xác định khi tạo tài khoản email tạm thời: {str(e)}")
            return False
            
    def login(self) -> bool:
        """Đăng nhập và lấy token"""
        if not self.email or not self.password:
            logger.error("Chưa có thông tin tài khoản email để đăng nhập.")
            return False
            
        try:
            headers = {
                "Content-Type": "application/json",
                'User-Agent': get_random_user_agent(),
            }
            
            payload = {
                "address": self.email,
                "password": self.password,
            }
            
            response = requests.post(
                f"{self.base_url}/token", 
                headers=headers, 
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.token = token_data.get("token")
                if self.token:
                    logger.info(f"Đăng nhập email thành công, đã lấy token.")
                    return True
                else:
                    logger.error("Không tìm thấy token trong phản hồi đăng nhập email.")
                    return False
            else:
                logger.error(f"Lỗi khi đăng nhập email: {response.status_code} - {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Lỗi kết nối đến mail.tm khi đăng nhập: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Lỗi không xác định khi đăng nhập email: {str(e)}")
            return False
            
    def get_message_ids(self) -> set:
        """Lấy ID email hiện có để có thể bỏ qua OTP cũ."""
        if not self.token and not self.login():
            return set()
        try:
            response = requests.get(
                f"{self.base_url}/messages?page=1",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    'User-Agent': get_random_user_agent(),
                },
                timeout=10,
            )
            if response.status_code == 200:
                return {
                    message.get('id')
                    for message in response.json().get('hydra:member', [])
                    if message.get('id')
                }
        except Exception as e:
            logger.warning(f"Không thể lấy danh sách email hiện tại: {str(e)}")
        return set()

    def get_verification_code(
        self,
        max_attempts=10,
        delay=5,
        exclude_message_ids=None,
        log_final_error=True,
    ) -> Optional[str]:
        """Lấy mã xác minh từ email - Cải tiến từ loginfb copy 2.py"""
        excluded_ids = set(exclude_message_ids or [])
        if not self.token:
            if not self.login():
                logger.error("Không thể đăng nhập để lấy token email.")
                return None
        
        for attempt in range(max_attempts):
            logger.info(f"Lấy mã xác minh, lần thử {attempt+1}/{max_attempts}...")
            
            try:
                headers = {
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    'User-Agent': get_random_user_agent(),
                }
                
                # Lấy danh sách tin nhắn
                response = requests.get(
                    f"{self.base_url}/messages?page=1", 
                    headers=headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    messages_data = response.json()
                    messages = messages_data.get("hydra:member", [])
                    
                    new_messages = [
                        message for message in messages
                        if message.get('id') and message.get('id') not in excluded_ids
                    ]
                    if new_messages:
                        # Dùng email mới nhất chưa tồn tại trước lúc yêu cầu OTP.
                        latest_message = new_messages[0]
                        message_id = latest_message["id"]
                        
                        # Lấy chi tiết tin nhắn
                        message_url = f"{self.base_url}/messages/{message_id}"
                        message_response = requests.get(message_url, headers=headers, timeout=10)
                        
                        if message_response.status_code == 200:
                            message_details = message_response.json()
                            message_text = message_details.get("text", "") or ""
                            if isinstance(message_text, list):
                                message_text = ' '.join(str(part) for part in message_text)
                            html_parts = message_details.get("html", []) or []
                            if isinstance(html_parts, str):
                                html_parts = [html_parts]
                            message_text += ' ' + ' '.join(str(part) for part in html_parts)
                            
                            # Trích xuất mã xác minh bằng regex
                            match = re.search(r'\b\d{6}\b', message_text)
                            if match:
                                verification_code = match.group(0)
                                logger.info(f"Đã lấy mã xác minh: {verification_code}")
                                return verification_code
                            else:
                                logger.warning("Không tìm thấy mã xác minh (6 chữ số) trong nội dung tin nhắn.")
                        else:
                            logger.warning(f"Lỗi khi lấy chi tiết tin nhắn: {message_response.status_code}")
                    else:
                        logger.warning("Chưa có email OTP mới. Đang chờ...")
                else:
                    logger.warning(f"Lỗi khi lấy danh sách tin nhắn: {response.status_code}")
            
            except Exception as e:
                logger.error(f"Lỗi khi lấy mã xác minh: {str(e)}")
            
            # Đợi trước khi thử lại
            time.sleep(delay)
            
        if log_final_error:
            logger.error(f"Không thể lấy mã xác minh sau {max_attempts} lần thử.")
        return None
        
    def get_email_info(self):
        """Trả về thông tin tài khoản email"""
        return {
            'email': self.email,
            'password': self.password
        }

# Hàm chính của chương trình
def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Đăng ký TikTok bằng hộp thư Outlook do bạn sở hữu."
    )
    parser.add_argument('--threads', type=int, help='Số luồng (mặc định hỏi khi chạy)')
    parser.add_argument('--accounts', type=int, help='Số tài khoản (mặc định hỏi khi chạy)')
    parser.add_argument(
        '--email', help='Email bạn sở hữu; OTP sẽ được nhập thủ công trong Terminal'
    )
    parser.add_argument(
        '--temp-mail', action='store_true',
        help='Tạo đúng một hộp thư mail.tm để đăng ký đúng một tài khoản TikTok',
    )
    parser.add_argument('--username', help='Username TikTok muốn đặt sau khi đăng ký')
    parser.add_argument('--password', help='Mật khẩu TikTok muốn dùng')
    parser.add_argument(
        '--qr-policy', choices=('skip', 'wait'), default='wait',
        help=(
            "Cách xử lý QR sau đăng ký: mặc định 'wait' để giữ nguyên phiên và "
            "chờ xác nhận thủ công trên ứng dụng; 'skip' chỉ bỏ qua bước tùy chọn "
            "và dừng nếu QR là bắt buộc"
        ),
    )
    parser.add_argument(
        '--check', action='store_true',
        help='Chỉ kiểm tra cấu hình, không mở trình duyệt hoặc đăng ký',
    )
    parser.add_argument(
        '--retries', type=int,
        help='Số lần thử cho mỗi tài khoản (mặc định: email tạm 3, email khác 3)',
    )
    return parser.parse_args(argv)


def preflight_check(
    manual_email: Optional[str] = None,
    use_temp_mail: bool = False,
) -> bool:
    """Kiểm tra các điều kiện bắt buộc trước khi mở Chrome."""
    issues = []
    mailboxes = load_outlook_accounts()
    if manual_email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', manual_email):
        issues.append("Email truyền qua --email không hợp lệ")
    if manual_email and use_temp_mail:
        issues.append("Không thể dùng đồng thời --email và --temp-mail")
    if not manual_email and not use_temp_mail and not mailboxes:
        issues.append(
            f"Thiếu {OUTLOOK_ACCOUNTS_FILE}: thêm email@outlook.com|MICROSOFT_APPLICATION_CLIENT_ID"
        )
    if not chrome_path:
        issues.append("Không tìm thấy Google Chrome/Chromium trên máy")
    if issues:
        for issue in issues:
            logger.error(f"Kiểm tra cấu hình: {issue}")
        return False
    email_mode = (
        "mail.tm (một tài khoản)" if use_temp_mail
        else manual_email or f"{len(mailboxes)} hộp thư Outlook"
    )
    logger.info(f"Kiểm tra cấu hình OK: {email_mode}, Chrome={chrome_path}")
    return True


def main(argv=None):
    """Hàm chính của chương trình"""
    args = parse_args(argv)
    create_data_files()

    logger.info("=== REG TIKTOK VỚI HỖ TRỢ PROXY VÀ ĐA LUỒNG FREE ===")
    logger.info("- Proxy sẽ được đọc từ file data/proxy.txt (hỗ trợ ip:port và ip:port:user:pass)")
    logger.info("- Mặc định dùng User-Agent gốc của Chrome để tránh lệch phiên bản")
    logger.info("- Tên miền email sẽ được đọc từ file data/domain_names.txt và kết hợp với số ngẫu nhiên.")
    logger.info("- Nếu file không tồn tại hoặc không có proxy nào, chương trình sẽ chạy không dùng proxy")
    logger.info("- Proxy không hoạt động sẽ được đánh dấu trong file data/proxy.txt")
    logger.info("- Thống kê proxy được lưu trong thư mục logs/proxy_log.txt")
    logger.info("- Tài khoản được tạo sẽ lưu trong file accounts.txt (ngang hàng với script chính)")
    logger.info("- Chương trình sẽ chạy đa luồng để đăng ký nhiều tài khoản cùng lúc")
    logger.info(f"- Cửa sổ Chrome sẽ được đặt kích thước {CONFIG['BROWSER_WIDTH']}x{CONFIG['BROWSER_HEIGHT']} để dễ quan sát.")
    logger.info("- TÁC GIẢ: Hồ Hiệp x HVHTOOL")
    logger.info("Github: https://github.com/hiep-py/reg-acc-tik-tok")
    logger.info("Youtube: https://www.youtube.com/@hiep-py")
    logger.info("Youtube: https://www.youtube.com/@HVHTOOL")
    logger.info("- PHIÊN BẢN CẢI TIẾN: 2.19")
    logger.info("====================================\n")

    if not os.path.exists('logs'):
        os.makedirs('logs')

    if not preflight_check(args.email, args.temp_mail):
        logger.error("Chưa đủ cấu hình để tạo tài khoản. Không có thay đổi nào được gửi lên TikTok.")
        return 2
    if args.check:
        return 0

    proxy_list = get_proxies()

    proxy_queue = queue.Queue()
    use_proxy_global = False # Biến cờ mới để kiểm soát việc sử dụng proxy
    if proxy_list:
        random.shuffle(proxy_list)
        for proxy in proxy_list:
            proxy_queue.put(proxy)
        logger.info(f"Đã đưa {proxy_queue.qsize()} proxy vào hàng đợi.")
        use_proxy_global = True # Đặt cờ là True nếu có proxy
    else:
        logger.warning("Không tìm thấy proxy nào. Chương trình sẽ chạy không sử dụng proxy.")
        use_proxy_global = False # Đặt cờ là False nếu không có proxy

    try:
        num_threads = args.threads if args.threads is not None else int(input("Nhập số lượng luồng (mặc định là 1): ") or "1")
        if num_threads < 1:
            num_threads = 1
    except ValueError:
        logger.warning("Giá trị không hợp lệ, sử dụng mặc định là 1 luồng")
        num_threads = 1

    try:
        num_accounts = args.accounts if args.accounts is not None else int(input("Nhập số lượng tài khoản cần tạo (mặc định là 1): ") or "1")
        if num_accounts < 1:
            num_accounts = 1
    except ValueError:
        logger.warning("Giá trị không hợp lệ, sử dụng mặc định là 1 tài khoản")
        num_accounts = 1

    if args.temp_mail and (num_threads != 1 or num_accounts != 1):
        logger.error("Chế độ --temp-mail chỉ cho phép --threads 1 --accounts 1.")
        return 2
    if args.username and num_accounts != 1:
        logger.error("--username chỉ dùng khi tạo đúng một tài khoản.")
        return 2
    if args.retries is not None and args.retries < 1:
        logger.error("--retries phải lớn hơn hoặc bằng 1.")
        return 2

    logger.info(f"\nBắt đầu chạy với {num_threads} luồng để tạo {num_accounts} tài khoản")

    if chrome_path:
        logger.info(f"Trình duyệt Chrome sử dụng: {chrome_path}")
    else:
        logger.warning("Không tìm thấy Chrome portable trong thư mục tool.")
        logger.warning("Sẽ để Selenium tự dò Chrome đã cài trên hệ thống.")
        logger.warning("Nếu lỗi, hãy cài Google Chrome hoặc đặt Chrome portable vào "
                       "chrome-win64 (Windows) / chrome-mac (macOS).")

    start_time = time.time()

    successful_accounts = 0
    failed_accounts = 0
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = []

        for i in range(num_accounts):
            # Truyền biến cờ use_proxy_global vào mỗi worker
            if args.temp_mail:
                mail_manager = TempMailManager()
            elif args.email:
                mail_manager = ManualEmailManager(args.email)
            else:
                mail_manager = OutlookMailManager()
            worker = TiktokRegWorker(
                i + 1,
                proxy_queue,
                use_proxy_global,
                mail_manager,
                max_retries=args.retries if args.retries is not None else 3,
                desired_username=args.username,
                tiktok_password=args.password,
                qr_policy=args.qr_policy,
            )
            future = executor.submit(worker.run)
            futures.append(future)

        for future in futures:
            try:
                result = future.result()
                if result:
                    successful_accounts += 1
                else:
                    failed_accounts += 1
            except Exception as e:
                logger.error(f"Luồng gặp lỗi nghiêm trọng: {str(e)}")
                failed_accounts += 1

    end_time = time.time()
    elapsed_time = end_time - start_time

    logger.info("\n====== KẾT QUẢ CUỐI CÙNG ======")
    logger.info(f"Tổng số tài khoản đã tạo thành công: {successful_accounts}/{num_accounts}")
    logger.info(f"Tổng số tài khoản thất bại: {failed_accounts}")
    if num_accounts > 0:
        logger.info(f"Tỷ lệ thành công: {(successful_accounts/num_accounts)*100:.2f}%")
    else:
        logger.info("Không có tài khoản nào được yêu cầu tạo.")
    logger.info(f"Tổng thời gian thực hiện: {elapsed_time:.2f} giây")
    logger.info("================================\n")

    print_proxy_stats()

    logger.info(f"Tài khoản đã được lưu trong file {ACCOUNTS_FILE}")
    logger.info(f"Log đã được lưu trong thư mục logs/")
    return 0 if failed_accounts == 0 else 1

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.info("\nChương trình đã bị dừng bởi người dùng (Ctrl+C).")
    except Exception as e:
        logger.critical(f"Lỗi nghiêm trọng không mong muốn trong hàm main: {str(e)}", exc_info=True)
    finally:
        logger.info("Chương trình kết thúc.")
