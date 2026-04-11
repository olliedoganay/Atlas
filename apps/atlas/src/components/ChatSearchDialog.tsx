import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { type ReactNode, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { searchChats, type ChatSearchResult } from "../lib/api";

type ChatSearchDialogProps = {
  currentThreadId: string;
  currentThreadTitle: string;
  currentUserId: string;
  onOpenChange: (open: boolean) => void;
  onPick: (result: ChatSearchResult, query: string) => void;
  open: boolean;
};

export function ChatSearchDialog({
  currentThreadId,
  currentThreadTitle,
  currentUserId,
  onOpenChange,
  onPick,
  open,
}: ChatSearchDialogProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim());
  const canSearch = open && Boolean(currentUserId) && deferredQuery.length >= 2;

  const { data, isFetching } = useQuery({
    queryKey: ["chat-search", currentUserId, currentThreadId, deferredQuery],
    queryFn: () => searchChats(deferredQuery, currentUserId, currentThreadId),
    enabled: canSearch,
    staleTime: 1000,
  });

  useEffect(() => {
    if (!open) {
      setQuery("");
      return;
    }
    const focusTimer = window.setTimeout(() => inputRef.current?.focus(), 16);
    return () => window.clearTimeout(focusTimer);
  }, [open]);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onOpenChange(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onOpenChange, open]);

  const currentResults = data?.current_thread_results ?? [];
  const otherResults = data?.other_thread_results ?? [];
  const totalResults = currentResults.length + otherResults.length;
  const currentThreadLabel = currentThreadTitle || currentThreadId || "Current chat";
  const statusCopy = useMemo(() => {
    if (!currentUserId) {
      return "Select a user before searching chats.";
    }
    if (deferredQuery.length === 0) {
      return "Search this chat and the rest of your local conversation archive.";
    }
    if (deferredQuery.length < 2) {
      return "Type at least 2 characters to search message content and chat titles.";
    }
    if (isFetching) {
      return "Searching local chats...";
    }
    if (totalResults === 0) {
      return "No matching threads or messages in local history.";
    }
    return `${totalResults} match${totalResults === 1 ? "" : "es"} across local chats.`;
  }, [currentUserId, deferredQuery.length, isFetching, totalResults]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="search-dialog-backdrop"
      onClick={() => onOpenChange(false)}
      role="presentation"
    >
      <div
        aria-label="Search chats"
        aria-modal="true"
        className="search-dialog"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <div className="search-dialog-header">
          <div>
            <p className="workspace-section-label">Search</p>
            <h2>Search chats</h2>
          </div>
          <button
            aria-label="Close search"
            className="ghost-button icon-button"
            onClick={() => onOpenChange(false)}
            type="button"
          >
            <X size={16} />
          </button>
        </div>

        <label className="search-input-shell">
          <Search size={18} />
          <input
            className="search-input"
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder="Search this chat and all chats"
            ref={inputRef}
            value={query}
          />
          {query ? (
            <button
              aria-label="Clear search"
              className="ghost-button icon-button"
              onClick={() => setQuery("")}
              type="button"
            >
              <X size={14} />
            </button>
          ) : (
            <span className="search-shortcut-hint">Ctrl+K</span>
          )}
        </label>

        <p className="search-status-copy">{statusCopy}</p>

        <div className="search-dialog-sections">
          <SearchSection
            emptyLabel={deferredQuery.length >= 2 ? "No hits in this chat." : "Start typing to search inside this chat."}
            query={deferredQuery}
            results={currentResults}
            sectionLabel="This chat"
            sectionTitle={currentThreadLabel}
            onPick={(result) => onPick(result, deferredQuery)}
          />
          <SearchSection
            emptyLabel={deferredQuery.length >= 2 ? "No hits in other chats." : "Search will also scan your other local chats."}
            query={deferredQuery}
            results={otherResults}
            sectionLabel="All chats"
            sectionTitle="Other conversations"
            onPick={(result) => onPick(result, deferredQuery)}
          />
        </div>
      </div>
    </div>
  );
}

type SearchSectionProps = {
  emptyLabel: string;
  onPick: (result: ChatSearchResult) => void;
  query: string;
  results: ChatSearchResult[];
  sectionLabel: string;
  sectionTitle: string;
};

function SearchSection({
  emptyLabel,
  onPick,
  query,
  results,
  sectionLabel,
  sectionTitle,
}: SearchSectionProps) {
  return (
    <section className="search-section">
      <div className="search-section-head">
        <div>
          <p className="workspace-section-label">{sectionLabel}</p>
          <h3>{sectionTitle}</h3>
        </div>
        <span className="search-section-count">{results.length}</span>
      </div>

      {results.length > 0 ? (
        <div className="search-result-list">
          {results.map((result, index) => (
            <button
              className="search-result-card"
              key={`${result.thread_id}-${result.match_type}-${result.history_index ?? "thread"}-${index}`}
              onClick={() => onPick(result)}
              type="button"
            >
              <div className="search-result-top">
                <div className="search-result-title-block">
                  <strong>{highlightSearchText(result.thread_title, query)}</strong>
                  <span className="search-result-badge">
                    {result.match_type === "thread"
                      ? "Chat"
                      : result.role === "assistant"
                        ? "Model"
                        : "User"}
                  </span>
                </div>
                <span className="search-result-meta">{formatSearchDate(result.updated_at)}</span>
              </div>
              <p className="search-result-snippet">{highlightSearchText(result.snippet, query)}</p>
              <div className="search-result-foot">
                <span>{result.chat_model || "Local model"}</span>
                <span>{result.history_index === null || result.history_index === undefined ? "Open chat" : "Jump to match"}</span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="search-empty-state">{emptyLabel}</div>
      )}
    </section>
  );
}

function highlightSearchText(value: string, query: string): ReactNode {
  if (!query) {
    return value;
  }
  const normalizedValue = value.toLocaleLowerCase();
  const normalizedQuery = query.toLocaleLowerCase();
  const parts: ReactNode[] = [];
  let cursor = 0;
  let key = 0;

  while (cursor < value.length) {
    const matchIndex = normalizedValue.indexOf(normalizedQuery, cursor);
    if (matchIndex < 0) {
      parts.push(value.slice(cursor));
      break;
    }
    if (matchIndex > cursor) {
      parts.push(value.slice(cursor, matchIndex));
    }
    const matchEnd = matchIndex + query.length;
    parts.push(
      <mark className="search-highlight" key={`match-${key}`}>
        {value.slice(matchIndex, matchEnd)}
      </mark>,
    );
    key += 1;
    cursor = matchEnd;
  }

  return parts;
}

function formatSearchDate(value?: string) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return "";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}
