from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from ..browser.models import BrowserPlan, Citation
from ..browser.service import BrowserManager, BrowserResearchError
from ..config import AppConfig
from ..evolution.registry import RuntimeProfile
from ..llm import format_runtime_error
from ..memory.mem0_service import Mem0Service
from ..memory.models import MemoryRecord
from ..memory.policy import (
    adjudicate_candidate,
    candidates_to_claims,
    fallback_candidates_from_text,
    fallback_local_memory_candidates_from_text,
    normalize_claim_candidate,
)
from ..providers.base import ChatModelProvider
from ..reasoning.models import ReasoningReport
from ..reasoning.rules import evaluate_world_state
from ..runtime import read_prompt
from ..world.models import Claim, ClaimCandidate
from ..world.store import WorldStore
from .context import GraphContext
from .state import AgentState

LOGGER = logging.getLogger(__name__)
DIRECT_URL_RE = re.compile(r"(https?://\S+|file://\S+)", re.IGNORECASE)
BROWSER_KEYWORDS = ("latest", "recent", "today", "current", "source", "cite", "web", "browse")
HIGH_TRUST_RESEARCH_DOMAINS = (
    "arxiv.org",
    "anthropic.com",
    "deepmind.google",
    "google.com",
    "huggingface.co",
    "meta.com",
    "microsoft.com",
    "nature.com",
    "nvidia.com",
    "openai.com",
    "research.google",
    "science.org",
    "stanford.edu",
)
MEDIUM_TRUST_RESEARCH_DOMAINS = (
    "apnews.com",
    "reuters.com",
    "techcrunch.com",
    "theverge.com",
    "venturebeat.com",
    "wired.com",
)
DISFAVORED_RESEARCH_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "medium.com",
    "pinterest.com",
    "quora.com",
    "reddit.com",
    "tiktok.com",
    "x.com",
)


