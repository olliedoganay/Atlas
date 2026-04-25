import type { ThreadSummary } from "./api";

const GENERATED_THREAD_ID_PATTERN = /^atlas-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}(?:-\d+)?-[a-z0-9]+$/i;
const GENERIC_TITLES = new Set(["", "new chat", "new thread"]);

export function isGeneratedThreadId(value?: string | null) {
  return GENERATED_THREAD_ID_PATTERN.test((value ?? "").trim());
}

export function cleanThreadTitle(value?: string | null) {
  const normalized = (value ?? "").trim();
  if (!normalized || isGeneratedThreadId(normalized)) {
    return "";
  }
  if (normalized.toLowerCase() === "main") {
    return "Main";
  }
  return normalized;
}

export function displayThreadTitle(
  threadOrTitle?: ThreadSummary | string | null,
  threadId?: string | null,
  fallback = "New chat",
) {
  if (typeof threadOrTitle === "object" && threadOrTitle) {
    return (
      cleanThreadTitle(threadOrTitle.title) ||
      cleanThreadTitle(threadOrTitle.thread_id) ||
      fallback
    );
  }
  return cleanThreadTitle(threadOrTitle) || cleanThreadTitle(threadId) || fallback;
}

export function editableThreadTitle(title?: string | null, threadId?: string | null) {
  return cleanThreadTitle(title) || cleanThreadTitle(threadId);
}

export function requestThreadTitle(title?: string | null, threadId?: string | null) {
  const normalized = editableThreadTitle(title, threadId);
  if (!normalized || GENERIC_TITLES.has(normalized.toLowerCase())) {
    return undefined;
  }
  return normalized;
}

export function threadInitial(thread: ThreadSummary) {
  return displayThreadTitle(thread).slice(0, 1).toUpperCase();
}
