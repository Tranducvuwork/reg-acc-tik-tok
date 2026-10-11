# TikTok Account Registration Tool v2.19

**Tác giả**: Hồ Hiệp x HVHTOOL  
**Mô tả**: Công cụ đăng ký tài khoản TikTok tự động bằng Selenium, hỗ trợ proxy và đa luồng.  
**Phiên bản**: 2.19 – Cải tiến logic xác nhận đăng ký

---

## ✅ Tính năng chính

- Đăng ký tài khoản TikTok tự động bằng trình duyệt thật (Chrome)    
- Chủ động chọn luồng đăng ký bằng email, không yêu cầu nhập số điện thoại khi TikTok cho phép
- Hỗ trợ proxy dạng `ip:port` và `ip:port:user:pass`
- Hỗ trợ đa luồng (multithread)
- Ghi log chi tiết, lưu tài khoản đã tạo
- Tự giải mã QR và mở URL trong tab phụ
- Hỗ trợ luồng Quên mật khẩu, nhận OTP qua email và đăng nhập kiểm tra
- Tự động kiểm tra và đánh dấu proxy lỗi
- Đọc OTP từ Outlook/Hotmail có sẵn qua Microsoft Graph OAuth
- Hỗ trợ đăng nhập Microsoft có 2FA bằng device-code chính thức; không lưu mật khẩu Microsoft

---

## 📦 Cấu trúc thư mục

```
/
├── regtiktok_multithread.py     # File script chính
├── chrome-win64/                # Thư mục chứa trình duyệt Chrome portable
│   └── chrome.exe
├── data/
│   ├── proxy.txt                # Danh sách proxy
│   ├── outlook_accounts.txt     # email Outlook và Microsoft Client ID (không commit)
│   ├── outlook_accounts.example.txt
│   ├── passwords.txt            # Danh sách mật khẩu email
│   └── useragents-desktop.txt   # Danh sách User-Agent
├── logs/
│   ├── regtiktok.log            # Log chính
│   └── proxy_log.txt            # Thống kê proxy
└── accounts.txt                 # Lưu thông tin tài khoản TikTok đã tạo
```

---

## ⚙️ Cài đặt

1. **Cài đặt Python:**  
   Yêu cầu Python 3.8 trở lên.  
   Tải từ: https://www.python.org/downloads/

2. **Cài thư viện cần thiết:**
   ```bash
   pip install -r requirements.txt
   ```
   Nếu chưa có `requirements.txt`, bạn có thể tự cài:
   ```bash
   pip install selenium requests opencv-python-headless numpy
   ```

3. **Tải trình duyệt Chrome portable:**  
   - Đặt `chrome.exe` vào thư mục `chrome-win64` ngang hàng với file script.

---

## 🛠️ Cấu hình dữ liệu

- **proxy.txt:** danh sách proxy dạng `ip:port` hoặc `ip:port:user:pass`, mỗi dòng một proxy.
- **outlook_accounts.txt:** mỗi dòng `email@outlook.com|MICROSOFT_APPLICATION_CLIENT_ID`.
  Chỉ dùng hộp thư bạn sở hữu. Lần đầu chạy, Microsoft hiển thị mã đăng nhập;
  mở URL được hướng dẫn, nhập mã và hoàn tất 2FA. Token được lưu cục bộ trong
  `data/.outlook_tokens/` và không được đưa lên GitHub.
- **passwords.txt:** danh sách mật khẩu để dùng cho email tạm.
- **useragents-desktop.txt:** danh sách User-Agent giả lập trình duyệt.

Khi chạy lần đầu, các file trên sẽ được tự động tạo nếu chưa có.

---

## ▶️ Cách sử dụng

Chạy file chính:

```bash
python regtiktok_multithread.py
```

Kiểm tra cấu hình mà không mở trình duyệt:

```bash
python regtiktok_multithread.py --check
```

Chạy đúng một tài khoản, một luồng:

```bash
python regtiktok_multithread.py --threads 1 --accounts 1 --email ban@gmail.com
```

Kết nối thiết bị Android đã ghép đôi qua ADB TCP và bắt buộc thiết bị phải online:

```bash
python regtiktok_multithread.py --adb-device 192.168.1.41:42977 --adb-required --check
python regtiktok_multithread.py --adb-device 192.168.1.41:42977 --adb-required --threads 1 --accounts 1 --email ban@gmail.com
```

Chỉ mở TikTok trực tiếp trên điện thoại để kiểm tra kết nối:

```bash
python regtiktok_multithread.py --adb-device 192.168.1.41:42977 --open-android
```

Chạy flow native trực tiếp trong app TikTok trên Android (không dùng Chrome/Selenium):

```bash
chmod +x run_android.sh
./run_android.sh --device 192.168.1.41:42977
```

Chạy toàn bộ flow Android với email tạm và tự lấy OTP:

