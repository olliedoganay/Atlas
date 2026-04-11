from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


class BrowserPolicyError(RuntimeError):
    pass


READ_ONLY_TOOLS = {
    "search_web",
    "open_page",
    "extract_text",
    "get_links",
    "go_back",
    "screenshot",
    "quote_source",
}
INTERACTIVE_TOOLS = {"click", "type"}


@dataclass(frozen=True)
class BrowserPolicy:
    allowlist: tuple[str, ...]
    blocklist: tuple[str, ...]

    def check(self, tool: str, url: str) -> None:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        scheme = parsed.scheme.lower()

        if scheme not in {"http", "https", "file"}:
            raise BrowserPolicyError(f"Blocked unsupported URL scheme for {tool}: {url}")

        if any(blocked.lower() in domain for blocked in self.blocklist):
            raise BrowserPolicyError(f"Blocked domain for {tool}: {domain}")

        if tool in READ_ONLY_TOOLS:
            return

        if tool in INTERACTIVE_TOOLS:
            if scheme == "file":
                return
            if not self.allowlist:
                raise BrowserPolicyError(
                    f"Blocked interactive browser action {tool!r} on public domain {domain}. "
                    "Add the domain to WEB_ALLOWLIST to permit it."
                )
            if any(allowed.lower() in domain for allowed in self.allowlist):
                return
            raise BrowserPolicyError(
                f"Blocked interactive browser action {tool!r} on {domain}. "
                "Only allowlisted domains may receive click/type operations."
            )

        raise BrowserPolicyError(f"Blocked unknown browser action: {tool}")
