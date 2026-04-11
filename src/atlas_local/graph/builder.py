from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from ..benchmarks.runner import BenchmarkRunner
from ..browser.service import BrowserManager
from ..config import AppConfig, load_config
from ..evolution.propose import propose_profile_improvement
from ..evolution.registry import (
    ImprovementProposal,
    RuntimeProfile,
    load_active_profile,
    promote_profile,
    save_profile,
)
from ..llm import LLMProvider
from ..memory.mem0_service import Mem0Service
from ..providers.base import ChatModelProvider
from ..session import scoped_thread_id
from ..world.store import WorldStore
from .context import GraphContext
from .nodes import GraphNodes
from .state import AgentState

PRE_SYNTHESIS_NODE_SEQUENCE = (
    "retrieve_memories",
    "retrieve_world_state",
)
BROWSER_NODE_SEQUENCE = (
    "plan_browser_research",
    "browser_loop",
)
POST_SYNTHESIS_NODE_SEQUENCE = (
    "extract_updates",
    "adjudicate_updates",
    "persist",
)


@dataclass
class AgentApplication:
    config: AppConfig
    graph: Any
    llm_provider: ChatModelProvider
    nodes: GraphNodes
    memory_service: Mem0Service
    world_store: WorldStore
    browser_manager: BrowserManager | None
    profile: RuntimeProfile
    benchmark_runner: BenchmarkRunner | None
    _stack: ExitStack

    def ask(
        self,
        prompt: str,
        *,
        user_id: str,
        thread_id: str,
        research_mode: bool = False,
        chat_model: str | None = None,
        chat_temperature: float | None = None,
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
                research_mode=research_mode,
                cross_chat_memory=cross_chat_memory,
                auto_compact_long_chats=auto_compact_long_chats,
                effective_context_window=effective_context_window,
            ),
        )

    def research(
        self,
        prompt: str,
        *,
        user_id: str,
        thread_id: str,
        chat_model: str | None = None,
        chat_temperature: float | None = None,
        cross_chat_memory: bool = True,
        auto_compact_long_chats: bool = True,
        effective_context_window: int | None = None,
    ) -> dict:
        return self.ask(
            prompt,
            user_id=user_id,
            thread_id=thread_id,
            research_mode=True,
            chat_model=chat_model,
            chat_temperature=chat_temperature,
            cross_chat_memory=cross_chat_memory,
            auto_compact_long_chats=auto_compact_long_chats,
            effective_context_window=effective_context_window,
        )

    def list_memories(self, *, user_id: str, limit: int = 20):
        return self.memory_service.list(user_id=user_id, limit=limit)

    def world_inspect(self, *, user_id: str, limit: int = 20) -> dict[str, object]:
        return self.world_store.inspect_user(user_id=user_id, limit=limit)

    def browser_open(self, url: str, *, thread_id: str) -> dict[str, object]:
        if self.browser_manager is None:
            raise RuntimeError("Browser subsystem is not available in chat-only mode.")
        return self.browser_manager.open_page(url, thread_id=thread_id).to_dict()

    def browser_replay(self, trace_path: str) -> list[dict[str, object]]:
        if self.browser_manager is None:
            raise RuntimeError("Browser subsystem is not available in chat-only mode.")
        return self.browser_manager.replay_trace(trace_path)

    def run_benchmark(self, *, suite: str, profile_name: str | None = None):
        if self.benchmark_runner is None:
            raise RuntimeError("Benchmark subsystem is not available in chat-only mode.")
        profile = load_active_profile(self.config, profile_name=profile_name)
        return self.benchmark_runner.run(app=self, suite=suite, profile=profile)

    def load_benchmark_report(self, run_id_or_path: str):
        if self.benchmark_runner is None:
            raise RuntimeError("Benchmark subsystem is not available in chat-only mode.")
        return self.benchmark_runner.load(run_id_or_path)

    def propose_improvement(self, *, run_id_or_path: str, profile_name: str | None = None) -> ImprovementProposal:
        if self.benchmark_runner is None:
            raise RuntimeError("Evolution subsystem is not available in chat-only mode.")
        profile = load_active_profile(self.config, profile_name=profile_name)
        run = self.load_benchmark_report(run_id_or_path)
        proposal = propose_profile_improvement(run, profile)
        save_profile(self.config, proposal.candidate_profile)
        return proposal

    def evaluate_profile(self, *, suite: str, profile_name: str):
        if self.benchmark_runner is None:
            raise RuntimeError("Evolution subsystem is not available in chat-only mode.")
        return self.run_benchmark(suite=suite, profile_name=profile_name)

    def promote_profile(self, *, profile_name: str) -> str:
        return str(promote_profile(self.config, profile_name))

    def close(self) -> None:
        try:
            if self.browser_manager is not None:
                self.browser_manager.close()
        finally:
            try:
                self.memory_service.close()
            finally:
                self._stack.close()

    def __enter__(self) -> "AgentApplication":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def pre_synthesis_node_sequence(*, include_browser: bool) -> tuple[str, ...]:
    return PRE_SYNTHESIS_NODE_SEQUENCE + (BROWSER_NODE_SEQUENCE if include_browser else ())


