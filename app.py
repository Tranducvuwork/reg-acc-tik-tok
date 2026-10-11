#!/usr/bin/env python3
"""Run the TikTok signup entry flow on a connected Android device.

This module intentionally uses Android's built-in ADB/UIAutomator interfaces so
it does not require Selenium, Chrome, Appium, or an APK rebuild. Security and
identity checks remain manual.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import secrets
import string
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import requests


TIKTOK_PACKAGE = "com.ss.android.ugc.trill"
BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


class AndroidError(RuntimeError):
    pass


class MailError(RuntimeError):
    pass


class MailTm:
    """Minimal mail.tm client used by the single-account Android flow."""

    def __init__(self) -> None:
        self.base_url = "https://api.mail.tm"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 Android TikTokFlow/1.0"})
        self.address = ""
        self.password = ""
        self.token = ""
        self.provider = "mail.tm"

    def _create_guerrilla(self) -> str:
        response = self.session.get(
            "https://api.guerrillamail.com/ajax.php",
            params={"f": "get_email_address", "lang": "en"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("email_addr") or not payload.get("sid_token"):
            raise MailError("Guerrilla Mail không cấp được hộp thư tạm.")
        self.provider = "guerrilla"
        self.address = payload["email_addr"]
        self.token = payload["sid_token"]
        self.password = ""
        return self.address

    def create(self) -> str:
        response = self.session.get(f"{self.base_url}/domains", timeout=15)
        response.raise_for_status()
        domains = response.json().get("hydra:member", [])
        if not domains:
            raise MailError("mail.tm hiện không có domain khả dụng.")
        domain = domains[0]["domain"]
        self.password = "Tt!" + secrets.token_urlsafe(12)
        limited = 0
        for attempt in range(1, 6):
            local = "android" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
            self.address = f"{local}@{domain}"
            created = self.session.post(
                f"{self.base_url}/accounts",
                json={"address": self.address, "password": self.password},
                timeout=15,
            )
            if created.status_code == 201:
                break
            if created.status_code == 429:
                limited += 1
                if limited >= 2:
                    print("→ mail.tm vẫn giới hạn; chuyển sang hộp thư dự phòng...")
                    return self._create_guerrilla()
                retry_after = created.headers.get("Retry-After", "")
                wait_seconds = int(retry_after) if retry_after.isdigit() else min(5 * attempt, 20)
                print(f"→ mail.tm đang giới hạn yêu cầu; thử lại sau {wait_seconds} giây...")
                time.sleep(wait_seconds)
                continue
            if created.status_code not in (409, 422):
                raise MailError(f"mail.tm từ chối tạo email ({created.status_code}).")
        else:
            print("→ mail.tm không tạo được địa chỉ; chuyển sang hộp thư dự phòng...")
            return self._create_guerrilla()
        login = self.session.post(
            f"{self.base_url}/token",
            json={"address": self.address, "password": self.password},
            timeout=15,
        )
        if login.status_code != 200 or not login.json().get("token"):
            raise MailError("Không đăng nhập được hộp thư mail.tm vừa tạo.")
        self.token = login.json()["token"]
        return self.address

    def message_ids(self) -> set[str]:
        if self.provider == "guerrilla":
            response = self.session.get(
                "https://api.guerrillamail.com/ajax.php",
                params={"f": "get_email_list", "offset": 0, "sid_token": self.token},
                timeout=15,
            )
            if response.status_code != 200:
                return set()
            return {str(item["mail_id"]) for item in response.json().get("list", []) if item.get("mail_id")}
        response = self.session.get(
            f"{self.base_url}/messages?page=1",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=15,
        )
        if response.status_code != 200:
            return set()
        return {item["id"] for item in response.json().get("hydra:member", []) if item.get("id")}

    def wait_for_otp(self, old_ids: set[str], timeout: int = 300) -> str:
        deadline = time.monotonic() + timeout
        if self.provider == "guerrilla":
            while time.monotonic() < deadline:
                listing = self.session.get(
                    "https://api.guerrillamail.com/ajax.php",
                    params={"f": "get_email_list", "offset": 0, "sid_token": self.token},
                    timeout=15,
                )
                if listing.status_code == 200:
                    for message in listing.json().get("list", []):
                        message_id = str(message.get("mail_id", ""))
                        if not message_id or message_id in old_ids:
                            continue
                        detail = self.session.get(
                            "https://api.guerrillamail.com/ajax.php",
                            params={"f": "fetch_email", "email_id": message_id, "sid_token": self.token},
                            timeout=15,
                        )
                        if detail.status_code == 200:
                            payload = detail.json()
                            body = " ".join(str(payload.get(key, "")) for key in ("mail_subject", "mail_excerpt", "mail_body"))
                            match = re.search(r"\b\d{6}\b", body)
                            if match:
                                return match.group(0)
                time.sleep(5)
            raise MailError("Hết 5 phút nhưng chưa nhận được OTP TikTok.")
        headers = {"Authorization": f"Bearer {self.token}"}
        while time.monotonic() < deadline:
            listing = self.session.get(
                f"{self.base_url}/messages?page=1", headers=headers, timeout=15
            )
            if listing.status_code == 200:
                for message in listing.json().get("hydra:member", []):
                    message_id = message.get("id")
                    if not message_id or message_id in old_ids:
                        continue
                    detail = self.session.get(
                        f"{self.base_url}/messages/{message_id}", headers=headers, timeout=15
                    )
                    if detail.status_code != 200:
                        continue
                    payload = detail.json()
                    body = str(payload.get("text", "")) + " " + str(payload.get("html", ""))
                    match = re.search(r"\b\d{6}\b", body)
                    if match:
                        return match.group(0)
            time.sleep(5)
        raise MailError("Hết 5 phút nhưng chưa nhận được OTP TikTok.")


@dataclass(frozen=True)
class UiNode:
    text: str
    description: str
    resource_id: str
    class_name: str
    bounds: tuple[int, int, int, int]
    clickable: bool

    @property
    def label(self) -> str:
        return " ".join(part for part in (self.text, self.description) if part).strip()

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.bounds
        return (left + right) // 2, (top + bottom) // 2


class AndroidDevice:
    def __init__(self, serial: str, adb: str = "adb") -> None:
        self.serial = serial
        self.adb = adb

    def _run(
        self,
        *args: str,
        timeout: int = 20,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [self.adb, "-s", self.serial, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise AndroidError(f"Không chạy được ADB: {exc}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise AndroidError(detail or f"ADB thoát với mã {result.returncode}")
        return result

    def ensure_online(self) -> None:
        state = self._run("get-state").stdout.strip()
        if state != "device":
            raise AndroidError(f"Device {self.serial} không online (state={state or 'unknown'})")

    def foreground_package(self) -> str:
        output = self._run("shell", "dumpsys", "activity", "activities").stdout
        match = re.search(r"(?:topResumedActivity|mResumedActivity)=.*?\s([\w.]+)/", output)
        return match.group(1) if match else ""

    def launch_tiktok(self) -> None:
        self._run("shell", "input", "keyevent", "KEYCODE_WAKEUP", check=False)
        result = self._run(
            "shell", "monkey", "-p", TIKTOK_PACKAGE,
            "-c", "android.intent.category.LAUNCHER", "1",
        )
        if "Events injected: 1" not in result.stdout:
            raise AndroidError("Không mở được TikTok. Hãy kiểm tra app đã được cài.")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.foreground_package() == TIKTOK_PACKAGE:
                return
            time.sleep(0.5)
        raise AndroidError("TikTok đã được gọi nhưng chưa lên foreground.")

    def nodes(self) -> list[UiNode]:
        remote = "/sdcard/codex_tiktok_window.xml"
        xml_text = ""
        for _attempt in range(3):
            self._run("shell", "rm", "-f", remote, check=False)
            self._run("shell", "uiautomator", "dump", remote, timeout=15, check=False)
            pulled = self._run("shell", "cat", remote, check=False)
            if pulled.returncode == 0 and pulled.stdout.lstrip().startswith("<?xml"):
                xml_text = pulled.stdout
                break
            time.sleep(0.75)
        if not xml_text:
            raise AndroidError("UIAutomator chưa đọc được màn hình đang chuyển động.")
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise AndroidError("Không đọc được cây giao diện Android.") from exc

        result: list[UiNode] = []
        for element in root.iter("node"):
            raw_bounds = element.attrib.get("bounds", "")
            match = BOUNDS_RE.fullmatch(raw_bounds)
            if not match:
                continue
            result.append(UiNode(
                text=element.attrib.get("text", "").strip(),
                description=element.attrib.get("content-desc", "").strip(),
                resource_id=element.attrib.get("resource-id", "").strip(),
                class_name=element.attrib.get("class", "").strip(),
                bounds=tuple(map(int, match.groups())),
                clickable=element.attrib.get("clickable") == "true",
            ))
        return result

    def tap(self, node: UiNode) -> None:
        x, y = node.center
        self._run("shell", "input", "tap", str(x), str(y))

    def tap_relative(self, x_ratio: float, y_ratio: float) -> None:
        output = self._run("shell", "wm", "size").stdout
        match = re.search(r"Physical size:\s*(\d+)x(\d+)", output)
        if not match:
            raise AndroidError("Không đọc được kích thước màn hình device.")
        width, height = map(int, match.groups())
        self._run(
            "shell", "input", "tap",
            str(round(width * x_ratio)), str(round(height * y_ratio)),
        )

    def input_text(self, value: str) -> None:
        # ADB input uses %s for spaces. Email/password generated by this tool
        # intentionally avoid shell metacharacters.
        encoded = value.replace(" ", "%s")
        self._run("shell", "input", "text", encoded)

    def back(self) -> None:
        self._run("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1)

    def replace_text(self, node: UiNode, value: str) -> None:
        self.tap(node)
        time.sleep(0.3)
        self._run("shell", "input", "keyevent", "KEYCODE_MOVE_END", check=False)
        # `--longpress KEYCODE_DEL` removes only one character on some Vivo
        # builds. Send enough ordinary delete events to clear any prior run.
        self._run("shell", "input", "keyevent", *(["KEYCODE_DEL"] * 160), check=False)
        self.input_text(value)
        time.sleep(0.5)

    def editable_nodes(self) -> list[UiNode]:
        return [node for node in self.nodes() if node.class_name == "android.widget.EditText"]

    def labels_contain(self, *needles: str) -> bool:
        labels = "\n".join(self.visible_labels()).casefold()
        return any(needle.casefold() in labels for needle in needles)

    def tap_text(self, labels: Iterable[str], timeout: float = 12) -> Optional[str]:
        wanted = [label.casefold() for label in labels]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.foreground_package() != TIKTOK_PACKAGE:
                return None
            nodes = self.nodes()
            for exact in (True, False):
                for node in nodes:
                    label = node.label.casefold()
                    if not label:
                        continue
                    matched = any(label == item for item in wanted) if exact else any(
                        item in label for item in wanted
                    )
                    if matched:
                        self.tap(node)
                        time.sleep(1)
                        return node.label
            time.sleep(0.75)
        return None

    def screenshot(self, destination: Path) -> None:
        result = subprocess.run(
            [self.adb, "-s", self.serial, "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            raise AndroidError("Không chụp được màn hình device.")
        destination.write_bytes(result.stdout)

    def visible_labels(self) -> list[str]:
        labels = []
        for node in self.nodes():
            if node.label and node.label not in labels:
                labels.append(node.label)
        return labels


class TikTokAndroidFlow:
    PROFILE = ("Profile", "Hồ sơ")
    SIGN_UP = ("Sign up", "Đăng ký")
    PHONE_EMAIL = (
        "Use phone or email",
        "Sử dụng số điện thoại hoặc email",
        "Dùng số điện thoại hoặc email",
        "Continue with email",
        "Tiếp tục với email",
    )

    CONTINUE = ("Continue", "Tiếp tục", "Next", "Tiếp")
    OTP_HINTS = (
        "verification code", "mã xác minh", "enter code", "nhập mã",
        "check your email", "kiểm tra email của bạn", "gửi lại mã",
    )
    PASSWORD_HINTS = ("create password", "tạo mật khẩu", "password", "mật khẩu")
    SUCCESS_HINTS = ("edit profile", "sửa hồ sơ", "skip", "bỏ qua", "choose your interests", "chọn sở thích")

    def __init__(self, device: AndroidDevice) -> None:
        self.device = device

    def _open_email_signup(self) -> None:
        try:
            profile = self.device.tap_text(self.PROFILE, timeout=5)
        except AndroidError:
            self.device.tap_relative(0.91, 0.95)
            time.sleep(2)
            profile = "Hồ sơ"
        if profile:
            print(f"✓ Đã mở {profile}")
        signup = self.device.tap_text(self.SIGN_UP, timeout=8)
        if signup:
            print(f"✓ Đã chọn {signup}")
        method = self.device.tap_text(self.PHONE_EMAIL, timeout=10)
        if method:
            print(f"✓ Đã chọn {method}")

    def _fill_first_editable(self, value: str, description: str) -> None:
        nodes = self.device.editable_nodes()
        if not nodes:
            raise AndroidError(f"Không thấy ô {description} trên màn hình.")
        self.device.replace_text(nodes[0], value)
        print(f"✓ Đã nhập {description}")

    def _manual_checkpoint(self, reason: str, expected: tuple[str, ...], timeout: int = 300) -> None:
        print(f"→ {reason} trên điện thoại. Tool đang chờ tối đa {timeout} giây...")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                labels = "\n".join(self.device.visible_labels()).casefold()
            except AndroidError:
                time.sleep(2)
                continue
            if any(item.casefold() in labels for item in expected):
                return
            time.sleep(2)
        raise AndroidError(f"Hết thời gian chờ: {reason}.")

    def register(self, email: str, password: str, mailbox: Optional[MailTm], resume: bool = False) -> int:
        self.device.ensure_online()
        self.device.launch_tiktok()
        print(f"✓ TikTok đang chạy trên {self.device.serial}")
        initial_labels = "\n".join(self.device.visible_labels()).casefold()
        on_birthday = any(item in initial_labels for item in ("birthday", "date of birth", "ngày sinh"))
        if not resume and not on_birthday:
            self._open_email_signup()

        if resume or on_birthday:
            print("→ Chọn ngày sinh thật trên điện thoại rồi bấm Tiếp tục.")
            self._manual_checkpoint(
                "Chọn ngày sinh hợp lệ rồi bấm Tiếp tục",
                self.PASSWORD_HINTS,
            )
        else:
            # A previous interrupted run may leave TikTok on its OTP screen. Go
            # back to the email form so the new mailbox and its token stay paired.
            labels = "\n".join(self.device.visible_labels()).casefold()
            if any(item in labels for item in self.OTP_HINTS):
                if not self.device.tap_text(("Quay lại màn hình trước", "Back"), timeout=3):
                    self.device.back()
                print("✓ Đã quay lại form email từ lượt trước")

            # If the app is already on the email screen, the navigation calls above
            # simply time out and the field is still discovered here.
            self._fill_first_editable(email, "email")
            old_ids = mailbox.message_ids() if mailbox else set()
            if not self.device.tap_text(self.CONTINUE, timeout=8):
                raise AndroidError("Không thấy nút Tiếp tục sau khi nhập email.")

        # TikTok commonly asks for date of birth between email and OTP. Picker
        # implementations vary by Android/TikTok version, so it remains a
        # visible user-confirmed step rather than a blind coordinate gesture.
            time.sleep(2)
            labels = "\n".join(self.device.visible_labels()).casefold()
            if any(item in labels for item in self.OTP_HINTS):
                if mailbox:
                    print("→ Đang chờ OTP từ TikTok...")
                    otp = mailbox.wait_for_otp(old_ids)
                else:
                    otp = input("Nhập OTP TikTok gồm 6 số: ").strip()
                    if not re.fullmatch(r"\d{6}", otp):
                        raise AndroidError("OTP phải gồm đúng 6 chữ số.")
                self._fill_first_editable(otp, "OTP")
                self.device.tap_text(self.CONTINUE, timeout=8)
                time.sleep(2)

            labels = "\n".join(self.device.visible_labels()).casefold()
            if any(item in labels for item in ("birthday", "date of birth", "ngày sinh")):
                print("→ Chọn ngày sinh thật trên điện thoại rồi bấm Tiếp tục.")
                self._manual_checkpoint(
                    "Chọn ngày sinh hợp lệ rồi bấm Tiếp tục",
                    self.PASSWORD_HINTS,
                )

        labels = "\n".join(self.device.visible_labels()).casefold()
        if any(item in labels for item in self.PASSWORD_HINTS):
            self._fill_first_editable(password, "mật khẩu TikTok")
            confirmation = input(f"Sắp tạo tài khoản TikTok cho {email}. Nhập CREATE để tiếp tục: ")
            if confirmation.strip() != "CREATE":
                raise AndroidError("Bạn chưa xác nhận CREATE; đã dừng trước bước tạo tài khoản.")
            if not self.device.tap_text(self.CONTINUE + self.SIGN_UP, timeout=10):
                raise AndroidError("Không thấy nút tạo tài khoản sau khi nhập mật khẩu.")

        # Never bypass CAPTCHA or device checkpoints. Wait for the user to
        # complete them and only report success when a post-signup screen is visible.
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                labels = "\n".join(self.device.visible_labels()).casefold()
            except AndroidError:
                time.sleep(2)
                continue
            if any(item in labels for item in ("captcha", "verify", "xác minh", "security check")):
                print("→ Hoàn tất CAPTCHA/checkpoint trực tiếp trên điện thoại.")
            if any(item.casefold() in labels for item in self.SUCCESS_HINTS):
                record = {"email": email, "tiktok_password": password, "created_at": int(time.time())}
                with Path("accounts_android.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                print("✓ TikTok đã chuyển sang màn hình sau đăng ký; đã lưu accounts_android.jsonl")
                return 0
            time.sleep(2)
        raise AndroidError("Chưa xác nhận được trạng thái tài khoản sau 5 phút.")

    def start_signup(self) -> int:
        self.device.ensure_online()
        self.device.launch_tiktok()
        print(f"✓ TikTok đang chạy trên {self.device.serial}")

        # TikTok may open directly on a logged-out signup page. Each step is
        # best-effort so layout changes do not result in blind coordinate taps.
        try:
            profile = self.device.tap_text(self.PROFILE, timeout=5)
        except AndroidError:
            # The endlessly playing For You feed can prevent UIAutomator from
            # reaching an idle state. TikTok's profile tab is the last item in
            # the fixed bottom navigation; use a screen-relative tap only for
            # this navigation step, then return to text-based selection.
            self.device.tap_relative(0.91, 0.95)
            time.sleep(2)
            profile = "Hồ sơ"
        if profile:
            print(f"✓ Đã mở {profile}")

        signup = self.device.tap_text(self.SIGN_UP, timeout=8)
        if signup:
            print(f"✓ Đã chọn {signup}")

        method = self.device.tap_text(self.PHONE_EMAIL, timeout=10)
        if method:
            print(f"✓ Đã chọn {method}")
            print("→ Tiếp tục trên điện thoại: nhập ngày sinh, email và OTP.")
            print("→ CAPTCHA/checkpoint phải được hoàn tất thủ công trong app.")
            return 0

        labels = self.device.visible_labels()
        print("TikTok đã mở nhưng chưa nhận diện được nút đăng ký hiện tại.")
        if labels:
            print("Nội dung đang thấy: " + " | ".join(labels[:12]))
        print("Hãy kiểm tra màn hình trên điện thoại rồi chạy lại lệnh.")
        return 1


def connected_devices(adb: str = "adb") -> list[str]:
    try:
        result = subprocess.run(
            [adb, "devices"], capture_output=True, text=True, timeout=10, check=True
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise AndroidError(f"Không đọc được danh sách ADB: {exc}") from exc
    return [
        parts[0]
        for line in result.stdout.splitlines()[1:]
        if len(parts := line.split()) >= 2 and parts[1] == "device"
    ]


def choose_device(requested: Optional[str], adb: str = "adb") -> str:
    devices = connected_devices(adb)
    if requested:
        if requested not in devices:
            raise AndroidError(f"Device {requested} chưa online.")
        return requested
    tcp_devices = [serial for serial in devices if re.fullmatch(r"[^:]+:\d+", serial)]
    if len(tcp_devices) == 1:
        return tcp_devices[0]
    if len(devices) == 1:
        return devices[0]
    if not devices:
        raise AndroidError("Không có Android device nào online.")
    raise AndroidError("Có nhiều device; hãy truyền --device SERIAL.")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chạy flow TikTok native trên Android")
    parser.add_argument("--device", help="ADB serial, ví dụ 192.168.1.41:42977")
    parser.add_argument("--inspect", action="store_true", help="In nội dung UI hiện tại")
    parser.add_argument("--screenshot", type=Path, help="Lưu ảnh màn hình device")
    parser.add_argument("--email", help="Email của bạn; OTP sẽ được nhập trong Terminal")
    parser.add_argument("--temp-mail", action="store_true", help="Tạo email mail.tm và tự lấy OTP")
    parser.add_argument("--password", help="Mật khẩu TikTok muốn dùng")
    parser.add_argument("--resume", action="store_true", help="Tiếp tục từ màn hình ngày sinh/mật khẩu hiện tại")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        serial = choose_device(args.device)
        device = AndroidDevice(serial)
        device.ensure_online()
        if args.screenshot:
            device.screenshot(args.screenshot.expanduser().resolve())
            print(f"Đã lưu ảnh: {args.screenshot.expanduser().resolve()}")
            return 0
        if args.inspect:
            print("\n".join(device.visible_labels()) or "Không thấy text trên màn hình.")
            return 0
        if args.email and args.temp_mail:
            raise AndroidError("Không thể dùng đồng thời --email và --temp-mail.")
        mailbox = None
        email = args.email
        if not args.resume and (args.temp_mail or not email):
            mailbox = MailTm()
            print("→ Đang tạo email tạm...")
            email = mailbox.create()
            print(f"✓ Email tạm: {email}")
        password = args.password or ("Tt!" + secrets.token_urlsafe(10))
        if args.resume and not email:
            raise AndroidError("--resume cần --email để lưu đúng tài khoản.")
        return TikTokAndroidFlow(device).register(email, password, mailbox, resume=args.resume)
    except (AndroidError, MailError, requests.RequestException) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
