import unittest
from unittest.mock import patch

import app


class AndroidAppTests(unittest.TestCase):
    def test_node_center(self):
        node = app.UiNode("Sign up", "", "", "TextView", (10, 20, 110, 220), True)
        self.assertEqual(node.center, (60, 120))

    @patch("app.connected_devices", return_value=["192.168.1.41:42977"])
    def test_choose_only_tcp_device(self, _devices):
        self.assertEqual(app.choose_device(None), "192.168.1.41:42977")

    @patch("app.connected_devices", return_value=["usb-device", "192.168.1.41:42977"])
    def test_choose_tcp_when_one_tcp_and_one_usb(self, _devices):
        self.assertEqual(app.choose_device(None), "192.168.1.41:42977")

    @patch("app.connected_devices", return_value=[])
    def test_choose_device_requires_online_device(self, _devices):
        with self.assertRaises(app.AndroidError):
            app.choose_device(None)

    def test_vietnamese_email_check_is_otp_state(self):
        labels = "Kiểm tra email của bạn\nGửi lại mã".casefold()
        self.assertTrue(any(item in labels for item in app.TikTokAndroidFlow.OTP_HINTS))

    def test_profile_alone_is_not_signup_success(self):
        self.assertNotIn("profile", app.TikTokAndroidFlow.SUCCESS_HINTS)

    def test_old_otp_screen_can_be_identified_before_new_email(self):
        labels = "Kiểm tra email của bạn\nSử dụng liên kết này hoặc mã được gửi đến old@example.com".casefold()
        self.assertTrue(any(item in labels for item in app.TikTokAndroidFlow.OTP_HINTS))


if __name__ == "__main__":
    unittest.main()
