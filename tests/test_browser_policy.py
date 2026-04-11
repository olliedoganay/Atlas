import unittest

from atlas_local.browser.policy import BrowserPolicy, BrowserPolicyError


class BrowserPolicyTests(unittest.TestCase):
    def test_read_only_public_navigation_is_allowed(self) -> None:
        policy = BrowserPolicy(allowlist=(), blocklist=())
        policy.check("open_page", "https://example.com")

    def test_public_click_is_blocked_without_allowlist(self) -> None:
        policy = BrowserPolicy(allowlist=(), blocklist=())
        with self.assertRaises(BrowserPolicyError):
            policy.check("click", "https://example.com")

    def test_allowlisted_click_is_permitted(self) -> None:
        policy = BrowserPolicy(allowlist=("example.com",), blocklist=())
        policy.check("click", "https://example.com/path")


if __name__ == "__main__":
    unittest.main()
