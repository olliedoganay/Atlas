import io
import json
import unittest
from unittest.mock import patch

from atlas_local.config import load_config
from atlas_local.llm import resolve_effective_context_window


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class LlmContextWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(env={"OLLAMA_URL": "http://127.0.0.1:11434"})

    def test_resolve_context_prefers_running_model_ps_value(self) -> None:
        responses = [
            {"models": [{"name": "gpt-oss:20b", "context_length": 16384}]},
        ]

        def fake_urlopen(request_object, timeout=0):
            payload = responses.pop(0)
            return _FakeResponse(json.dumps(payload).encode("utf-8"))

        with patch("atlas_local.llm.request.urlopen", side_effect=fake_urlopen):
            value = resolve_effective_context_window(self.config, "gpt-oss:20b")

        self.assertEqual(value, 16384)

    def test_resolve_context_falls_back_to_show_model_info(self) -> None:
        responses = [
            {"models": []},
            {"model_info": {"gptoss.context_length": 131072}},
        ]

        def fake_urlopen(request_object, timeout=0):
            payload = responses.pop(0)
            return _FakeResponse(json.dumps(payload).encode("utf-8"))

        with patch("atlas_local.llm.request.urlopen", side_effect=fake_urlopen):
            value = resolve_effective_context_window(self.config, "gpt-oss:20b")

        self.assertEqual(value, 131072)


if __name__ == "__main__":
    unittest.main()
