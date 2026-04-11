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
  startCompact,
  startChat,
  type ImageAttachment,
  type ThreadMessage,
} from "../lib/api";
import { useAtlasStore } from "../store/useAtlasStore";

type ConversationMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  attachments?: ImageAttachment[];
  ephemeral?: boolean;
  dismissible?: boolean;
  kind?: string;
  runId?: string;
  timestamp?: string;
  compactionReason?: string;
  threadSummary?: string;
  compactedMessageCount?: number;
  newlyCompactedMessageCount?: number;
  detectedContextWindow?: number;
  historyRepresentationTokensBeforeCompaction?: number;
  historyRepresentationTokensAfterCompaction?: number;
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
  const currentRunMode = useAtlasStore((state) => state.currentRunMode);
  const activeRunUserId = useAtlasStore((state) => state.activeRunUserId);
  const activeRunThreadId = useAtlasStore((state) => state.activeRunThreadId);
  const currentStage = useAtlasStore((state) => state.currentStage);
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
  const [expandedCompactionKeys, setExpandedCompactionKeys] = useState<Record<string, boolean>>({});

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

  useEffect(() => {
    setDraftTitle(currentThread?.title || currentThreadTitle || currentThreadId || "");
    setIsEditingTitle(false);
  }, [currentThread?.title, currentThreadId, currentThreadTitle]);

  useEffect(() => {
    setExpandedCompactionKeys({});
  }, [currentUserId, currentThreadId]);

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
      beginRun(run_id, "chat", value, currentUserId, currentThreadId, attachments);
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

  const startManualCompact = useMutation({
    mutationFn: async () => {
      if (!currentUserId) {
        throw new Error("Create or select a user in Settings before compacting a chat.");
      }
      return startCompact(currentThreadId, currentUserId);
    },
    onSuccess: ({ run_id }) => {
      autoScrollToLatestRef.current = true;
      beginRun(run_id, "compact", "", currentUserId, currentThreadId, []);
    },
    onError: (error) => {
      failRun(error instanceof Error ? error.message : "Atlas could not compact this thread.");
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
    const items: ConversationMessage[] = history.map((item: ThreadMessage) => ({
      role: item.role,
      content: item.content,
      attachments: item.attachments,
      kind: item.kind,
      runId: item.run_id,
      timestamp: item.timestamp,
      compactionReason: item.compaction_reason,
      threadSummary: item.thread_summary,
      compactedMessageCount: item.compacted_message_count,
      newlyCompactedMessageCount: item.newly_compacted_message_count,
      detectedContextWindow: item.detected_context_window,
      historyRepresentationTokensBeforeCompaction: item.history_representation_tokens_before_compaction,
      historyRepresentationTokensAfterCompaction: item.history_representation_tokens_after_compaction,
    }));
    if (currentThreadHasActiveRun) {
      const liveLifecycle = buildLiveRunLifecycleMessage({
        runId: currentRunId,
        mode: currentRunMode,
        stage: currentStage,
      });
      if (liveLifecycle) {
        items.push(liveLifecycle);
      }
    }
    if (currentThreadHasActiveRun && (pendingPrompt || pendingAttachments.length)) {
      items.push({ role: "user", content: pendingPrompt, attachments: pendingAttachments, ephemeral: true });
    }
    if (currentThreadHasActiveRun && currentThreadCompactionNotice) {
      items.push(buildLiveCompactionMessage(currentThreadCompactionNotice));
    }
    if (currentThreadHasActiveRun && liveAnswer) {
      items.push({ role: "assistant", content: liveAnswer, ephemeral: true });
    }
    return items;
  }, [currentRunId, currentRunMode, currentStage, currentThreadCompactionNotice, currentThreadHasActiveRun, history, liveAnswer, pendingAttachments, pendingPrompt]);

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

  const toggleCompactionSummary = (key: string) => {
    setExpandedCompactionKeys((current) => ({ ...current, [key]: !current[key] }));
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
                isContextCompactionMessage(message) ? (
                  <article
                    className={`message-card system compact-context-message${message.ephemeral ? " active" : ""}`}
                    key={compactionMessageKey(message, index)}
                    role={message.ephemeral ? "status" : undefined}
                  >
                    <div className="message-meta compact-context-meta">
                      <span>{formatMessageRoleLabel("system")}</span>
                      <span className={`status-pill subtle ${timelineSystemBadgeClass(message)}`}>
                        <span className="status-dot" />
                        {timelineSystemBadgeLabel(message)}
                      </span>
                      {message.ephemeral ? <span className="ephemeral-tag">{timelineEphemeralLabel(message)}</span> : null}
                    </div>
                    <div className="message-content compact-context-copy">
                      <p>{formatTimelineSystemMessageText(message)}</p>
                    </div>
                    <div className="compact-context-actions">
                      {isContextCompactionMessage(message) && message.threadSummary ? (
                        <button
                          className="ghost-button compact-summary-toggle"
                          onClick={() => toggleCompactionSummary(compactionMessageKey(message, index))}
                          type="button"
                        >
                          {expandedCompactionKeys[compactionMessageKey(message, index)] ? "Hide summary" : "Preview summary"}
                        </button>
                      ) : null}
                      {message.dismissible ? (
                        <button
                          aria-label="Dismiss compaction notice"
                          className="ghost-button icon-button"
                          onClick={() => clearCompactionNotice()}
                          type="button"
                        >
                          <X size={14} />
                        </button>
                      ) : null}
                    </div>
                    {isContextCompactionMessage(message) && message.threadSummary && expandedCompactionKeys[compactionMessageKey(message, index)] ? (
                      <div className="stack-card compaction-summary-preview compact-context-summary">
                        <span className="compaction-summary-preview-label">Summary snapshot at this point</span>
                        <pre className="compaction-summary-preview-text">{message.threadSummary}</pre>
                      </div>
                    ) : null}
                  </article>
                ) : isTimelineSystemMessage(message) ? (
                  <article
                    className={`message-card system timeline-system-message${message.ephemeral ? " active" : ""}`}
                    key={compactionMessageKey(message, index)}
                    role={message.ephemeral ? "status" : undefined}
                  >
                    <div className="timeline-system-meta">
                      <span className={`status-pill subtle ${timelineSystemBadgeClass(message)}`}>
                        <span className="status-dot" />
                        {timelineSystemBadgeLabel(message)}
                      </span>
                      {message.ephemeral ? <span className="ephemeral-tag">{timelineEphemeralLabel(message)}</span> : null}
                    </div>
                    <p className="timeline-system-text">{formatTimelineSystemMessageText(message)}</p>
                  </article>
                ) : (
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
                )
              ))}
              {currentThreadHasActiveRun && isStreaming && !liveAnswer && !shouldSuppressWaitingCard(currentStage) ? (
                <article className={`message-card ${currentRunMode === "compact" ? "system" : "assistant"} message-card-waiting`}>
                  <div className="message-meta">
                    <span>{currentRunMode === "compact" ? "SYSTEM" : formatMessageRoleLabel("assistant")}</span>
                  </div>
                  <div className="stream-waiting-line" aria-live="polite">
                    <span>{currentRunMode === "compact" ? "Compacting older context" : "Deciding"}</span>
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

          <button
            className="ghost-button"
            disabled={isStreaming || !currentUserId || !threadHasHistory || startManualCompact.isPending}
            onClick={() => startManualCompact.mutate()}
            type="button"
          >
            {startManualCompact.isPending || (isStreaming && currentRunMode === "compact") ? "Compacting..." : "Compact now"}
          </button>
          <button className="primary-button" disabled={isStreaming || (!prompt.trim() && attachments.length === 0) || !selectedModel || !currentUserId} type="submit">
            <Send size={16} />
            {isStreaming ? (currentRunMode === "compact" ? "Compacting..." : "Running...") : "Send"}
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

function isNearBottom(element: HTMLDivElement, threshold = 72) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold;
}

function formatMessageRoleLabel(role: ConversationMessage["role"]) {
  if (role === "assistant") {
    return "MODEL";
  }
  return role;
}

function isContextCompactionMessage(message: ConversationMessage) {
  return message.role === "system" && message.kind === "context_compacted";
}

function isTimelineSystemMessage(message: ConversationMessage) {
  return message.role === "system" && Boolean(message.kind);
}

function buildLiveRunLifecycleMessage(input: {
  runId: string | null;
  mode: "chat" | "compact" | null;
  stage: string;
}): ConversationMessage | null {
  if (!input.runId) {
    return null;
  }
  if (input.stage === "queued") {
    return {
      role: "system",
      kind: "run_queued",
      content: input.mode === "compact"
        ? "Manual compaction is queued and will start after the current task finishes."
        : "Response queued and waiting for the current task to finish.",
      ephemeral: true,
      runId: input.runId,
    };
  }
  if (input.stage === "starting") {
    return {
      role: "system",
      kind: "run_started",
      content: input.mode === "compact" ? "Manual compaction started." : "Atlas started responding.",
      ephemeral: true,
      runId: input.runId,
    };
  }
  if (input.stage === "stopping") {
    return {
      role: "system",
      kind: "run_stopped",
      content: "Stopping this run.",
      ephemeral: true,
      runId: input.runId,
    };
  }
  return null;
}

function buildLiveCompactionMessage(notice: {
  runId: string;
  compactionReason?: string;
  compactedMessageCount: number;
  newlyCompactedMessageCount: number;
  threadSummary: string;
  detectedContextWindow: number;
  historyRepresentationTokensBeforeCompaction?: number;
  historyRepresentationTokensAfterCompaction?: number;
}): ConversationMessage {
  return {
    role: "system",
    kind: "context_compacted",
    content: "Context compacted",
    ephemeral: true,
    dismissible: true,
    runId: notice.runId,
    compactionReason: notice.compactionReason,
    threadSummary: notice.threadSummary,
    compactedMessageCount: notice.compactedMessageCount,
    newlyCompactedMessageCount: notice.newlyCompactedMessageCount,
    detectedContextWindow: notice.detectedContextWindow,
    historyRepresentationTokensBeforeCompaction: notice.historyRepresentationTokensBeforeCompaction,
    historyRepresentationTokensAfterCompaction: notice.historyRepresentationTokensAfterCompaction,
  };
}

function compactionMessageKey(message: ConversationMessage, index: number) {
  return message.runId || message.timestamp || `context-compacted-${index}`;
}

function formatTimelineSystemMessageText(message: ConversationMessage) {
  if (!isContextCompactionMessage(message)) {
    return message.content;
  }
  const freshCount = Math.max(
    0,
    Number(message.newlyCompactedMessageCount ?? message.compactedMessageCount ?? 0),
  );
  const compactedCount = Math.max(0, Number(message.compactedMessageCount ?? 0));
  const countForCopy = freshCount > 0 ? freshCount : compactedCount;
  const reason = String(message.compactionReason ?? "").toLowerCase();
  const lead = countForCopy > 0
    ? `${countForCopy} earlier ${countForCopy === 1 ? "message was" : "messages were"} ${
        reason === "manual" ? "manually folded" : "folded"
      } into a running summary.`
    : reason === "manual"
      ? "Earlier turns were manually folded into a running summary."
      : "Earlier turns were folded into a running summary.";
  const beforeTokens = Math.max(0, Number(message.historyRepresentationTokensBeforeCompaction ?? 0));
  const afterTokens = Math.max(0, Number(message.historyRepresentationTokensAfterCompaction ?? 0));
  const reductionCopy =
    beforeTokens > afterTokens && afterTokens > 0
      ? ` Atlas compressed the represented thread context from ${beforeTokens.toLocaleString()} to ${afterTokens.toLocaleString()} estimated tokens.`
      : "";
  const windowCopy =
    message.detectedContextWindow && message.detectedContextWindow > 0
      ? ` Model window: ${message.detectedContextWindow.toLocaleString()} tokens.`
      : "";
  return `${lead}${reductionCopy} Future turns use this summary plus the most recent raw turns.${windowCopy}`;
}

function timelineSystemBadgeLabel(message: ConversationMessage) {
  switch (message.kind) {
    case "run_queued":
      return "Queued";
    case "run_started":
      return "Started";
    case "run_stopped":
      return "Stopped";
    case "backend_restarted":
      return "Backend restarted";
    case "run_failed":
      return "Run failed";
    case "context_compacted":
      return "Context compacted";
    default:
      return "System";
  }
}

function timelineSystemBadgeClass(message: ConversationMessage) {
  switch (message.kind) {
    case "run_failed":
    case "backend_restarted":
      return "warning";
    case "run_stopped":
      return "muted";
    default:
      return "compacted";
  }
}

function timelineEphemeralLabel(message: ConversationMessage) {
  if (message.kind === "context_compacted") {
    return "during this response";
  }
  return "live";
}

function shouldSuppressWaitingCard(stage: string) {
  return stage === "queued" || stage === "starting" || stage === "stopping";
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
