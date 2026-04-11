import * as ScrollArea from "@radix-ui/react-scroll-area";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Edit3, ImagePlus, Lock, Send, Square, X } from "lucide-react";
import { ChangeEvent, FormEvent, KeyboardEvent, UIEvent, useEffect, useMemo, useRef, useState } from "react";

import { MessageContent } from "../components/MessageContent";
import {
  cancelRun,
  getRun,
  getModels,
  getStatus,
  getThreadHistory,
  getThreads,
  renameThread,
  startChat,
  type ImageAttachment,
} from "../lib/api";
import { useAtlasStore } from "../store/useAtlasStore";

type ConversationMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  attachments?: ImageAttachment[];
  ephemeral?: boolean;
};

export function WorkspacePage() {
  const queryClient = useQueryClient();
  const conversationViewportRef = useRef<HTMLDivElement | null>(null);
  const autoScrollToLatestRef = useRef(true);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [prompt, setPrompt] = useState("");
  const [attachments, setAttachments] = useState<ImageAttachment[]>([]);

  const currentUserId = useAtlasStore((state) => state.currentUserId);
  const currentThreadId = useAtlasStore((state) => state.currentThreadId);
  const currentThreadTitle = useAtlasStore((state) => state.currentThreadTitle);
  const draftThreadModel = useAtlasStore((state) => state.draftThreadModel);
  const draftThreadTemperature = useAtlasStore((state) => state.draftThreadTemperature);
  const crossChatMemoryEnabled = useAtlasStore((state) => state.crossChatMemoryEnabled);
  const autoCompactLongChats = useAtlasStore((state) => state.autoCompactLongChats);
  const currentRunId = useAtlasStore((state) => state.currentRunId);
  const activeRunUserId = useAtlasStore((state) => state.activeRunUserId);
  const activeRunThreadId = useAtlasStore((state) => state.activeRunThreadId);
  const pendingPrompt = useAtlasStore((state) => state.pendingPrompt);
  const pendingAttachments = useAtlasStore((state) => state.pendingAttachments);
  const liveAnswer = useAtlasStore((state) => state.liveAnswer);
  const liveError = useAtlasStore((state) => state.liveError);
  const compactionNotice = useAtlasStore((state) => state.compactionNotice);
  const isStreaming = useAtlasStore((state) => state.isStreaming);
  const setCurrentThreadId = useAtlasStore((state) => state.setCurrentThreadId);
  const setCurrentThreadTitle = useAtlasStore((state) => state.setCurrentThreadTitle);
  const setDraftThreadModel = useAtlasStore((state) => state.setDraftThreadModel);
  const setDraftThreadTemperature = useAtlasStore((state) => state.setDraftThreadTemperature);
  const beginRun = useAtlasStore((state) => state.beginRun);
  const setStage = useAtlasStore((state) => state.setStage);
  const failRun = useAtlasStore((state) => state.failRun);
  const clearCompactionNotice = useAtlasStore((state) => state.clearCompactionNotice);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [showCompactionSummary, setShowCompactionSummary] = useState(false);

  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: getStatus,
    staleTime: 5000,
  });
  const { data: models } = useQuery({
    queryKey: ["models"],
    queryFn: getModels,
    staleTime: 10000,
  });
  const { data: threads = [] } = useQuery({
    queryKey: ["threads", currentUserId],
    queryFn: () => getThreads(currentUserId),
    enabled: Boolean(currentUserId),
    staleTime: 2000,
  });
  const { data: history = [] } = useQuery({
    queryKey: ["thread-history", currentUserId, currentThreadId],
    queryFn: () => getThreadHistory(currentThreadId, currentUserId),
    enabled: Boolean(currentUserId && currentThreadId),
    staleTime: 2000,
  });

  const threadItems = useMemo(() => {
    const seen = new Set<string>();
    return threads.filter((thread) => {
      const key = `${thread.user_id}::${thread.thread_id}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
  }, [threads]);

  const defaultModel =
    models?.default_model || status?.default_chat_model || status?.chat_model || draftThreadModel || "";
  const defaultTemperature =
    models?.default_temperature ?? status?.default_chat_temperature ?? status?.chat_temperature ?? 0.2;
  const availableModels = (models?.models ?? [defaultModel]).filter(Boolean);

  const currentThread = useMemo(() => {
    const existing = threadItems.find((item) => item.thread_id === currentThreadId);
    if (existing) {
      return existing;
    }
    if (!currentThreadId) {
      return threadItems[0];
    }
    return {
      user_id: currentUserId,
      thread_id: currentThreadId,
      title: currentThreadTitle || currentThreadId,
      chat_model: draftThreadModel || defaultModel,
      temperature: draftThreadTemperature,
      last_mode: "chat",
      updated_at: new Date().toISOString(),
      last_prompt: "",
      last_run_id: "",
    };
  }, [currentThreadId, currentThreadTitle, currentUserId, defaultModel, draftThreadModel, draftThreadTemperature, threadItems]);

  const currentThreadHasActiveRun =
    activeRunUserId === currentUserId &&
    activeRunThreadId === currentThreadId;
  const activeRunIdForThread = currentThreadHasActiveRun ? currentRunId : null;
  const lastRunId = activeRunIdForThread ?? currentThread?.last_run_id ?? "";
  const { data: runDetails } = useQuery({
    queryKey: ["run", lastRunId],
    queryFn: () => getRun(lastRunId),
    enabled: Boolean(lastRunId),
    staleTime: 2000,
  });

  const threadHasHistory = Boolean(history.length || currentThread?.last_run_id || runDetails?.run_id);
  const lockedThreadModel = threadHasHistory
    ? runDetails?.chat_model ||
      currentThread?.chat_model ||
      status?.default_chat_model ||
      models?.default_model ||
      ""
    : "";
  const lockedThreadTemperature = useMemo<number | null | undefined>(() => {
    if (!threadHasHistory) {
      return undefined;
    }
    const runTemperature = readStoredTemperature(runDetails);
    if (runTemperature !== undefined) {
      return runTemperature;
    }
    const threadTemperature = readStoredTemperature(currentThread);
    if (threadTemperature !== undefined) {
      return threadTemperature;
    }
    return defaultTemperature;
  }, [currentThread, defaultTemperature, runDetails, threadHasHistory]);
  const selectedModel = lockedThreadModel || draftThreadModel || defaultModel;
  const selectedTemperature = lockedThreadTemperature !== undefined ? lockedThreadTemperature : draftThreadTemperature;
  const selectedModelDetails = useMemo(
    () => models?.model_details?.find((item) => item.name === selectedModel),
    [models?.model_details, selectedModel],
  );
  const selectedModelSupportsImages = Boolean(selectedModelDetails?.supports_images);
  const headerSummary = !status
    ? "Local runtime offline. Restart Atlas from the sidebar to continue."
    : !currentUserId
      ? "Create or select a user before starting a chat."
    : selectedModel
      ? "Model and temperature lock after the first message in this thread."
      : "Choose a local model and temperature before the first message.";
  const idleTitle = !status ? "Backend offline" : !currentUserId ? "No user selected" : "Start the next thread";
  const idleDescription = !status
    ? "Atlas cannot load chats or models until the managed backend comes back online. Use the restart control in the sidebar when the runtime is ready."
    : !currentUserId
      ? "Open Settings and create a user, or switch to an existing one, before sending the first message."
    : selectedModelSupportsImages
      ? "Ask a question, upload a photo for context, or use this thread as a clean branch for a new line of thinking."
      : "Use this thread to compare ideas, condense notes, or sketch the next move.";
  const composerPlaceholder = !selectedModel
    ? !status
      ? "Backend offline. Restart the local runtime to continue."
      : !currentUserId
        ? "Create or select a user in Settings first."
      : "Choose a local model to start this chat."
    : selectedModelSupportsImages
      ? "Drop a photo, a rough brief, or the first line."
      : "Start with a question, a draft, or the next move.";
  const currentThreadCompactionNotice = useMemo(() => {
    if (!compactionNotice) {
      return null;
    }
    if (compactionNotice.userId !== currentUserId || compactionNotice.threadId !== currentThreadId) {
      return null;
    }
    return compactionNotice;
  }, [compactionNotice, currentThreadId, currentUserId]);
  const runCompactedMessageCount = readPositiveInteger(runDetails?.compacted_message_count);
  const noticedCompactedMessageCount = currentThreadCompactionNotice?.compactedMessageCount ?? 0;
  const effectiveCompactedMessageCount = Math.max(runCompactedMessageCount, noticedCompactedMessageCount);
  const effectiveDetectedContextWindow =
    readPositiveInteger(currentThreadCompactionNotice?.detectedContextWindow) ||
    readPositiveInteger(runDetails?.detected_context_window);
  const effectiveThreadSummary = useMemo(() => {
    const liveSummary = (currentThreadCompactionNotice?.threadSummary || "").trim();
    if (liveSummary) {
      return liveSummary;
    }
    return String(runDetails?.thread_summary ?? "").trim();
  }, [currentThreadCompactionNotice?.threadSummary, runDetails?.thread_summary]);
  const hasCompactionHistory = effectiveCompactedMessageCount > 0 && Boolean(effectiveThreadSummary);

  useEffect(() => {
    setDraftTitle(currentThread?.title || currentThreadTitle || currentThreadId || "");
    setIsEditingTitle(false);
  }, [currentThread?.title, currentThreadId, currentThreadTitle]);

  useEffect(() => {
    setShowCompactionSummary(false);
  }, [currentUserId, currentThreadId]);

  useEffect(() => {
    if (currentThreadCompactionNotice) {
      setShowCompactionSummary(true);
    }
  }, [currentThreadCompactionNotice?.runId]);

  const startRun = useMutation({
    mutationFn: async (value: string) => {
      if (!currentUserId) {
        throw new Error("Create or select a user in Settings before starting a chat.");
      }
      const modelForRun = lockedThreadModel || selectedModel;
      if (!modelForRun) {
        throw new Error("Select a local Ollama model before starting this chat.");
      }
      const temperatureForRun = lockedThreadTemperature !== undefined ? lockedThreadTemperature : (selectedTemperature ?? null);
      return startChat(
        value,
        currentUserId,
        currentThreadId,
        modelForRun,
        temperatureForRun,
        (currentThreadTitle || currentThreadId).trim(),
        crossChatMemoryEnabled,
        autoCompactLongChats,
        attachments,
      );
    },
    onSuccess: ({ run_id }, value) => {
      autoScrollToLatestRef.current = true;
      beginRun(run_id, value, currentUserId, currentThreadId, attachments);
      setPrompt("");
      setAttachments([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    },
    onError: (error) => {
      failRun(error instanceof Error ? error.message : "Atlas run failed.");
    },
  });

  const stopRun = useMutation({
    mutationFn: async () => {
      if (!currentRunId) {
        throw new Error("No active run to stop.");
      }
      return cancelRun(currentRunId);
    },
    onSuccess: () => {
      setStage("stopping");
    },
    onError: (error) => {
      failRun(error instanceof Error ? error.message : "Atlas could not stop this run.");
    },
  });

  useEffect(() => {
    if (!currentThreadId && threadItems.length) {
      setCurrentThreadId(threadItems[0].thread_id);
    }
  }, [currentThreadId, setCurrentThreadId, threadItems]);

  useEffect(() => {
    if (!draftThreadModel && defaultModel) {
      setDraftThreadModel(defaultModel);
    }
  }, [defaultModel, draftThreadModel, setDraftThreadModel]);

  useEffect(() => {
    const resolvedTitle = currentThread?.title || currentThreadId || "";
    if (resolvedTitle && resolvedTitle !== currentThreadTitle) {
      setCurrentThreadTitle(resolvedTitle);
    }
  }, [currentThread?.title, currentThreadId, currentThreadTitle, setCurrentThreadTitle]);

  const transcript = useMemo(() => {
    const items: ConversationMessage[] = history.map((item) => ({ ...item }));
    if (currentThreadHasActiveRun && (pendingPrompt || pendingAttachments.length)) {
      items.push({ role: "user", content: pendingPrompt, attachments: pendingAttachments, ephemeral: true });
    }
    if (currentThreadHasActiveRun && liveAnswer) {
      items.push({ role: "assistant", content: liveAnswer, ephemeral: true });
    }
    return items;
  }, [currentThreadHasActiveRun, history, liveAnswer, pendingAttachments, pendingPrompt]);

  useEffect(() => {
    autoScrollToLatestRef.current = true;
  }, [currentUserId, currentThreadId]);

  useEffect(() => {
    const viewport = conversationViewportRef.current;
    if (!viewport) {
      return;
    }
    if (!autoScrollToLatestRef.current) {
      return;
    }
    viewport.scrollTo({ top: viewport.scrollHeight });
  }, [transcript]);

  const handleConversationScroll = (event: UIEvent<HTMLDivElement>) => {
    autoScrollToLatestRef.current = isNearBottom(event.currentTarget);
  };

  const submitPrompt = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if ((!prompt.trim() && attachments.length === 0) || isStreaming || !selectedModel || !currentUserId) {
      return;
    }
    startRun.mutate(prompt.trim());
  };

  const handlePromptKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      if ((!prompt.trim() && attachments.length === 0) || isStreaming || !selectedModel || !currentUserId) {
        return;
      }
      startRun.mutate(prompt.trim());
    }
  };

  const commitTitle = useMutation({
    mutationFn: async (title: string) => renameThread(currentThreadId, currentUserId, title),
    onSuccess: async (thread) => {
      setCurrentThreadTitle(thread.title || thread.thread_id);
      setIsEditingTitle(false);
      await queryClient.invalidateQueries({ queryKey: ["threads", currentUserId] });
    },
  });

  const saveTitle = async () => {
    const normalized = draftTitle.trim() || currentThreadId;
    if (!threadHasHistory) {
      setCurrentThreadTitle(normalized);
      setDraftTitle(normalized);
      setIsEditingTitle(false);
      return;
    }
    await commitTitle.mutateAsync(normalized);
  };

  const handleFileSelection = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.currentTarget.files ?? []);
    const nextAttachments = await Promise.all(files.map((file) => fileToAttachment(file)));
    setAttachments(nextAttachments);
  };

  return (
    <section className="workspace-main workspace-main-single">
      <div className="workspace-main-header">
        <div className="workspace-title-block">
          <div className="workspace-title-row">
            {isEditingTitle ? (
              <>
                <input
                  className="text-input workspace-title-input"
                  onChange={(event) => setDraftTitle(event.currentTarget.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void saveTitle();
                    }
                    if (event.key === "Escape") {
                      setDraftTitle(currentThread?.title || currentThreadTitle || currentThreadId || "");
                      setIsEditingTitle(false);
                    }
                  }}
                  placeholder="Chat title"
                  value={draftTitle}
                />
                <button className="ghost-button icon-button" onClick={() => void saveTitle()} type="button">
                  <Check size={16} />
                </button>
                <button
                  className="ghost-button icon-button"
                  onClick={() => {
                    setDraftTitle(currentThread?.title || currentThreadTitle || currentThreadId || "");
                    setIsEditingTitle(false);
                  }}
                  type="button"
                >
                  <X size={16} />
                </button>
              </>
            ) : (
              <>
                <h1>{currentThread?.title || currentThreadTitle || currentThreadId || "New chat"}</h1>
                <button className="ghost-button icon-button title-edit-button" onClick={() => setIsEditingTitle(true)} type="button">
                  <Edit3 size={16} />
                </button>
              </>
            )}
          </div>
          <p>{headerSummary}</p>
          {hasCompactionHistory ? (
            <div className="compaction-summary-card">
              <div className="compaction-summary-topline">
                <span className="status-pill subtle compacted">
                  <span className="status-dot" />
                  Context compacted
                </span>
                <p className="compaction-summary-copy">
                  {formatCompactionSummaryMessage(
                    effectiveCompactedMessageCount,
                    effectiveDetectedContextWindow,
                  )}
                </p>
                <button
                  className="ghost-button compact-summary-toggle"
                  onClick={() => setShowCompactionSummary((current) => !current)}
                  type="button"
                >
                  {showCompactionSummary ? "Hide summary" : "Preview summary"}
                </button>
              </div>
              {showCompactionSummary ? (
                <div className="stack-card compaction-summary-preview">
                  <span className="compaction-summary-preview-label">Active summary</span>
                  <pre className="compaction-summary-preview-text">{effectiveThreadSummary}</pre>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="workspace-header-controls">
          <div className="workspace-model-group">
            <span className="workspace-model-label">Model</span>
            {lockedThreadModel ? (
              <div className="workspace-model-lock" title="This chat already started with this model.">
                <Lock size={14} />
                <span>{formatModelLabel(lockedThreadModel)}</span>
              </div>
            ) : (
              <label className="workspace-model-picker">
                <select
                  className="select-input workspace-model-select"
                  disabled={availableModels.length === 0}
                  onChange={(event) => setDraftThreadModel(event.currentTarget.value)}
                  value={selectedModel}
                >
                  {availableModels.length > 0 ? (
                    availableModels.map((model) => (
                      <option key={model} value={model}>
                        {formatModelLabel(model)}
                      </option>
                    ))
                  ) : (
                    <option value="">No model available</option>
                  )}
                </select>
              </label>
            )}
          </div>

          <div className="workspace-model-group">
            <span className="workspace-model-label">Temp</span>
            {lockedThreadTemperature !== undefined ? (
              <div className="workspace-model-lock" title="This chat already started with this temperature.">
                <Lock size={14} />
                <span>{formatTemperatureLabel(lockedThreadTemperature)}</span>
              </div>
            ) : (
              <label className="workspace-model-picker workspace-temperature-picker">
                <select
                  className="select-input workspace-model-select"
                  disabled={availableModels.length === 0}
                  onChange={(event) => setDraftThreadTemperature(parseTemperatureValue(event.currentTarget.value))}
                  value={formatTemperatureSelectValue(selectedTemperature)}
                >
                  <option value={MODEL_DEFAULT_TEMPERATURE_VALUE}>Model default</option>
                  {TEMPERATURE_OPTIONS.map((value) => (
                    <option key={value} value={value.toFixed(1)}>
                      {value.toFixed(1)}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </div>
      </div>

      <div className="conversation-shell">
        <ScrollArea.Root className="conversation-scroll">
          <ScrollArea.Viewport
            className="conversation-viewport"
            onScroll={handleConversationScroll}
            ref={conversationViewportRef}
          >
            <div className="conversation-stack">
              {currentThreadCompactionNotice ? (
                <div className="success-banner compact-notice" role="status">
                  <div className="compact-notice-copy">
                    <strong>Context compacted while Atlas was answering.</strong>
                    <span>
                      {formatCompactionNoticeMessage(
                        currentThreadCompactionNotice.newlyCompactedMessageCount,
                        currentThreadCompactionNotice.compactedMessageCount,
                        effectiveDetectedContextWindow,
                      )}
                    </span>
                  </div>
                  <div className="compact-notice-actions">
                    {effectiveThreadSummary ? (
                      <button
                        className="ghost-button compact-summary-toggle"
                        onClick={() => setShowCompactionSummary((current) => !current)}
                        type="button"
                      >
                        {showCompactionSummary ? "Hide summary" : "Preview summary"}
                      </button>
                    ) : null}
                    <button
                      aria-label="Dismiss compaction notice"
                      className="ghost-button icon-button"
                      onClick={() => clearCompactionNotice()}
                      type="button"
                    >
                      <X size={14} />
                    </button>
                  </div>
                </div>
              ) : null}
              {transcript.length === 0 ? (
                <div className="workspace-idle">
                  <div className="workspace-idle-card">
                    <div className="workspace-idle-mark">
                      <img alt="Atlas" className="workspace-idle-logo workspace-idle-logo-large" src="/AtlasLogo.png" />
                    </div>
                    <h2>{idleTitle}</h2>
                    <p>{idleDescription}</p>
                  </div>
                </div>
              ) : null}

              {transcript.map((message, index) => (
                <article className={`message-card ${message.role}`} key={`${message.role}-${index}-${message.content.length}`}>
                  <div className="message-meta">
                    <span>{formatMessageRoleLabel(message.role)}</span>
                  </div>
                  {message.attachments?.length ? (
                    <div className="message-attachments">
                      {message.attachments.map((item, attachmentIndex) => (
                        <img
                          alt={item.name || `attachment-${attachmentIndex + 1}`}
                          className="message-attachment-image"
                          key={`${item.data_url}-${attachmentIndex}`}
                          src={item.data_url}
                        />
                      ))}
                    </div>
                  ) : null}
                  <MessageContent content={message.content} streaming={Boolean(message.ephemeral && message.role === "assistant")} />
                </article>
              ))}
              {currentThreadHasActiveRun && isStreaming && !liveAnswer ? (
                <article className="message-card assistant message-card-waiting">
                  <div className="message-meta">
                    <span>{formatMessageRoleLabel("assistant")}</span>
                  </div>
                  <div className="stream-waiting-line" aria-live="polite">
                    <span>Deciding</span>
                    <span className="stream-dots" aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </span>
                  </div>
                </article>
              ) : null}
              {currentThreadHasActiveRun && liveError ? <div className="error-banner">{liveError}</div> : null}
            </div>
          </ScrollArea.Viewport>
          <ScrollArea.Scrollbar className="scrollbar" orientation="vertical">
            <ScrollArea.Thumb className="scrollbar-thumb" />
          </ScrollArea.Scrollbar>
        </ScrollArea.Root>
      </div>

      <form className="composer composer-shell" onSubmit={submitPrompt}>
        {attachments.length ? (
          <div className="composer-attachments">
            {attachments.map((item, index) => (
              <div className="composer-attachment-card" key={`${item.data_url}-${index}`}>
                <img alt={item.name || `attachment-${index + 1}`} className="composer-attachment-image" src={item.data_url} />
                <button
                  aria-label={`Remove ${item.name || "image"}`}
                  className="ghost-button icon-button composer-attachment-remove"
                  onClick={() => setAttachments((current) => current.filter((_, currentIndex) => currentIndex !== index))}
                  type="button"
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
        ) : null}

        <textarea
          className="prompt-input"
          onChange={(event) => setPrompt(event.currentTarget.value)}
          onKeyDown={handlePromptKeyDown}
          placeholder={composerPlaceholder}
          rows={3}
          value={prompt}
        />

        <div className="composer-actions">
          {selectedModelSupportsImages ? (
            <>
              <input
                accept="image/*"
                className="hidden-file-input"
                onChange={handleFileSelection}
                ref={fileInputRef}
                type="file"
              />
              <button className="ghost-button" onClick={() => fileInputRef.current?.click()} type="button">
                <ImagePlus size={16} />
                Upload photo
              </button>
            </>
          ) : null}

          <button className="primary-button" disabled={isStreaming || (!prompt.trim() && attachments.length === 0) || !selectedModel || !currentUserId} type="submit">
            <Send size={16} />
            {isStreaming ? "Running..." : "Send"}
          </button>
          {isStreaming ? (
            <button
              className="ghost-button stop-button"
              disabled={stopRun.isPending || !currentRunId}
              onClick={() => stopRun.mutate()}
              type="button"
            >
              <Square size={14} fill="currentColor" />
              {stopRun.isPending ? "Stopping..." : "Stop"}
            </button>
          ) : null}
        </div>
      </form>
    </section>
  );
}

const MODEL_DEFAULT_TEMPERATURE_VALUE = "model-default";
const TEMPERATURE_OPTIONS = Array.from({ length: 21 }, (_, index) => Number((index / 10).toFixed(1)));

function formatModelLabel(value: string) {
  return value || "Select model";
}

function readStoredTemperature(value: { temperature?: number | null } | undefined): number | null | undefined {
  if (!value || !Object.prototype.hasOwnProperty.call(value, "temperature")) {
    return undefined;
  }
  if (typeof value.temperature === "number" && Number.isFinite(value.temperature)) {
    return value.temperature;
  }
  return null;
}

function parseTemperatureValue(value: string): number | null {
  if (value === MODEL_DEFAULT_TEMPERATURE_VALUE) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Number(parsed.toFixed(1)) : null;
}

function formatTemperatureSelectValue(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return MODEL_DEFAULT_TEMPERATURE_VALUE;
  }
  return value.toFixed(1);
}

function formatTemperatureLabel(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "Model default";
  }
  return value.toFixed(1);
}

function readPositiveInteger(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : 0;
}

function isNearBottom(element: HTMLDivElement, threshold = 72) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold;
}

function formatMessageRoleLabel(role: ConversationMessage["role"]) {
  if (role === "assistant") {
    return "MODEL";
  }
  return role;
}

function formatCompactionSummaryMessage(compactedMessageCount: number, detectedContextWindow: number) {
  const messageLabel = compactedMessageCount === 1 ? "message was" : "messages were";
  const windowCopy =
    detectedContextWindow > 0
      ? ` Atlas detected a ${detectedContextWindow.toLocaleString()} token window for this model.`
      : "";
  return `${compactedMessageCount} earlier ${messageLabel} summarized so Atlas can keep the prompt inside the model context.${windowCopy}`;
}

function formatCompactionNoticeMessage(
  newlyCompactedMessageCount: number,
  compactedMessageCount: number,
  detectedContextWindow: number,
) {
  const freshCount = newlyCompactedMessageCount > 0 ? newlyCompactedMessageCount : compactedMessageCount;
  const verb = freshCount === 1 ? "message was" : "messages were";
  const windowCopy =
    detectedContextWindow > 0
      ? ` Context window: ${detectedContextWindow.toLocaleString()} tokens.`
      : "";
  return `${freshCount} earlier ${verb} folded into the thread summary. Atlas will use that summary plus the most recent raw turns on the next prompt.${windowCopy}`;
}

async function fileToAttachment(file: File): Promise<ImageAttachment> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("Could not read image."));
    reader.onload = () => resolve(String(reader.result || ""));
    reader.readAsDataURL(file);
  });
  return {
    name: file.name,
    media_type: file.type || "image/png",
    data_url: dataUrl,
  };
}
