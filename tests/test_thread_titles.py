import unittest

from atlas_local.api_service import _suggest_thread_title


class ThreadTitleTests(unittest.TestCase):
    def test_suggest_thread_title_trims_prompt(self) -> None:
        title = _suggest_thread_title("build me a simple 2d snake game in one html file")
        self.assertEqual(title, "build me a simple 2d snake")


if __name__ == "__main__":
    unittest.main()
