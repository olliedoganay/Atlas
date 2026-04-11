import unittest
from types import SimpleNamespace

from atlas_local.api_service import _ThinkingStreamParser, _extract_chunk_stream_parts


class ThinkingStreamTests(unittest.TestCase):
    def test_think_tags_are_split_from_answer(self):
        parser = _ThinkingStreamParser()
        answer_a, thinking_a = _extract_chunk_stream_parts(SimpleNamespace(content="<think>first"), parser)
        answer_b, thinking_b = _extract_chunk_stream_parts(SimpleNamespace(content=" pass</think>answer"), parser)
        tail_answer, tail_thinking = parser.flush()

        self.assertEqual(answer_a, "")
        self.assertEqual(thinking_a, "first")
        self.assertEqual(answer_b, "answer")
        self.assertEqual(thinking_b, " pass")
        self.assertEqual(tail_answer, "")
        self.assertEqual(tail_thinking, "")

    def test_reasoning_content_is_extracted_from_additional_kwargs(self):
        parser = _ThinkingStreamParser()
        chunk = SimpleNamespace(content="final", additional_kwargs={"reasoning_content": "scratch"})
        answer, thinking = _extract_chunk_stream_parts(chunk, parser)
        self.assertEqual(answer, "final")
        self.assertEqual(thinking, "scratch")


if __name__ == "__main__":
    unittest.main()
