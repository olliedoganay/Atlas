import unittest

from langchain_core.messages import HumanMessage, SystemMessage

from atlas_local.graph.context import GraphContext
from atlas_local.graph.nodes import _build_answer_messages, _latest_user_text


class ChatContextTests(unittest.TestCase):
    def test_cross_chat_memory_injects_minimal_context(self) -> None:
        state = {
            "messages": [HumanMessage(content="What is my name?")],
            "retrieved_memories": ["name: Atlas Tester"],
        }
        context = GraphContext(
            user_id="u1",
            thread_id="main",
            session_id="u1__main",
            chat_model="test-model",
            chat_temperature=0.2,
            cross_chat_memory=True,
        )

        messages = _build_answer_messages(state=state, runtime_context=context)

        self.assertIsInstance(messages[0], SystemMessage)
        self.assertIn("Relevant persistent memories", str(messages[0].content))

    def test_cross_chat_memory_disabled_keeps_raw_messages(self) -> None:
        user_message = HumanMessage(content="What is my name?")
        state = {
            "messages": [user_message],
            "retrieved_memories": ["name: Atlas Tester"],
        }
        context = GraphContext(
            user_id="u1",
            thread_id="main",
            session_id="u1__main",
            chat_model="test-model",
            chat_temperature=0.2,
            cross_chat_memory=False,
        )

        messages = _build_answer_messages(state=state, runtime_context=context)

        self.assertEqual(messages, [user_message])

    def test_thread_summary_replaces_compacted_prefix_in_prompt(self) -> None:
        state = {
            "messages": [
                HumanMessage(content="first"),
                HumanMessage(content="second"),
                HumanMessage(content="latest question"),
            ],
            "thread_summary": "- user asked about earlier setup",
            "compacted_message_count": 2,
        }
        context = GraphContext(
            user_id="u1",
            thread_id="main",
            session_id="u1__main",
            chat_model="test-model",
            chat_temperature=0.2,
            cross_chat_memory=False,
            effective_context_window=512,
        )

        messages = _build_answer_messages(state=state, runtime_context=context)

        self.assertIsInstance(messages[0], SystemMessage)
        self.assertIn("Conversation summary from earlier in this thread", str(messages[0].content))
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[-1].content, "latest question")

    def test_latest_user_text_ignores_image_blocks(self) -> None:
        state = {
            "messages": [
                HumanMessage(
                    content=[
                        {"type": "text", "text": "Describe this image"},
                        {"type": "image_url", "image_url": "data:image/png;base64,AAAA"},
                    ]
                )
            ]
        }

        self.assertEqual(_latest_user_text(state), "Describe this image")


if __name__ == "__main__":
    unittest.main()
