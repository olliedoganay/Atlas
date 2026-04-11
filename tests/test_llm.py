import unittest
from types import SimpleNamespace
from unittest.mock import patch

from atlas_local.llm import LLMProvider


class LLMProviderTemperatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SimpleNamespace(
            chat_model="gpt-oss:20b",
            chat_temperature=0.2,
            ollama_url="http://127.0.0.1:11434",
        )

    @patch("atlas_local.llm.ChatOllama")
    def test_chat_omits_temperature_when_using_model_default(self, chat_ollama_mock) -> None:
        provider = LLMProvider(self.config)

        provider.chat("gpt-oss:20b", temperature=None)

        _, kwargs = chat_ollama_mock.call_args
        self.assertTrue(kwargs["reasoning"])
        self.assertNotIn("temperature", kwargs)

    @patch("atlas_local.llm.ChatOllama")
    def test_chat_passes_explicit_temperature_override(self, chat_ollama_mock) -> None:
        provider = LLMProvider(self.config)

        provider.chat("gpt-oss:20b", temperature=0.7)

        _, kwargs = chat_ollama_mock.call_args
        self.assertTrue(kwargs["reasoning"])
        self.assertEqual(kwargs["temperature"], 0.7)


if __name__ == "__main__":
    unittest.main()
