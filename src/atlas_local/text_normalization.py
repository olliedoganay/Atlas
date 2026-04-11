from __future__ import annotations

from dataclasses import dataclass

_MOJIBAKE_MARKERS = ("Ã", "Â", "â", "ð")
_MOJIBAKE_PATTERNS = (
    "â€",
    "â€™",
    "â€œ",
    "â€\u009d",
    "â€˜",
    "â€“",
    "â€”",
    "â€¦",
    "Ã©",
    "Ã¼",
    "Ã±",
)
_MIN_SEQUENCE_LENGTH = {
    "Ã": 2,
    "Â": 2,
    "â": 3,
    "ð": 4,
}


def repair_mojibake_text(text: str, *, max_passes: int = 2) -> str:
    if not text or not _looks_like_mojibake(text):
        return text

    current = text
    for _ in range(max_passes):
        candidate = _attempt_cp1252_utf8_redecode(current)
        if candidate == current or _mojibake_score(candidate) >= _mojibake_score(current):
            break
        current = candidate
        if not _looks_like_mojibake(current):
            break
    return current


@dataclass
class MojibakeRepairStream:
    pending: str = ""

    def consume(self, text: str) -> str:
        if not text:
            return ""
        data = f"{self.pending}{text}"
        safe_end = _safe_mojibake_boundary(data)
        self.pending = data[safe_end:]
        return repair_mojibake_text(data[:safe_end])

    def flush(self) -> str:
        if not self.pending:
            return ""
        remainder = self.pending
        self.pending = ""
        return repair_mojibake_text(remainder)


def _attempt_cp1252_utf8_redecode(text: str) -> str:
    try:
        payload = bytearray()
        for character in text:
            codepoint = ord(character)
            if codepoint <= 0xFF:
                payload.append(codepoint)
                continue
            encoded = character.encode("cp1252")
            if len(encoded) != 1:
                return text
            payload.extend(encoded)
        return bytes(payload).decode("utf-8")
    except UnicodeError:
        return text


def _looks_like_mojibake(text: str) -> bool:
    return any(marker in text for marker in _MOJIBAKE_MARKERS) or any(pattern in text for pattern in _MOJIBAKE_PATTERNS)


def _mojibake_score(text: str) -> int:
    score = text.count("\ufffd") * 8
    for pattern in _MOJIBAKE_PATTERNS:
        score += text.count(pattern) * 4
    for marker in _MOJIBAKE_MARKERS:
        score += text.count(marker)
    return score


def _safe_mojibake_boundary(text: str) -> int:
    if not text:
        return 0
    scan_start = max(0, len(text) - max(_MIN_SEQUENCE_LENGTH.values()) + 1)
    for index in range(len(text) - 1, scan_start - 1, -1):
        marker = text[index]
        minimum_length = _MIN_SEQUENCE_LENGTH.get(marker)
        if minimum_length is None:
            continue
        trailing_length = len(text) - index
        if trailing_length < minimum_length:
            return index
    return len(text)
