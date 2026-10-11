import unittest
from unittest.mock import MagicMock, call, patch

from regtiktok_multithread import (
    TiktokRegWorker,
    connect_adb_device,
    format_account_record,
    generate_totp,
    open_tiktok_android,
    parse_args,
    parse_proxy,
    read_adb_device_context,
)


class FakeElement:
    def __init__(self, text='Skip', displayed=True, enabled=True, size=None):
        self.text = text
        self._displayed = displayed
        self._enabled = enabled
        self.size = size or {'width': 20, 'height': 20}

    def is_displayed(self):
        return self._displayed

    def is_enabled(self):
        return self._enabled

    def get_attribute(self, _name):
        return None

    def click(self):
        self._displayed = False


class CoreTests(unittest.TestCase):
    def test_totp_rfc6238_vector(self):
        # RFC 6238 SHA-1 vector truncated to six digits.
        self.assertEqual(generate_totp('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ', 59), '287082')

    def test_account_record_requires_real_base32_secret(self):
        record = format_account_record('demo', 'Pass@123', 'JBSWY3DPEHPK3PXP')
        self.assertEqual(record, 'demo|Pass@123|JBSWY3DPEHPK3PXP')
        with self.assertRaises(ValueError):
            format_account_record('demo', 'Pass@123', '')

    def test_authenticated_proxy_is_parsed(self):
        parsed = parse_proxy('127.0.0.1:8080:user:pass')
        self.assertEqual(parsed['host'], '127.0.0.1')
        self.assertEqual(parsed['port'], 8080)
        self.assertEqual(parsed['username'], 'user')
        self.assertEqual(parsed['password'], 'pass')

    def test_temp_mail_cli_mode(self):
        args = parse_args([
            '--temp-mail', '--threads', '1', '--accounts', '1',
            '--username', 'demo.user', '--password', 'Example@123',
        ])
        self.assertTrue(args.temp_mail)
        self.assertEqual(args.threads, 1)
        self.assertEqual(args.accounts, 1)
        self.assertEqual(args.username, 'demo.user')
        self.assertEqual(args.password, 'Example@123')
        self.assertEqual(args.qr_policy, 'wait')

    def test_qr_wait_policy_can_be_selected(self):
        args = parse_args([
            '--qr-policy', 'wait', '--retries', '4',
            '--adb-device', '192.168.1.41:42977', '--adb-required',
        ])
        self.assertEqual(args.qr_policy, 'wait')
        self.assertEqual(args.retries, 4)
        self.assertEqual(args.adb_device, '192.168.1.41:42977')
        self.assertTrue(args.adb_required)

    @patch('regtiktok_multithread.list_adb_devices')
    @patch('regtiktok_multithread.subprocess.run')
    def test_adb_tcp_connect_confirms_exact_device(self, run, list_devices):
        list_devices.return_value = {'192.168.1.41:42977': 'device'}
        self.assertTrue(connect_adb_device('192.168.1.41:42977'))
        run.assert_called_once_with(
            ['adb', 'connect', '192.168.1.41:42977'],
            capture_output=True, text=True, timeout=20, check=False,
        )

    def test_adb_tcp_connect_rejects_invalid_endpoint(self):
        with self.assertRaises(ValueError):
            connect_adb_device('192.168.1.999:37027')

    @patch('regtiktok_multithread.subprocess.run')
    def test_adb_context_is_read_only(self, run):
        run.side_effect = [
            MagicMock(returncode=0, stdout='vi-VN\n'),
            MagicMock(returncode=0, stdout='Asia/Ho_Chi_Minh\n'),
            MagicMock(returncode=0, stdout='3\n'),
        ]

        context = read_adb_device_context('192.168.1.41:42977')

        self.assertEqual(context, {
            'locale': 'vi-VN',
            'timezone': 'Asia/Ho_Chi_Minh',
            'location_mode': '3',
        })
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands, [
            ['adb', '-s', '192.168.1.41:42977', 'shell', 'getprop', 'persist.sys.locale'],
            ['adb', '-s', '192.168.1.41:42977', 'shell', 'getprop', 'persist.sys.timezone'],
            ['adb', '-s', '192.168.1.41:42977', 'shell', 'settings', 'get', 'secure', 'location_mode'],
        ])

    @patch('regtiktok_multithread.subprocess.run')
    def test_open_tiktok_android_uses_official_launcher(self, run):
        run.side_effect = [
            MagicMock(returncode=0, stdout='', stderr=''),
            MagicMock(returncode=0, stdout='Events injected: 1', stderr=''),
        ]

        self.assertTrue(open_tiktok_android('192.168.1.41:42977'))
        self.assertEqual(run.call_args_list[1].args[0], [
            'adb', '-s', '192.168.1.41:42977', 'shell', 'monkey',
            '-p', 'com.ss.android.ugc.trill',
            '-c', 'android.intent.category.LAUNCHER', '1',
        ])

    @patch('regtiktok_multithread.time.sleep', return_value=None)
    def test_post_signup_rejection_is_detected_without_login_fallback(self, _sleep):
        worker = TiktokRegWorker.__new__(TiktokRegWorker)
        worker.worker_id = 1
        worker.post_signup_state = 'unknown'
        worker.qr_policy = 'skip'
        worker.log = MagicMock()
        worker.decode_qr_element = MagicMock(return_value=None)
        worker.click_optional_post_signup_skip = MagicMock(return_value=None)
        driver = MagicMock()
        worker.driver = driver
        body = MagicMock()
        body.text = 'Rất tiếc, đã xảy ra lỗi, vui lòng thử lại sau'
        driver.find_element.return_value = body
        driver.find_elements.return_value = []
        driver.current_url = 'https://www.tiktok.com/signup/phone-or-email'

        self.assertFalse(worker.handle_post_signup(timeout=1))
        self.assertEqual(worker.post_signup_state, 'signup_rejected')

    @patch('regtiktok_multithread.time.sleep', return_value=None)
    def test_post_signup_skip_exits_after_session_transition(self, _sleep):
        worker = TiktokRegWorker.__new__(TiktokRegWorker)
        worker.worker_id = 1
        worker.post_signup_state = 'unknown'
        worker.qr_policy = 'skip'
        worker.log = MagicMock()
        worker.decode_qr_element = MagicMock(return_value=None)
        worker.click_optional_post_signup_skip = MagicMock(return_value='Skip for now')
        driver = MagicMock()
        worker.driver = driver
        skip = FakeElement()
        body = MagicMock()
        body.text = 'Scan the QR code or Skip for now'

        def find_elements(by, value):
            if 'skip' in value.lower() and skip.is_displayed():
                return [skip]
            return []

        driver.find_elements.side_effect = find_elements
        driver.find_element.return_value = body
        driver.get_cookies.return_value = [{'name': 'sessionid', 'value': 'real-session'}]
        driver.current_url = 'https://www.tiktok.com/foryou'

        self.assertTrue(worker.handle_post_signup(timeout=1))
        self.assertEqual(worker.post_signup_state, 'confirmed')

    @patch('regtiktok_multithread.time.sleep', return_value=None)
    def test_generic_canvas_does_not_start_security_qr_wait(self, _sleep):
        worker = TiktokRegWorker.__new__(TiktokRegWorker)
        worker.worker_id = 1
        worker.post_signup_state = 'unknown'
        worker.qr_policy = 'skip'
        worker.log = MagicMock()
        worker.decode_qr_element = MagicMock(return_value=None)
        worker.click_optional_post_signup_skip = MagicMock(return_value=None)
        driver = MagicMock()
        worker.driver = driver
        body = MagicMock()
        body.text = 'Welcome to TikTok'
        driver.find_element.return_value = body
        driver.find_elements.return_value = []
        driver.get_cookies.return_value = []
        driver.current_url = 'https://www.tiktok.com/signup'

        self.assertFalse(worker.handle_post_signup(timeout=0))
        self.assertEqual(worker.post_signup_state, 'unconfirmed')

    @patch.dict('regtiktok_multithread.CONFIG', {'QR_SKIP_DISCOVERY_TIME': 0})
    def test_mandatory_security_qr_fails_fast_in_skip_policy(self):
        worker = TiktokRegWorker.__new__(TiktokRegWorker)
        worker.worker_id = 1
        worker.qr_policy = 'skip'
        worker.post_signup_state = 'unknown'
        worker.log = MagicMock()
        worker.decode_qr_element = MagicMock(return_value=None)
        worker.click_optional_post_signup_skip = MagicMock(return_value=None)
        driver = MagicMock()
        worker.driver = driver
        body = MagicMock()
        body.text = 'For security reasons, continue with the TikTok app'
        driver.find_element.return_value = body
        driver.find_elements.return_value = []
        driver.get_cookies.return_value = []
        driver.current_url = 'https://www.tiktok.com/signup'

        self.assertFalse(worker.handle_post_signup(timeout=1))
        self.assertEqual(worker.post_signup_state, 'security_qr_required')

    @patch('regtiktok_multithread.time.sleep', return_value=None)
    def test_vietnamese_tiktok_id_onboarding_confirms_created_session(self, _sleep):
        worker = TiktokRegWorker.__new__(TiktokRegWorker)
        worker.worker_id = 1
        worker.post_signup_state = 'unknown'
        worker.qr_policy = 'wait'
        worker.log = MagicMock()
        worker.decode_qr_element = MagicMock(return_value=None)
        worker.click_optional_post_signup_skip = MagicMock(return_value='Bỏ qua')
        driver = MagicMock()
        worker.driver = driver
        body = MagicMock()
        body.text = 'Đăng ký Tạo TikTok ID Bạn luôn có thể thay đổi điều này sau. Bỏ qua'
        driver.find_element.return_value = body
        driver.find_elements.return_value = []
        driver.get_cookies.return_value = [{'name': 'sessionid', 'value': 'real-session'}]
        driver.current_url = 'https://www.tiktok.com/signup'

        self.assertTrue(worker.handle_post_signup(timeout=1))
        self.assertEqual(worker.post_signup_state, 'confirmed')


if __name__ == '__main__':
    unittest.main()
