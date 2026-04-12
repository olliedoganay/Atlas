from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from .config import AppConfig


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
        }


@dataclass
class OllamaWebSearchService:
    config: AppConfig

    @property
    def available(self) -> bool:
        return bool(self.config.ollama_api_key.strip())

    def search(self, query: str, *, max_results: int | None = None) -> list[WebSearchResult]:
        normalized_query = " ".join(query.split()).strip()
        if not normalized_query:
            return []
        if not self.available:
            raise RuntimeError("Web search is unavailable because OLLAMA_API_KEY is not configured.")

        payload = json.dumps(
            {
                "query": normalized_query,
                "max_results": max(1, min(int(max_results or self.config.web_search_max_results), 10)),
            }
        ).encode("utf-8")
        request_object = request.Request(
            "https://ollama.com/api/web_search",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.config.ollama_api_key.strip()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(request_object, timeout=10.0) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except (error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise RuntimeError("Ollama web search failed.") from exc

        results: list[WebSearchResult] = []
        for item in parsed.get("results", []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "") or "").strip()
            url = str(item.get("url", "") or "").strip()
            content = str(item.get("content", "") or "").strip()
            if not title and not url and not content:
                continue
            results.append(WebSearchResult(title=title, url=url, content=content))
        return results
