from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from ..config import AppConfig, load_config
from ..llm import LLMProvider
from ..memory.mem0_service import Mem0Service
from ..providers.base import ChatModelProvider
from ..security import open_application_sqlite
from ..session import scoped_thread_id
from ..web_search import OllamaWebSearchService
from .context import GraphContext
from .nodes import GraphNodes
from .state import AgentState

PRE_SYNTHESIS_NODE_SEQUENCE = ("retrieve_memories", "retrieve_web")
POST_SYNTHESIS_NODE_SEQUENCE = ("extract_updates", "persist")


@dataclass
class AgentApplication:
    config: AppConfig
    graph: Any
    llm_provider: ChatModelProvider
    nodes: GraphNodes
    memory_service: Mem0Service
    _stack: ExitStack

    def ask(
        self,
        prompt: str,
        *,
        user_id: str,
        thread_id: str,
        chat_model: str | None = None,
        chat_temperature: float | None = None,
        reasoning_mode: str | None = "on",
        web_search_enabled: bool = False,
        cross_chat_memory: bool = True,
        auto_compact_long_chats: bool = True,
        effective_context_window: int | None = None,
    ) -> dict:
        session_id = scoped_thread_id(user_id, thread_id)
        return self.graph.invoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"configurable": {"thread_id": session_id}},
            context=GraphContext(
                user_id=user_id,
                thread_id=thread_id,
                session_id=session_id,
                chat_model=chat_model or self.config.chat_model,
                chat_temperature=chat_temperature,
                reasoning_mode=reasoning_mode,
                web_search_enabled=web_search_enabled,
                cross_chat_memory=cross_chat_memory,
                auto_compact_long_chats=auto_compact_long_chats,
                effective_context_window=effective_context_window,
            ),
        )

    def list_memories(self, *, user_id: str, limit: int = 20):
        return self.memory_service.list(user_id=user_id, limit=limit)

    def close(self) -> None:
        try:
            self.memory_service.close()
        finally:
            self._stack.close()

    def __enter__(self) -> "AgentApplication":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def pre_synthesis_node_sequence(*, include_browser: bool | None = None) -> tuple[str, ...]:
    return PRE_SYNTHESIS_NODE_SEQUENCE


def post_synthesis_node_sequence() -> tuple[str, ...]:
    return POST_SYNTHESIS_NODE_SEQUENCE


def execution_node_sequence(*, include_browser: bool | None = None) -> tuple[str, ...]:
    return PRE_SYNTHESIS_NODE_SEQUENCE + ("synthesize_answer",) + POST_SYNTHESIS_NODE_SEQUENCE


def build_chat_application(config: AppConfig | None = None) -> AgentApplication:
    resolved = config or load_config()
    stack = ExitStack()
    checkpoint_conn = open_application_sqlite(
        resolved.langgraph_checkpoint_db,
        data_dir=resolved.data_dir,
        check_same_thread=False,
    )
    stack.callback(checkpoint_conn.close)
    checkpointer = SqliteSaver(checkpoint_conn)
    checkpointer.setup()

    llm_provider = LLMProvider(resolved)
    memory_service = Mem0Service(resolved)
    web_search_service = OllamaWebSearchService(resolved)
    nodes = GraphNodes(resolved, llm_provider, memory_service, web_search_service)
    graph = _compile_graph(nodes, checkpointer=checkpointer)

    return AgentApplication(
        config=resolved,
        graph=graph,
        llm_provider=llm_provider,
        nodes=nodes,
        memory_service=memory_service,
        _stack=stack,
    )


def build_application(config: AppConfig | None = None) -> AgentApplication:
    return build_chat_application(config)


def _compile_graph(
    nodes: GraphNodes,
    *,
    checkpointer: SqliteSaver,
):
    builder = StateGraph(AgentState, context_schema=GraphContext)
    sequence = execution_node_sequence()
    for node_name in sequence:
        builder.add_node(node_name, getattr(nodes, node_name))

    previous = START
    for node_name in sequence:
        builder.add_edge(previous, node_name)
        previous = node_name
    builder.add_edge(previous, END)
    return builder.compile(checkpointer=checkpointer)
