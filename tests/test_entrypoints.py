import unittest
from unittest.mock import patch

from atlas_local import entrypoints


class EntrypointTests(unittest.TestCase):
    @patch("atlas_local.entrypoints.run_chat_launcher", return_value=0)
    @patch("atlas_local.entrypoints.cli_main")
    def test_atlas_main_uses_chat_launcher(self, cli_main_mock, launcher_mock) -> None:
        exit_code = entrypoints.atlas_main()

        self.assertEqual(exit_code, 0)
        launcher_mock.assert_called_once_with(cli_main_mock, description="Primary launcher for Atlas.")

    @patch("atlas_local.entrypoints.api_main", return_value=0)
    def test_atlas_backend_main_forwards_to_api_main(self, api_main_mock) -> None:
        exit_code = entrypoints.atlas_backend_main()

        self.assertEqual(exit_code, 0)
        api_main_mock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