def post_synthesis_node_sequence() -> tuple[str, ...]:
    return POST_SYNTHESIS_NODE_SEQUENCE


def execution_node_sequence(*, include_browser: bool) -> tuple[str, ...]:
    return pre_synthesis_node_sequence(include_browser=include_browser) + (
        "synthesize_answer_with_citations",
    ) + post_synthesis_node_sequence()


def build_application(
    config: AppConfig | None = None,
    *,
    profile_name: str | None = None,
) -> AgentApplication:
    resolved = config or load_config()
    profile = load_active_profile(resolved, profile_name=profile_name)
    stack = ExitStack()
    checkpointer = stack.enter_context(
        SqliteSaver.from_conn_string(str(resolved.langgraph_checkpoint_db))
    )
    checkpointer.setup()

    llm_provider = LLMProvider(resolved)
    memory_service = Mem0Service(resolved)
    world_store = WorldStore(resolved)
    browser_manager = BrowserManager(resolved)
    nodes = GraphNodes(resolved, llm_provider, memory_service, world_store, browser_manager, profile)
    graph = _compile_graph(nodes, checkpointer=checkpointer, include_browser=True)
    return AgentApplication(
        config=resolved,
        graph=graph,
        llm_provider=llm_provider,
        nodes=nodes,
        memory_service=memory_service,
        world_store=world_store,
        browser_manager=browser_manager,
        profile=profile,
        benchmark_runner=BenchmarkRunner(resolved),
        _stack=stack,
    )


def build_chat_application(
    config: AppConfig | None = None,
    *,
    profile_name: str | None = None,
) -> AgentApplication:
    resolved = config or load_config()
    profile = load_active_profile(resolved, profile_name=profile_name)
    stack = ExitStack()
    checkpointer = stack.enter_context(
        SqliteSaver.from_conn_string(str(resolved.langgraph_checkpoint_db))
    )
    checkpointer.setup()

    llm_provider = LLMProvider(resolved)
    memory_service = Mem0Service(resolved)
    world_store = WorldStore(resolved)
    nodes = GraphNodes(resolved, llm_provider, memory_service, world_store, None, profile)
    graph = _compile_graph(nodes, checkpointer=checkpointer, include_browser=False)

    return AgentApplication(
        config=resolved,
        graph=graph,
        llm_provider=llm_provider,
        nodes=nodes,
        memory_service=memory_service,
        world_store=world_store,
        browser_manager=None,
        profile=profile,
        benchmark_runner=None,
        _stack=stack,
    )


def _compile_graph(
    nodes: GraphNodes,
    *,
    checkpointer: SqliteSaver,
    include_browser: bool,
):
    builder = StateGraph(AgentState, context_schema=GraphContext)
    sequence = execution_node_sequence(include_browser=include_browser)
    for node_name in sequence:
        builder.add_node(node_name, getattr(nodes, node_name))

    previous = START
    for node_name in sequence:
        builder.add_edge(previous, node_name)
        previous = node_name
    builder.add_edge(previous, END)
    return builder.compile(checkpointer=checkpointer)
