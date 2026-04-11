from __future__ import annotations

import json
import base64
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

from ..config import AppConfig
from .models import BrowserAction, BrowserObservation, BrowserTraceEntry, Citation
from .policy import BrowserPolicy

try:
    from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
except ImportError:  # pragma: no cover - runtime dependency path
    Browser = BrowserContext = Page = object  # type: ignore[assignment,misc]
    sync_playwright = None


@dataclass
class _BrowserSession:
    context: BrowserContext
    page: Page
    trace_path: Path


class BrowserResearchError(RuntimeError):
    pass


class BrowserManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.policy = BrowserPolicy(config.web_allowlist, config.web_blocklist)
        self._playwright = None
        self._browser: Browser | None = None
        self._sessions: dict[str, _BrowserSession] = {}
        self._owner_thread_id: int | None = None
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            current_thread_id = threading.get_ident()
            self._reset_runtime(close_handles=self._owner_thread_id in {None, current_thread_id})

    def search_web(self, query: str, *, thread_id: str) -> BrowserObservation:
        if self.config.search_provider == "yahoo_browser":
            return self._search_yahoo(query, thread_id=thread_id)
        if self.config.search_provider == "bing_browser":
            return self._search_bing(query, thread_id=thread_id)
        raise BrowserResearchError(
            f"Unsupported SEARCH_PROVIDER {self.config.search_provider!r}. "
            "This implementation currently supports yahoo_browser and bing_browser only."
        )

    def open_page(
        self,
        url: str,
        *,
        thread_id: str,
        action_name: str = "open_page",
        action_value: str = "",
    ) -> BrowserObservation:
        self.policy.check(action_name, url)
        session = self._get_session(thread_id)
        session.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        observation = self._snapshot_page(session.page)
        self._record_trace(
            thread_id,
            BrowserTraceEntry(
                action=BrowserAction(tool=action_name, value=action_value or url),
                observation=observation,
            ),
        )
        return observation

    def research_links(self, query: str, *, thread_id: str, limit: int) -> tuple[BrowserObservation, list[dict[str, str]]]:
        observation = self.search_web(query, thread_id=thread_id)
        results = observation.results[:limit]
        if not results:
            raise BrowserResearchError("The browser opened the search page but no usable result cards were extracted.")
        return observation, results

    def extract_text(self, *, thread_id: str) -> BrowserObservation:
        session = self._get_session(thread_id)
        observation = self._snapshot_page(session.page)
        self._record_trace(
            thread_id,
            BrowserTraceEntry(action=BrowserAction(tool="extract_text"), observation=observation),
        )
        return observation

    def get_links(self, *, thread_id: str) -> list[dict[str, str]]:
        return self.extract_text(thread_id=thread_id).links

    def click(self, selector: str, *, thread_id: str) -> BrowserObservation:
        session = self._get_session(thread_id)
        self.policy.check("click", session.page.url)
        session.page.locator(selector).first.click(timeout=5000)
        observation = self._snapshot_page(session.page)
        self._record_trace(
            thread_id,
            BrowserTraceEntry(
                action=BrowserAction(tool="click", selector=selector),
                observation=observation,
            ),
        )
        return observation

    def type(self, selector: str, value: str, *, thread_id: str) -> BrowserObservation:
        session = self._get_session(thread_id)
        self.policy.check("type", session.page.url)
        session.page.locator(selector).first.fill(value, timeout=5000)
        observation = self._snapshot_page(session.page)
        self._record_trace(
            thread_id,
            BrowserTraceEntry(
                action=BrowserAction(tool="type", selector=selector, value=value),
                observation=observation,
            ),
        )
        return observation

    def go_back(self, *, thread_id: str) -> BrowserObservation:
        session = self._get_session(thread_id)
        session.page.go_back(wait_until="domcontentloaded", timeout=15000)
        observation = self._snapshot_page(session.page)
        self._record_trace(
            thread_id,
            BrowserTraceEntry(action=BrowserAction(tool="go_back"), observation=observation),
        )
        return observation

    def screenshot(self, *, thread_id: str, name: str = "page") -> str:
        session = self._get_session(thread_id)
        directory = self._thread_dir(thread_id)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = directory / f"{name}-{stamp}.png"
        session.page.screenshot(path=str(path), full_page=True)
        self._record_trace(
            thread_id,
            BrowserTraceEntry(
                action=BrowserAction(tool="screenshot", value=str(path)),
                observation=BrowserObservation(
                    url=session.page.url,
                    title=session.page.title(),
                    text_excerpt="",
                    links=[],
                    screenshot_path=str(path),
                ),
            ),
        )
        return str(path)

    def quote_source(self, *, thread_id: str, query: str) -> Citation:
        observation = self.extract_text(thread_id=thread_id)
        return Citation(
            url=observation.url,
            title=observation.title,
            quote=_extract_quote(observation.text_excerpt, query),
            accessed_at=datetime.now(UTC).isoformat(),
        )

    def replay_trace(self, trace_path: str) -> list[dict[str, object]]:
        path = Path(trace_path)
        if not path.exists():
            raise RuntimeError(f"Browser trace not found: {trace_path}")
        entries: list[dict[str, object]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def latest_trace_path(self, *, thread_id: str) -> str:
        session = self._sessions.get(thread_id)
        if session and session.trace_path.exists():
            return str(session.trace_path)
        directory = self._thread_dir(thread_id)
        if not directory.exists():
            return ""
        candidates = sorted(directory.glob("*.jsonl"))
        return str(candidates[-1]) if candidates else ""

    def _search_bing(self, query: str, *, thread_id: str) -> BrowserObservation:
        search_url = f"https://www.bing.com/search?q={quote_plus(query)}&setlang=en-US&cc=us"
        self.policy.check("search_web", search_url)
        session = self._get_session(thread_id)
        session.page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        try:
            session.page.wait_for_selector("li.b_algo, div.b_no", timeout=15000)
        except Exception:
            pass
        observation = self._snapshot_page(session.page)
        self._record_trace(
            thread_id,
            BrowserTraceEntry(
                action=BrowserAction(tool="search_web", value=query),
                observation=observation,
            ),
        )
        challenge_reason = _bing_challenge_reason(observation)
        if challenge_reason:
            raise BrowserResearchError(challenge_reason)
        if not observation.results:
            raise BrowserResearchError("Bing loaded, but Atlas could not extract any result cards from the page.")
        return observation

    def _search_yahoo(self, query: str, *, thread_id: str) -> BrowserObservation:
        search_url = f"https://search.yahoo.com/search?p={quote_plus(query)}"
        self.policy.check("search_web", search_url)
        session = self._get_session(thread_id)
        session.page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        try:
            session.page.wait_for_selector("div.algo, div#results", timeout=15000)
        except Exception:
            pass
        observation = self._snapshot_page(session.page)
        self._record_trace(
            thread_id,
            BrowserTraceEntry(
                action=BrowserAction(tool="search_web", value=query),
                observation=observation,
            ),
        )
        challenge_reason = _yahoo_challenge_reason(observation)
        if challenge_reason:
            raise BrowserResearchError(challenge_reason)
        if not observation.results:
            raise BrowserResearchError("Yahoo loaded, but Atlas could not extract any result cards from the page.")
        return observation

    def _get_session(self, thread_id: str) -> _BrowserSession:
        with self._lock:
            current_thread_id = threading.get_ident()
            if self._owner_thread_id is not None and self._owner_thread_id != current_thread_id:
                # Playwright handles are thread-affine. If the browser was created on a
                # different thread, drop those references and start a fresh runtime here.
                self._reset_runtime(close_handles=False)

            session = self._sessions.get(thread_id)
            if session is not None:
                return session

            if sync_playwright is None:
                raise RuntimeError(
                    "Playwright is not installed. Run `pip install -r requirements.txt` and "
                    "`python -m playwright install chromium`."
                )

            if self._playwright is None:
                self._playwright = sync_playwright().start()
                self._owner_thread_id = current_thread_id
            if self._browser is None:
                self._browser = self._playwright.chromium.launch(headless=self.config.browser_headless)
                self._owner_thread_id = current_thread_id

            trace_dir = self._thread_dir(thread_id)
            trace_dir.mkdir(parents=True, exist_ok=True)
            trace_path = trace_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
            context = self._browser.new_context(locale="en-US")
            page = context.new_page()
            session = _BrowserSession(context=context, page=page, trace_path=trace_path)
            self._sessions[thread_id] = session
            return session

    def _reset_runtime(self, *, close_handles: bool) -> None:
        if close_handles:
            for session in self._sessions.values():
                close = getattr(session.context, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            if self._browser is not None:
                try:
                    self._browser.close()
                except Exception:
                    pass
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
        self._sessions.clear()
        self._browser = None
        self._playwright = None
        self._owner_thread_id = None

    def _thread_dir(self, thread_id: str) -> Path:
        safe_thread = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in thread_id)
        return self.config.browser_storage_dir / safe_thread

    def _record_trace(self, thread_id: str, entry: BrowserTraceEntry) -> None:
        session = self._get_session(thread_id)
        session.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with session.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def _snapshot_page(self, page: Page) -> BrowserObservation:
        title = page.title()
        text = page.locator("body").inner_text(timeout=5000)
        links = page.locator("a[href]").evaluate_all(
            """elements => elements.slice(0, 12).map(el => ({
                text: (el.innerText || '').trim(),
                url: el.href || ''
            })).filter(item => item.url)"""
        )
        cleaned_links = []
        seen: set[str] = set()
        for item in links:
            url = str(item.get("url", "")).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            cleaned_links.append(
                {
                    "text": str(item.get("text", "")).strip()[:120],
                    "url": url,
                }
            )
        results = _extract_search_results(page)
        return BrowserObservation(
            url=page.url,
            title=title.strip(),
            text_excerpt=" ".join(text.split())[:3000],
            links=cleaned_links,
            results=results,
        )


def _extract_quote(text: str, query: str) -> str:
    compact = " ".join(text.split())
    if not compact:
        return ""

    query_terms = [term.lower() for term in query.split() if len(term) > 2]
    segments = [segment.strip() for segment in compact.split(". ") if segment.strip()]
    matches = []
    for segment in segments:
        lowered = segment.lower()
        if any(term in lowered for term in query_terms):
            matches.append(segment)
    if matches:
        return " ".join(matches[:2])[:280]
    return segments[0][:280]


def _extract_bing_results(page: Page) -> list[dict[str, str]]:
    items = page.locator("li.b_algo").evaluate_all(
        """elements => elements.slice(0, 8).map(el => {
            const anchor = el.querySelector('h2 a');
            const snippet = el.querySelector('.b_caption p');
            const cite = el.querySelector('cite');
            return {
                title: (anchor?.innerText || '').trim(),
                url: anchor?.href || '',
                snippet: (snippet?.innerText || '').trim(),
                display_url: (cite?.innerText || '').trim(),
            };
        })"""
    )
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        raw_url = str(item.get("url", "")).strip()
        resolved_url = _resolve_bing_url(raw_url)
        title = str(item.get("title", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        display_url = str(item.get("display_url", "")).strip()
        if not resolved_url or not title or resolved_url in seen:
            continue
        seen.add(resolved_url)
        results.append(
            {
                "title": title,
                "url": resolved_url,
                "snippet": snippet,
                "display_url": display_url,
            }
        )
    return results


def _extract_yahoo_results(page: Page) -> list[dict[str, str]]:
    items = page.locator("div.algo").evaluate_all(
        """elements => elements.slice(0, 8).map(el => {
            const anchor = el.querySelector('.compTitle h3 a, .compTitle a');
            const titleNode = el.querySelector('.compTitle h3');
            const snippet = el.querySelector('.compText p');
            const sourceNode = el.querySelector('.compTitle .fc-141414');
            return {
                title: (titleNode?.innerText || anchor?.innerText || '').trim(),
                url: anchor?.href || '',
                snippet: (snippet?.innerText || '').trim(),
                display_url: (sourceNode?.innerText || '').trim(),
            };
        })"""
    )
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        display_url = str(item.get("display_url", "")).strip()
        if not url or not title or url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "display_url": display_url,
            }
        )
    return results


def _extract_search_results(page: Page) -> list[dict[str, str]]:
    url = page.url.lower()
    if "search.yahoo.com" in url:
        return _extract_yahoo_results(page)
    if "bing.com" in url:
        return _extract_bing_results(page)
    return []


def _resolve_bing_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if "bing.com" not in parsed.netloc.lower():
        return url
    encoded = parse_qs(parsed.query).get("u", [""])[0].strip()
    if not encoded.startswith("a1"):
        return url
    payload = encoded[2:]
    try:
        pad = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + pad).decode("utf-8")
    except Exception:
        return url
    return decoded.strip() or url


def _bing_challenge_reason(observation: BrowserObservation) -> str:
    body = observation.text_excerpt.lower()
    title = observation.title.lower()
    if "unusual traffic" in body or "about this page" in body:
        return "The search engine blocked browser automation with an unusual-traffic challenge."
    if "complete the following challenge" in body or "confirm this search was made by a human" in body:
        return "The search engine presented a bot challenge instead of search results."
    if "captcha" in title:
        return "The search engine returned a captcha page instead of search results."
    return ""


def _yahoo_challenge_reason(observation: BrowserObservation) -> str:
    body = observation.text_excerpt.lower()
    title = observation.title.lower()
    if "unusual traffic" in body or "confirm you’re not a robot" in body:
        return "Yahoo blocked the search with an anti-bot challenge."
    if "captcha" in title or "access denied" in title:
        return "Yahoo returned a blocked search page instead of results."
    return ""