class GraphNodes:
    def __init__(
        self,
        config: AppConfig,
        llm_provider: ChatModelProvider,
        memory_service: Mem0Service,
        world_store: WorldStore,
        browser_manager: BrowserManager | None,
        profile: RuntimeProfile,
    ):
        self.config = config
        self.llm_provider = llm_provider
        self.memory_service = memory_service
        self.world_store = world_store
        self.browser_manager = browser_manager
        self.profile = profile

    def retrieve_memories(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        if not runtime.context.cross_chat_memory:
            return {"retrieved_memories": []}
        latest_user_message = _latest_user_text(state)
        if not latest_user_message:
            return {"retrieved_memories": []}

        retrieved: list[str] = []
        try:
            limit = max(1, round(self.config.memory_top_k * self.profile.retrieval_weight))
            stored = self.memory_service.search(
                latest_user_message,
                user_id=runtime.context.user_id,
                limit=limit,
            )
            retrieved = [item.memory for item in stored if item.memory]
        except Exception as exc:  # pragma: no cover - integration path
            LOGGER.warning("Memory retrieval failed: %s", exc)
        return {"retrieved_memories": retrieved}

    def retrieve_world_state(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        if not runtime.context.cross_chat_memory:
            return {
                "world_claims": [],
                "world_events": [],
                "reasoning_report": ReasoningReport.from_dict(None).to_dict(),
            }
        latest_user_message = _latest_user_text(state)
        claims = self.world_store.query_relevant_claims(
            user_id=runtime.context.user_id,
            query=latest_user_message,
            limit=12,
        )
        events = self.world_store.list_recent_events(user_id=runtime.context.user_id, limit=8)
        report = evaluate_world_state(claims, events)
        return {
            "world_claims": [claim.to_dict() for claim in claims],
            "world_events": [event.to_dict() for event in events],
            "reasoning_report": report.to_dict(),
        }

    def plan_browser_research(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        latest_user_message = _latest_user_text(state)
        direct_url = _extract_direct_url(latest_user_message)
        wants_browser = runtime.context.research_mode or bool(direct_url) or any(
            keyword in latest_user_message.lower() for keyword in BROWSER_KEYWORDS
        )
        if runtime.context.research_mode and self.profile.force_browser_for_research:
            wants_browser = True
        plan = BrowserPlan(
            use_browser=wants_browser,
            objective=latest_user_message,
            query=_normalize_browser_query(latest_user_message),
            direct_url=direct_url or "",
            max_steps=self.config.max_browser_steps,
        )
        return {"browser_plan": plan.to_dict()}

    def browser_loop(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        plan = BrowserPlan.from_dict(state.get("browser_plan"))
        if not plan.use_browser:
            return {"browser_trace": [], "citations": []}
        if self.browser_manager is None:
            raise BrowserResearchError("Browser subsystem is not available in chat-only mode.")

        citations: list[Citation] = []
        browser_error = ""
        try:
            if plan.direct_url:
                observation = self.browser_manager.open_page(plan.direct_url, thread_id=runtime.context.session_id)
                citations = self._citations_from_observation(
                    observation,
                    query=plan.query,
                    follow_links=plan.max_steps > 1,
                    thread_id=runtime.context.session_id,
                    follow_limit=min(self.profile.browser_result_limit, plan.max_steps - 1),
                )
            else:
                combined_candidates: list[dict[str, str]] = []
                last_error = ""
                for search_query in _expand_research_queries(plan.query):
                    try:
                        _, candidates = self.browser_manager.research_links(
                            search_query,
                            thread_id=runtime.context.session_id,
                            limit=max(plan.max_steps, self.profile.browser_result_limit),
                        )
                    except BrowserResearchError as exc:
                        last_error = str(exc)
                        LOGGER.debug("Browser query variant failed for %s: %s", search_query, exc)
                        continue
                    combined_candidates.extend(candidates)
                    if any(_research_domain_score(item.get("url", "")) >= 2 for item in combined_candidates):
                        break
                if not combined_candidates:
                    raise BrowserResearchError(last_error or "Atlas could not extract any usable search results.")
                ranked_candidates = sorted(
                    _dedupe_search_results(combined_candidates),
                    key=lambda item: _score_search_result(item, plan.query),
                    reverse=True,
                )
                citations = self._follow_search_results(
                    ranked_candidates,
                    thread_id=runtime.context.session_id,
                    query=plan.query,
                    limit=min(self.profile.browser_result_limit, plan.max_steps),
                )
                if not citations:
                    raise BrowserResearchError(
                        "Atlas opened the search page, but could not verify any external pages with usable evidence."
                    )
        except BrowserResearchError as exc:
            browser_error = str(exc)
            LOGGER.warning("Browser research blocked: %s", exc)
        except Exception as exc:
            browser_error = f"Browser research failed unexpectedly: {exc}"
            LOGGER.warning("Browser research failed: %s", exc)

        trace_path = self.browser_manager.latest_trace_path(thread_id=runtime.context.session_id)
        try:
            browser_trace = self.browser_manager.replay_trace(trace_path) if trace_path else []
        except RuntimeError as exc:
            LOGGER.warning("Browser trace replay failed: %s", exc)
            browser_trace = []
        verified_citations = [citation for citation in citations if _is_verified_citation(citation)]
        if plan.use_browser and not verified_citations:
            if not browser_error:
                browser_error = "Atlas completed the browser loop without producing verified citations."
            raise BrowserResearchError(browser_error)
        return {
            "browser_trace": browser_trace,
            "citations": [citation.to_dict() for citation in verified_citations[: self.profile.browser_result_limit]],
            "browser_error": browser_error,
        }

    def synthesize_answer_with_citations(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        citations = [Citation.from_dict(item) for item in state.get("citations", [])]
        if runtime.context.research_mode and citations:
            answer = _grounded_research_answer(
                question=_latest_user_text(state),
                citations=citations,
            )
            return {
                "messages": [AIMessage(content=answer)],
                "answer": answer,
            }
        messages = _build_answer_messages(state=state, runtime_context=runtime.context)
        try:
            response = self.llm_provider.chat(
                runtime.context.chat_model,
                temperature=runtime.context.chat_temperature,
            ).invoke(messages)
        except Exception as exc:  # pragma: no cover - integration path
            raise format_runtime_error(self.config, exc, chat_model=runtime.context.chat_model) from exc

        answer = _finalize_answer_text(str(response.content), state=state)
        return {
            "messages": [AIMessage(content=answer)],
            "answer": answer,
        }

    def extract_updates(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        if not runtime.context.cross_chat_memory:
            return {"update_candidates": []}
        latest_user_message = _latest_user_text(state)
        answer = state.get("answer", "")
        citations = [Citation.from_dict(item) for item in state.get("citations", [])]
        prompt = read_prompt(self.config.prompt_dir, "claim_extract.md")
        heuristic_candidates = candidates_to_claims(
            fallback_candidates_from_text(latest_user_message),
            source_kind="user",
        )

        if not runtime.context.research_mode:
            local_candidates = candidates_to_claims(
                fallback_local_memory_candidates_from_text(latest_user_message),
                source_kind="user",
            )
            return {"update_candidates": [candidate.to_dict() for candidate in local_candidates]}

        if latest_user_message.strip().endswith("?") and not heuristic_candidates and not citations:
            return {"update_candidates": []}

        candidates: list[ClaimCandidate] = []
        try:
            response = self.llm_provider.json_chat(runtime.context.chat_model).invoke(
                [
                    SystemMessage(content=prompt),
                    HumanMessage(
                        content=(
                            f"Latest user message:\n{latest_user_message}\n\n"
                            f"Assistant answer:\n{answer}\n\n"
                            f"Citations:\n{json.dumps([item.to_dict() for item in citations], ensure_ascii=False)}\n\n"
                            f"User ID: {runtime.context.user_id}\n"
                            "Extract canonical claim candidates only."
                        )
                    ),
                ]
            )
            candidates = _parse_claim_candidates(str(response.content))
        except Exception as exc:
            LOGGER.warning("JSON claim extraction failed, using heuristic fallback: %s", exc)

        if not candidates:
            candidates = heuristic_candidates + _browser_candidates_from_citations(citations)
        return {"update_candidates": [candidate.to_dict() for candidate in candidates]}

    def adjudicate_updates(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        existing_claims = [Claim.from_dict(item) for item in state.get("world_claims", [])]
        adjudicated = []
        for payload in state.get("update_candidates", []):
            candidate = ClaimCandidate.from_dict(payload)
            normalized = normalize_claim_candidate(candidate) or candidate
            decision = adjudicate_candidate(normalized, active_claims=existing_claims)
            adjudicated.append(
                {
                    "candidate": normalized.to_dict(),
                    "decision": decision.to_dict(),
                }
            )
        return {"adjudicated_updates": adjudicated}

    def persist(
        self,
        state: AgentState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, Any]:
        user_entity = self.world_store.ensure_entity(
            user_id=runtime.context.user_id,
            name="user",
            entity_type="user",
        )
        persisted_claims: list[Claim] = []

        for item in state.get("adjudicated_updates", []):
            candidate = ClaimCandidate.from_dict(item.get("candidate", {}))
            decision = item.get("decision", {})
            action = str(decision.get("action", "reject"))
            target_claim_id = decision.get("claim_id")

            if action == "reject":
                continue

            if action == "merge" and target_claim_id:
                self.world_store.record_event(
                    user_id=runtime.context.user_id,
                    event_type="claim.merge",
                    thread_id=runtime.context.thread_id,
                    payload={"target_claim_id": target_claim_id, "candidate": candidate.to_dict()},
                )
                continue

            if action == "deprecate" and target_claim_id:
                self.world_store.update_claim_status(str(target_claim_id), status="deprecated")
                self._delete_claim_memory(runtime.context.user_id, str(target_claim_id))
                continue

            source_id = None
            if candidate.source_url:
                source = self.world_store.add_source(
                    user_id=runtime.context.user_id,
                    url=candidate.source_url,
                    title=candidate.source_title or candidate.source_url,
                    supporting_text=candidate.supporting_text or candidate.source_text,
                    created_in_thread_id=runtime.context.thread_id,
                )
                source_id = source.source_id

            supersedes_claim_id = None
            if action == "revise" and target_claim_id:
                supersedes_claim_id = str(target_claim_id)
                self.world_store.update_claim_status(supersedes_claim_id, status="superseded")
                self._delete_claim_memory(runtime.context.user_id, supersedes_claim_id)

            claim = self.world_store.add_claim(
                user_id=runtime.context.user_id,
                entity_id=user_entity.entity_id,
                predicate=candidate.predicate,
                value=candidate.value,
                claim_type=candidate.claim_type,
                confidence=candidate.confidence,
                source_id=source_id,
                supersedes_claim_id=supersedes_claim_id,
                created_in_thread_id=runtime.context.thread_id,
            )
            persisted_claims.append(claim)
            self._sync_claim_memory(runtime.context.user_id, claim)
            self.world_store.record_event(
                user_id=runtime.context.user_id,
                event_type=f"claim.{action}",
                thread_id=runtime.context.thread_id,
                payload={"claim_id": claim.claim_id, "candidate": candidate.to_dict()},
            )

        fresh_claims = self.world_store.query_relevant_claims(
            user_id=runtime.context.user_id,
            query=_latest_user_text(state),
            limit=12,
        )
        fresh_events = self.world_store.list_recent_events(user_id=runtime.context.user_id, limit=8)
        report = evaluate_world_state(fresh_claims, fresh_events)
        return {
            "world_claims": [claim.to_dict() for claim in fresh_claims],
            "world_events": [event.to_dict() for event in fresh_events],
            "reasoning_report": report.to_dict(),
            "citations": [item.to_dict() if isinstance(item, Citation) else item for item in state.get("citations", [])],
        }

    def _follow_observation_links(
        self,
        links: list[dict[str, str]],
        *,
        thread_id: str,
        query: str,
        limit: int,
        ) -> list[Citation]:
        citations: list[Citation] = []
        for link in links:
            if len(citations) >= limit:
                break
            url = link.get("url", "")
            if not url or _is_disfavored_research_url(url):
                continue
            try:
                observation = self.browser_manager.open_page(url, thread_id=thread_id)
            except Exception as exc:
                LOGGER.debug("Skipping browser link %s: %s", url, exc)
                continue
            citations.append(
                Citation(
                    url=observation.url,
                    title=observation.title or link.get("text", ""),
                    quote=_quote_from_observation(observation.text_excerpt, query),
                    accessed_at=_now(),
                )
            )
        return citations

    def _follow_search_results(
        self,
        results: list[dict[str, str]],
        *,
        thread_id: str,
        query: str,
        limit: int,
    ) -> list[Citation]:
        citations: list[Citation] = []
        for result in results:
            if len(citations) >= limit:
                break
            url = result.get("url", "")
            if not url or _is_search_engine_url(url) or _is_disfavored_research_url(url):
                continue
            try:
                observation = self.browser_manager.open_page(url, thread_id=thread_id)
            except Exception as exc:
                LOGGER.debug("Skipping browser result %s: %s", url, exc)
                continue
            citation = Citation(
                url=observation.url,
                title=observation.title or result.get("title", ""),
                quote=_quote_from_observation(observation.text_excerpt, query, fallback=result.get("snippet", "")),
                accessed_at=_now(),
            )
            if _is_verified_citation(citation):
                citations.append(citation)
        return citations

    def _citations_from_observation(
        self,
        observation,
        *,
        query: str,
        follow_links: bool,
        thread_id: str,
        follow_limit: int,
    ) -> list[Citation]:
        citations = [
            Citation(
                url=observation.url,
                title=observation.title,
                quote=_quote_from_observation(observation.text_excerpt, query),
                accessed_at=_now(),
            )
        ]
        if follow_links:
            citations.extend(
                self._follow_observation_links(
                    observation.links,
                    thread_id=thread_id,
                    query=query,
                    limit=follow_limit,
                )
            )
        return citations

    def _sync_claim_memory(self, user_id: str, claim: Claim) -> None:
        record = MemoryRecord(claim_id=claim.claim_id, text=_render_claim_memory(claim))
        response = self.memory_service.add(
            record,
            user_id=user_id,
            metadata={
                "claim_id": claim.claim_id,
                "predicate": claim.predicate,
                "claim_type": claim.claim_type,
            },
        )
        mem0_results = response.get("results", [])
        mem0_id = ""
        if mem0_results:
            mem0_id = str(mem0_results[0].get("id", "")).strip()
        if mem0_id:
            self.world_store.upsert_memory_record(
                user_id=user_id,
                claim_id=claim.claim_id,
                mem0_id=mem0_id,
                text=record.text,
                status="active",
            )

    def _delete_claim_memory(self, user_id: str, claim_id: str) -> None:
        existing = self.world_store.get_memory_record(user_id=user_id, claim_id=claim_id)
        if not existing:
            return
        mem0_id = existing.get("mem0_id", "")
        if mem0_id:
            try:
                self.memory_service.delete(mem0_id)
            except Exception as exc:
                LOGGER.warning("Failed to delete Mem0 record %s: %s", mem0_id, exc)
        self.world_store.upsert_memory_record(
            user_id=user_id,
            claim_id=claim_id,
            mem0_id=mem0_id,
            text=existing.get("text", ""),
            status="inactive",
        )


def _latest_user_text(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return _message_text(message.content)
    return ""


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "\n".join(part for part in parts if part).strip()


def _build_answer_messages(*, state: AgentState, runtime_context: GraphContext) -> list[HumanMessage | AIMessage | SystemMessage]:
    memory_message = _memory_context_message(state=state, runtime_context=runtime_context)
    summary_message = _thread_summary_message(state)
    recent_messages = _recent_prompt_messages(state=state, runtime_context=runtime_context, memory_message=memory_message, summary_message=summary_message)
    prefix = [item for item in (memory_message, summary_message) if item is not None]
    return prefix + recent_messages


def _memory_context_message(*, state: AgentState, runtime_context: GraphContext) -> SystemMessage | None:
    if not getattr(runtime_context, "cross_chat_memory", True):
        return None

    sections: list[str] = []
    memories = [item for item in state.get("retrieved_memories", []) if item]
    claims = state.get("world_claims", [])
    report = ReasoningReport.from_dict(state.get("reasoning_report"))

    if memories:
        sections.append("Relevant persistent memories:\n" + _format_list(memories))
    if claims:
        sections.append("Relevant persistent facts:\n" + _format_world_claims(claims))
    if report.violations:
        sections.append("Consistency notes:\n" + report.to_prompt_text())

    if not sections:
        return None

    return SystemMessage(content="\n\n".join(sections))


def _thread_summary_message(state: AgentState) -> SystemMessage | None:
    summary = str(state.get("thread_summary", "") or "").strip()
    if not summary:
        return None
    return SystemMessage(content=f"Conversation summary from earlier in this thread:\n{summary}")


def _recent_prompt_messages(
    *,
    state: AgentState,
    runtime_context: GraphContext,
    memory_message: SystemMessage | None,
    summary_message: SystemMessage | None,
) -> list[BaseMessage]:
    messages = list(state.get("messages", []))
    compacted_count = max(0, min(int(state.get("compacted_message_count", 0) or 0), len(messages)))
    candidate_messages = messages[compacted_count:]
    effective_context_window = int(
        runtime_context.effective_context_window
        or state.get("detected_context_window")
        or 0
    )
    if effective_context_window <= 0:
        return candidate_messages

    prompt_budget = max(1024, int(effective_context_window * 0.72))
    reserved_tokens = _estimate_message_tokens(memory_message) + _estimate_message_tokens(summary_message) + 64
    available_tokens = max(256, prompt_budget - reserved_tokens)

    selected: list[BaseMessage] = []
    consumed = 0
    for message in reversed(candidate_messages):
        message_tokens = _estimate_message_tokens(message)
        if selected and consumed + message_tokens > available_tokens:
            break
        selected.insert(0, message)
        consumed += message_tokens
        if len(selected) >= 12 and consumed >= available_tokens:
            break

    if not selected and candidate_messages:
        return [candidate_messages[-1]]
    return selected


def _estimate_message_tokens(message: BaseMessage | None) -> int:
    if message is None:
        return 0
    return _estimate_content_tokens(message.content) + 8


def _estimate_content_tokens(content: Any) -> int:
    if isinstance(content, str):
        return max(1, len(content) // 4)
    if isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, str):
                total += max(1, len(item) // 4)
            elif isinstance(item, dict):
                item_type = str(item.get("type", "")).strip().lower()
                if item_type == "text":
                    total += max(1, len(str(item.get("text", ""))) // 4)
                elif item_type == "image_url":
                    total += 256
        return max(total, 1)
    return max(1, len(str(content)) // 4)


def _format_list(values: list[str]) -> str:
    if not values:
        return "- none"
    return "\n".join(f"- {item}" for item in values)


def _format_world_claims(values: list[dict[str, Any]]) -> str:
    if not values:
        return "- none"
    return "\n".join(
        f"- {item.get('predicate', 'claim')}: {item.get('value', '')} [{item.get('claim_type', 'claim')}]"
        for item in values
    )


def _format_browser_context(trace: list[dict[str, Any]]) -> str:
    if not trace:
        return "- none"
    rendered = []
    for item in trace[-6:]:
        action = item.get("action", {})
        observation = item.get("observation") or {}
        rendered.append(
            f"- {action.get('tool', 'browser')} -> {observation.get('title', '')} {observation.get('url', '')}".strip()
        )
    return "\n".join(rendered)


def _format_citations(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return "- none"
    return "\n".join(
        f"- {item.get('title', 'source')}: {item.get('quote', '')} ({item.get('url', '')})"
        for item in citations
    )


def _extract_direct_url(text: str) -> str:
    match = DIRECT_URL_RE.search(text)
    return match.group(1) if match else ""


def _parse_claim_candidates(payload: str) -> list[ClaimCandidate]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return []

    raw_candidates = parsed if isinstance(parsed, list) else parsed.get("candidates", [])
    results: list[ClaimCandidate] = []
    for item in raw_candidates:
        if isinstance(item, dict):
            results.append(ClaimCandidate.from_dict(item))
    return results


def _browser_candidates_from_citations(citations: list[Citation]) -> list[ClaimCandidate]:
    candidates: list[ClaimCandidate] = []
    for citation in citations[:2]:
        if not citation.quote:
            continue
        candidates.append(
            ClaimCandidate(
                entity_name="research",
                entity_type="topic",
                predicate="finding",
                value=citation.quote,
                claim_type="research_finding",
                confidence=0.74,
                source_kind="browser",
                source_text=citation.quote,
                source_url=citation.url,
                source_title=citation.title,
                supporting_text=citation.quote,
            )
        )
    return candidates


def _render_claim_memory(claim: Claim) -> str:
    return f"[{claim.claim_type}] {claim.predicate}: {claim.value}"


def _quote_from_observation(text: str, query: str, *, fallback: str = "") -> str:
    query_terms = [token.lower() for token in query.split() if len(token) > 2]
    segments = [segment.strip() for segment in text.split(". ") if segment.strip()]
    matches = []
    for segment in segments:
        lowered = segment.lower()
        if any(term in lowered for term in query_terms):
            matches.append(segment)
    if matches:
        return " ".join(matches[:2])[:280]
    if segments:
        return segments[0][:280]
    return fallback[:280]


def _is_weak_answer(answer: str) -> bool:
    stripped = answer.strip()
    return len(stripped) < 20


def _fallback_answer(*, citations: list[Citation], world_claims: list[dict[str, Any]]) -> str:
    quote_lines = [item.quote.strip() for item in citations if item.quote.strip()]
    if quote_lines:
        summary = " ".join(dict.fromkeys(quote_lines))
        return f"Based on the gathered sources: {summary}"
    if world_claims:
        claims_text = "; ".join(
            f"{item.get('predicate', 'claim')}: {item.get('value', '')}" for item in world_claims[:3]
        )
        return f"Based on the current canonical world state: {claims_text}"
    return "I could not synthesize a strong answer from the available context."


def _strip_empty_sources_footer(answer: str) -> str:
    cleaned = re.sub(r"\n{0,2}Sources:\s*(-\s*)?(none|n/?a)\s*$", "", answer.strip(), flags=re.IGNORECASE)
    return cleaned.strip()


def _finalize_answer_text(answer: str, *, state: AgentState) -> str:
    finalized = answer.strip()
    if state.get("citations") and _is_weak_answer(finalized):
        finalized = _fallback_answer(
            citations=[Citation.from_dict(item) for item in state.get("citations", [])],
            world_claims=state.get("world_claims", []),
        )
    if state.get("citations") and "Sources:" not in finalized:
        sources = "\n".join(
            f"- {item.get('title', 'source')} ({item.get('url', '')})"
            for item in state.get("citations", [])
        )
        finalized = f"{finalized}\n\nSources:\n{sources}"
    if not state.get("citations"):
        finalized = _strip_empty_sources_footer(finalized)
    return finalized


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _score_search_result(item: dict[str, str], query: str) -> tuple[int, int, int]:
    haystack = " ".join([item.get("title", ""), item.get("snippet", ""), item.get("display_url", "")]).lower()
    query_terms = [term.lower() for term in re.findall(r"\w+", query) if len(term) > 2]
    score = sum(haystack.count(term) for term in query_terms)
    title_score = sum(item.get("title", "").lower().count(term) for term in query_terms)
    domain_score = _research_domain_score(item.get("url", ""))
    return (domain_score, title_score, score)


def _is_verified_citation(citation: Citation) -> bool:
    return bool(
        citation.url
        and citation.title
        and citation.quote
        and not _is_search_engine_url(citation.url)
        and not _is_disfavored_research_url(citation.url)
    )


def _is_search_engine_url(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return any(
        engine in domain
        for engine in ("bing.com", "duckduckgo.com", "search.brave.com", "google.com")
    )


def _normalize_browser_query(value: str) -> str:
    normalized = value.strip()
    patterns = (
        r"^(please\s+)?search\s+(the\s+)?web\s+(for|about)\s+",
        r"^(please\s+)?browse\s+(the\s+)?web\s+(for|about)\s+",
        r"^(please\s+)?look\s+up\s+",
        r"^(please\s+)?find\s+",
    )
    for pattern in patterns:
        normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)
    return normalized.strip() or value.strip()


def _expand_research_queries(query: str) -> list[str]:
    base = query.strip()
    if not base:
        return [query]
    variants = [
        base,
        f"{base} site:arxiv.org",
        f"{base} site:openai.com",
        f"{base} site:deepmind.google",
        f"{base} site:anthropic.com",
        f"{base} site:research.google",
        f"{base} site:microsoft.com",
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for item in variants:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _dedupe_search_results(results: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in results:
        url = item.get("url", "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)
    return deduped


def _grounded_research_answer(*, question: str, citations: list[Citation]) -> str:
    lines = ["Atlas verified these browser-grounded findings:"]
    seen: set[tuple[str, str]] = set()
    kept: list[Citation] = []
    for citation in citations:
        quote = _clean_text(citation.quote)
        key = (citation.url, quote)
        if not quote or key in seen:
            continue
        seen.add(key)
        kept.append(
            Citation(
                url=citation.url,
                title=_clean_text(citation.title) or citation.url,
                quote=quote,
                accessed_at=citation.accessed_at,
            )
        )
        if len(kept) >= 4:
            break

    if question.strip():
        lines.append("")
        lines.append(f"Question: {question.strip()}")

    lines.append("")
    for citation in kept:
        lines.append(f"- {citation.title}: {citation.quote}")

    lines.append("")
    lines.append("Sources:")
    for citation in kept:
        lines.append(f"- {citation.title} ({citation.url})")
    return "\n".join(lines).strip()


def _clean_text(value: str) -> str:
    compact = " ".join(value.replace("\n", " ").replace("\r", " ").split())
    return compact.replace("<br>", " ").replace("|", " ").strip()


def _is_disfavored_research_url(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return any(
        domain == blocked or domain.endswith(f".{blocked}")
        for blocked in DISFAVORED_RESEARCH_DOMAINS
    )


def _research_domain_score(url: str) -> int:
    if _is_search_engine_url(url):
        return -5
    if _is_disfavored_research_url(url):
        return -4
    domain = urlparse(url).netloc.lower()
    if any(domain == item or domain.endswith(f".{item}") for item in HIGH_TRUST_RESEARCH_DOMAINS):
        return 3
    if any(domain == item or domain.endswith(f".{item}") for item in MEDIUM_TRUST_RESEARCH_DOMAINS):
        return 2
    if domain:
        return 1
    return 0