```bash
./run_android.sh --device 192.168.1.41:42977 --temp-mail
```

Hoặc dùng email của bạn và nhập OTP trong Terminal:

```bash
./run_android.sh --device 192.168.1.41:42977 --email you@example.com
```

Flow native chỉ bấm các nút được nhận diện bằng text, không bấm theo tọa độ cố
định. Ngày sinh, OTP, CAPTCHA và checkpoint được hoàn tất thủ công trên điện
thoại. Dùng `python3 app.py --device SERIAL --inspect` để xem nội dung UI mà ADB
đang nhận diện.

Tool chỉ đọc locale, múi giờ và trạng thái dịch vụ vị trí để báo cáo; không thay
đổi, giả lập hoặc đồng bộ các cài đặt này. Kết nối mạng/proxy 4G vẫn do chính
điện thoại hoặc router quản lý. Khi TikTok yêu cầu xác minh bắt buộc, tool mở
deep-link trong ứng dụng và chờ bạn xác nhận thay vì né bước bảo mật.

Với `--email`, bạn có thể dùng Gmail hoặc bất kỳ hộp thư nào mình sở hữu.
Khi TikTok gửi mã 6 số, công cụ sẽ yêu cầu nhập OTP trực tiếp trong Terminal;
không cần Microsoft Client ID.

Hoặc dùng lớp email tạm `mail.tm` đã có sẵn trong dự án để tạo đúng một tài khoản:

```bash
python regtiktok_multithread.py --temp-mail --threads 1 --accounts 1
```

Mặc định công cụ thử tối đa 3 lần. Mỗi lần thất bại ở form đăng ký trong chế độ
email tạm sẽ mở phiên mới và tạo một địa chỉ mail.tm mới. Có thể đổi giới hạn:

```bash
python regtiktok_multithread.py --temp-mail --threads 1 --accounts 1 --retries 5
```

Mặc định tool giữ nguyên phiên đăng ký và chờ tối đa 180 giây để bạn hoàn tất QR
checkpoint bằng ứng dụng TikTok trên điện thoại. Nếu đây chỉ là onboarding tùy
chọn, tool vẫn tự bấm nút **Skip / Skip for now / Not now / Maybe later** chính
thức. Muốn dừng ngay khi gặp QR bắt buộc, chạy thêm `--qr-policy skip`.

Chế độ này cố ý giới hạn ở một tài khoản. Ngay trước nút **Sign up**, công cụ vẫn
yêu cầu nhập `CREATE`. Nếu TikTok hiện QR bảo mật, hãy mở ứng dụng TikTok trên
điện thoại và hoàn tất checkpoint trong vòng 180 giây. Công cụ giữ nguyên phiên
đăng ký, kiểm tra session thật, rồi mới bật Authenticator và lưu kết quả; luồng
Quên mật khẩu không được dùng để thay thế checkpoint thiết bị.

Sau đó nhập:

- Số **luồng**: số trình duyệt chạy song song
- Số **tài khoản**: số lượng tài khoản cần tạo

> ⚠️ Nếu không có proxy, tool sẽ tự động chuyển sang chế độ **không dùng proxy**.

---

## 📋 Kết quả

- Tài khoản thành công được lưu tại `accounts.txt` dạng:
  ```
  username|tiktok_password|2fa_secret
  ```
  Tool chỉ lưu sau khi 2FA đã được bật và secret hợp lệ; không tạo khóa 2FA giả.
- Proxy lỗi sẽ được đánh dấu trong `data/proxy.txt`
- Thống kê proxy thành công/thất bại nằm ở `logs/proxy_log.txt`
- Log chi tiết toàn bộ quá trình tại `logs/regtiktok.log`

---

## ❗ Lưu ý

- Cần kết nối Internet ổn định
- Cần tạo Microsoft Entra application dạng public client và cấp quyền delegated
  `Mail.Read`, `User.Read` cho Client ID dùng trong `outlook_accounts.txt`
- Tool không tự tạo Outlook/Hotmail và không lưu mật khẩu hoặc mã 2FA Microsoft
- Tool vẫn tuân theo CAPTCHA, OTP và các bước xác minh bảo mật do TikTok yêu cầu
- Tool chỉ lưu kết quả sau khi TikTok xác nhận Authenticator và khóa 2FA thật đã được kiểm tra
- Nếu CAPTCHA xuất hiện, tool sẽ chờ `600s` rồi tiếp tục

---
## Cảm Ơn 

 <#--Cảm ơn  bạn nhandzcl đã ủng hộ 20,000 vnd--#>

## 👨‍💻 Liên hệ

> Tác giả: Hồ Hiệp  
> Tool hỗ trợ phát triển bởi: HVHTOOL  
> Phiên bản: 2.19 – Cập nhật logic đăng ký, xử lý lỗi tốt hơn

---
