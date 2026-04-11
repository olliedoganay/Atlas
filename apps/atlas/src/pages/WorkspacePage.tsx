import * as ScrollArea from "@radix-ui/react-scroll-area";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Copy, CornerUpLeft, Edit3, GitBranch, ImagePlus, Lock, RotateCcw, Search, Send, Square, X } from "lucide-react";
import { ChangeEvent, FormEvent, KeyboardEvent, UIEvent, useEffect, useMemo, useRef, useState } from "react";

import { MessageContent } from "../components/MessageContent";
import {
  cancelRun,
  branchThread,
  createUser,
  getRun,
  getModels,
  getStatus,
  getThreadHistory,
  getThreads,
  getUsers,
  renameThread,
  startCompact,
  startChat,
  type ImageAttachment,
  type ThreadMessage,
  type UserSummary,
  unlockUser,
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
  historyIndex?: number;
};

type UserProtectionMode = "passwordless" | "password";

export function WorkspacePage() {
  const queryClient = useQueryClient();
  const conversationViewportRef = useRef<HTMLDivElement | null>(null);
  const autoScrollToLatestRef = useRef(true);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const promptInputRef = useRef<HTMLTextAreaElement | null>(null);
  const [prompt, setPrompt] = useState("");
  const [attachments, setAttachments] = useState<ImageAttachment[]>([]);
  const [onboardingUserId, setOnboardingUserId] = useState("");
  const [onboardingUserProtection, setOnboardingUserProtection] = useState<UserProtectionMode>("passwordless");
  const [onboardingUserPassword, setOnboardingUserPassword] = useState("");
  const [unlockTargetUserId, setUnlockTargetUserId] = useState<string | null>(null);
  const [unlockPassword, setUnlockPassword] = useState("");

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
  const liveThinking = useAtlasStore((state) => state.liveThinking);
  const liveAnswer = useAtlasStore((state) => state.liveAnswer);
  const liveError = useAtlasStore((state) => state.liveError);
  const compactionNotice = useAtlasStore((state) => state.compactionNotice);
  const isStreaming = useAtlasStore((state) => state.isStreaming);
  const setCurrentUserId = useAtlasStore((state) => state.setCurrentUserId);
  const setCurrentThreadId = useAtlasStore((state) => state.setCurrentThreadId);
  const setCurrentThreadTitle = useAtlasStore((state) => state.setCurrentThreadTitle);
  const setDraftThreadModel = useAtlasStore((state) => state.setDraftThreadModel);
  const setDraftThreadTemperature = useAtlasStore((state) => state.setDraftThreadTemperature);
  const beginRun = useAtlasStore((state) => state.beginRun);
  const setStage = useAtlasStore((state) => state.setStage);
  const failRun = useAtlasStore((state) => state.failRun);
  const clearCompactionNotice = useAtlasStore((state) => state.clearCompactionNotice);
  const searchJumpTarget = useAtlasStore((state) => state.searchJumpTarget);
  const stepSearchJumpTarget = useAtlasStore((state) => state.stepSearchJumpTarget);
  const clearSearchJumpTarget = useAtlasStore((state) => state.clearSearchJumpTarget);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [expandedCompactionKeys, setExpandedCompactionKeys] = useState<Record<string, boolean>>({});
  const [isThinkingExpanded, setIsThinkingExpanded] = useState(false);
  const [highlightedHistoryIndex, setHighlightedHistoryIndex] = useState<number | null>(null);
  const [copiedMessageKey, setCopiedMessageKey] = useState<string | null>(null);

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
  const { data: users = [] } = useQuery({
    queryKey: ["users"],
    queryFn: getUsers,
    staleTime: 5000,
    retry: 1,
    refetchOnWindowFocus: false,
  });
  const visibleUsers = useMemo(() => {
    const seen = new Set<string>();
    return users.filter((user) => {
      if (!user.user_id || seen.has(user.user_id)) {
        return false;
      }
      seen.add(user.user_id);
      return true;
    });
  }, [users]);
  const currentUserProfile = visibleUsers.find((user) => user.user_id === currentUserId) ?? null;
  const currentUserLocked = Boolean(currentUserProfile?.locked);
  const { data: threads = [] } = useQuery({
    queryKey: ["threads", currentUserId],
    queryFn: () => getThreads(currentUserId),
    enabled: Boolean(currentUserId) && !currentUserLocked,
    staleTime: 2000,
  });
  const { data: history = [] } = useQuery({
    queryKey: ["thread-history", currentUserId, currentThreadId],
    queryFn: () => getThreadHistory(currentThreadId, currentUserId),
    enabled: Boolean(currentUserId && currentThreadId) && !currentUserLocked,
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
  const modelCatalogLoaded = Boolean(models);
  const availableModels = (models?.models ?? []).filter(Boolean);
  const ollamaOnline = Boolean(models?.ollama_online);
  const hasLocalModels = Boolean(models?.has_local_models);

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
    Boolean(currentRunId) &&
    isStreaming &&
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
  const preferredDraftModel = useMemo(() => {
    if (threadHasHistory && lockedThreadModel) {
      return lockedThreadModel;
    }
    if (draftThreadModel && availableModels.includes(draftThreadModel)) {
      return draftThreadModel;
    }
    if (defaultModel && availableModels.includes(defaultModel)) {
      return defaultModel;
    }
    return availableModels[0] || "";
  }, [availableModels, defaultModel, draftThreadModel, lockedThreadModel, threadHasHistory]);
  const selectedModel = lockedThreadModel || preferredDraftModel || draftThreadModel || defaultModel;
  const selectedTemperature = lockedThreadTemperature !== undefined ? lockedThreadTemperature : draftThreadTemperature;
  const selectedModelDetails = useMemo(
    () => models?.model_details?.find((item) => item.name === selectedModel),
    [models?.model_details, selectedModel],
  );
  const selectedModelSupportsImages = Boolean(selectedModelDetails?.supports_images);
  const headerSummary = !status
    ? "Local runtime offline. Restart Atlas from the sidebar to continue."
    : !currentUserId
      ? "Choose a profile before starting the first chat."
    : !modelCatalogLoaded
      ? "Checking the local Ollama model list."
    : !ollamaOnline
      ? "Atlas is online, but Ollama is not responding yet."
    : !hasLocalModels
      ? "Ollama is running, but there are no local chat models installed yet."
    : selectedModel
      ? "Model and temperature lock after the first message in this thread."
      : "Choose a local model and temperature before the first message.";
  const idleTitle = !status ? "Backend offline" : !currentUserId || !modelCatalogLoaded || !ollamaOnline || !hasLocalModels ? "Finish setup" : "Start the next thread";
  const idleDescription = !status
    ? "Atlas cannot load chats or models until the managed backend comes back online. Use the restart control in the sidebar when the runtime is ready."
    : !currentUserId
      ? "Choose a profile first. Atlas keeps chats, memory, and search scoped to the active profile."
    : !modelCatalogLoaded
      ? "Atlas is checking the local Ollama model list before the first message."
    : !ollamaOnline
      ? "Start Ollama on this machine, then refresh the local model list before sending the first message."
    : !hasLocalModels
      ? "Pull at least one local chat model with Ollama, then refresh Atlas to use it in new chats."
      : selectedModelSupportsImages
      ? "Ask a question, upload a photo for context, or use this thread as a clean branch for a new line of thinking."
      : "Use this thread to compare ideas, condense notes, or sketch the next move.";
  const composerPlaceholder = !status
    ? "Backend offline. Restart the local runtime to continue."
    : !currentUserId
      ? "Choose a profile before sending the first message."
      : !modelCatalogLoaded
        ? "Checking the local Ollama model list."
      : !ollamaOnline
        ? "Start Ollama on this machine first."
        : !hasLocalModels
          ? "Pull a local Ollama model before sending the first message."
          : !selectedModel
            ? "Choose a local model to start this chat."
            : selectedModelSupportsImages
              ? "Drop a photo, a rough brief, or the first line."
              : "Start with a question, a draft, or the next move.";
  const canStartChat = Boolean(
    status &&
      currentUserId &&
      !currentUserLocked &&
      modelCatalogLoaded &&
      ollamaOnline &&
      hasLocalModels &&
      selectedModel,
  );
  const currentThreadCompactionNotice = useMemo(() => {
    if (!compactionNotice) {
      return null;
    }
    if (compactionNotice.userId !== currentUserId || compactionNotice.threadId !== currentThreadId) {
      return null;
    }
    return compactionNotice;
  }, [compactionNotice, currentThreadId, currentUserId]);
  const activeSearchNavigator = useMemo(() => {
    if (!searchJumpTarget) {
      return null;
    }
    if (searchJumpTarget.userId !== currentUserId || searchJumpTarget.threadId !== currentThreadId) {
      return null;
    }
    const historyIndices = (searchJumpTarget.historyIndices ?? []).filter((value): value is number => typeof value === "number");
    if (!historyIndices.length) {
      return null;
    }
    const activePosition = Math.max(0, Math.min(historyIndices.length - 1, searchJumpTarget.activePosition ?? 0));
    return {
      query: searchJumpTarget.query,
      historyIndices,
      activePosition,
      historyIndex: historyIndices[activePosition] ?? null,
    };
  }, [currentThreadId, currentUserId, searchJumpTarget]);

  useEffect(() => {
    setDraftTitle(currentThread?.title || currentThreadTitle || currentThreadId || "");
    setIsEditingTitle(false);
  }, [currentThread?.title, currentThreadId, currentThreadTitle]);

  useEffect(() => {
    setExpandedCompactionKeys({});
  }, [currentUserId, currentThreadId]);

  useEffect(() => {
    setIsThinkingExpanded(false);
  }, [currentRunId]);

  const startRun = useMutation({
    mutationFn: async (value: string) => {
      if (!currentUserId) {
        throw new Error("Choose a profile before starting the first chat.");
      }
      if (!ollamaOnline) {
        throw new Error("Start Ollama on this machine before starting the first chat.");
      }
      if (!hasLocalModels) {
        throw new Error("Pull a local chat model with Ollama before starting the first chat.");
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

  const branchMessage = useMutation({
    mutationFn: async (payload: { afterMessageCount: number }) => {
      if (!currentUserId) {
        throw new Error("Choose a profile before branching this chat.");
      }
      return branchThread(currentThreadId, currentUserId, payload.afterMessageCount);
    },
    onSuccess: async (thread) => {
      setCurrentThreadId(thread.thread_id);
      setCurrentThreadTitle(thread.title || thread.thread_id);
      setDraftThreadModel(thread.chat_model || defaultModel);
      setDraftThreadTemperature(readStoredTemperature(thread) ?? null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads", currentUserId] }),
        queryClient.invalidateQueries({ queryKey: ["thread-history", currentUserId] }),
      ]);
    },
  });

  const retryAssistantTurn = useMutation({
    mutationFn: async (payload: { afterMessageCount: number; prompt: string; attachments: ImageAttachment[] }) => {
      if (!currentUserId) {
        throw new Error("Choose a profile before retrying a response.");
      }
      const thread = await branchThread(currentThreadId, currentUserId, payload.afterMessageCount);
      const run = await startChat(
        payload.prompt,
        currentUserId,
        thread.thread_id,
        thread.chat_model || selectedModel,
        readStoredTemperature(thread) ?? selectedTemperature ?? null,
        thread.title || thread.thread_id,
        crossChatMemoryEnabled,
        autoCompactLongChats,
        payload.attachments,
      );
      return { thread, run, prompt: payload.prompt, attachments: payload.attachments };
    },
    onSuccess: async ({ thread, run, prompt: retryPrompt, attachments: retryAttachments }) => {
      autoScrollToLatestRef.current = true;
      setCurrentThreadId(thread.thread_id);
      setCurrentThreadTitle(thread.title || thread.thread_id);
      setDraftThreadModel(thread.chat_model || defaultModel);
      setDraftThreadTemperature(readStoredTemperature(thread) ?? null);
      beginRun(run.run_id, "chat", retryPrompt, currentUserId, thread.thread_id, retryAttachments);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads", currentUserId] }),
        queryClient.invalidateQueries({ queryKey: ["thread-history", currentUserId] }),
      ]);
    },
    onError: (error) => {
      failRun(error instanceof Error ? error.message : "Atlas could not retry this response.");
    },
  });

  const activateUser = async (user: UserSummary) => {
    setCurrentUserId(user.user_id);
    setCurrentThreadId("main");
    setCurrentThreadTitle("main");
    setDraftThreadTemperature(null);
    if (preferredDraftModel) {
      setDraftThreadModel(preferredDraftModel);
    }
    setUnlockPassword("");
    setUnlockTargetUserId(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["users"] }),
      queryClient.invalidateQueries({ queryKey: ["threads"] }),
      queryClient.invalidateQueries({ queryKey: ["thread-history"] }),
      queryClient.invalidateQueries({ queryKey: ["models"] }),
    ]);
  };

  const createOnboardingUser = useMutation({
    mutationFn: async () =>
      createUser(
        onboardingUserId.trim(),
        onboardingUserProtection === "password" ? onboardingUserPassword.trim() : undefined,
      ),
    onSuccess: async (user) => {
      setOnboardingUserId("");
      setOnboardingUserProtection("passwordless");
      setOnboardingUserPassword("");
      await activateUser(user);
    },
  });

  const unlockOnboardingUser = useMutation({
    mutationFn: async (payload: { userId: string; password?: string }) =>
      unlockUser(payload.userId, payload.password),
    onSuccess: async (user) => {
      await activateUser(user);
    },
  });

  const refreshModels = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["status"] }),
      queryClient.invalidateQueries({ queryKey: ["models"] }),
      queryClient.invalidateQueries({ queryKey: ["threads"] }),
    ]);
  };

  useEffect(() => {
    if (!currentThreadId && threadItems.length) {
      setCurrentThreadId(threadItems[0].thread_id);
    }
  }, [currentThreadId, setCurrentThreadId, threadItems]);

  useEffect(() => {
    if (threadHasHistory) {
      return;
    }
    if (!preferredDraftModel) {
      return;
    }
    if (draftThreadModel !== preferredDraftModel) {
      setDraftThreadModel(preferredDraftModel);
    }
  }, [draftThreadModel, preferredDraftModel, setDraftThreadModel, threadHasHistory]);

  useEffect(() => {
    const resolvedTitle = currentThread?.title || currentThreadId || "";
    if (resolvedTitle && resolvedTitle !== currentThreadTitle) {
      setCurrentThreadTitle(resolvedTitle);
    }
  }, [currentThread?.title, currentThreadId, currentThreadTitle, setCurrentThreadTitle]);

  const transcript = useMemo(() => {
    const items: ConversationMessage[] = history.map((item: ThreadMessage, historyIndex) => ({
      role: item.role,
      content: item.content,
      attachments: item.attachments,
      historyIndex,
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
  }, [currentThreadCompactionNotice, currentThreadHasActiveRun, history, liveAnswer, pendingAttachments, pendingPrompt]);
  const shouldShowOnboarding = Boolean(
    status &&
      modelCatalogLoaded &&
      transcript.length === 0 &&
      (!currentUserId || !ollamaOnline || !hasLocalModels),
  );

  useEffect(() => {
    autoScrollToLatestRef.current = true;
  }, [currentUserId, currentThreadId]);

  useEffect(() => {
    if (!searchJumpTarget) {
      return;
    }
    if (searchJumpTarget.userId !== currentUserId || searchJumpTarget.threadId !== currentThreadId) {
      return;
    }
    if (searchJumpTarget.historyIndex === null || searchJumpTarget.historyIndex === undefined) {
      if (!searchJumpTarget.historyIndices?.length) {
        clearSearchJumpTarget();
      }
      return;
    }
    const targetHistoryIndex = searchJumpTarget.historyIndex;
    const targetElement = conversationViewportRef.current?.querySelector<HTMLElement>(
      `[data-history-index="${targetHistoryIndex}"]`,
    );
    if (!targetElement) {
      return;
    }
    autoScrollToLatestRef.current = false;
    targetElement.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlightedHistoryIndex(targetHistoryIndex);
  }, [clearSearchJumpTarget, currentThreadId, currentUserId, searchJumpTarget, transcript]);

  useEffect(() => {
    if (highlightedHistoryIndex === null) {
      return undefined;
    }
    const timer = window.setTimeout(() => setHighlightedHistoryIndex(null), 2400);
    return () => window.clearTimeout(timer);
  }, [highlightedHistoryIndex]);

  useEffect(() => {
    if (!activeSearchNavigator) {
      return undefined;
    }
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "F3") {
        event.preventDefault();
        stepSearchJumpTarget(event.shiftKey ? -1 : 1);
        return;
      }
      if (event.key === "Escape") {
        clearSearchJumpTarget();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeSearchNavigator, clearSearchJumpTarget, stepSearchJumpTarget]);

  useEffect(() => {
    if (!copiedMessageKey) {
      return undefined;
    }
    const timer = window.setTimeout(() => setCopiedMessageKey(null), 1600);
    return () => window.clearTimeout(timer);
  }, [copiedMessageKey]);

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

  const handleCopyMessage = async (message: ConversationMessage, index: number) => {
    const key = messageActionKey(message, index, "copy");
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(message.content);
      }
      setCopiedMessageKey(key);
    } catch {
      // Ignore clipboard failures silently. The action should stay non-blocking.
    }
  };

  const handleQuoteMessage = (message: ConversationMessage) => {
    const quoted = buildQuotedPrompt(message.content);
    setPrompt((current) => (current.trim() ? `${current.trim()}\n\n${quoted}` : quoted));
    promptInputRef.current?.focus();
  };

  const submitPrompt = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if ((!prompt.trim() && attachments.length === 0) || isStreaming || !canStartChat) {
      return;
    }
    startRun.mutate(prompt.trim());
  };

  const handlePromptKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      if ((!prompt.trim() && attachments.length === 0) || isStreaming || !canStartChat) {
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
          <p className="workspace-title-summary">{headerSummary}</p>
        </div>

        <div className="workspace-header-controls">
          <div className="workspace-header-control-strip">
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
      </div>

      <div className="conversation-shell">
        {activeSearchNavigator ? (
          <div className="search-inline-navigator">
            <div className="search-inline-copy">
              <span className="status-pill subtle muted">
                <Search size={13} />
                Find in chat
              </span>
              <strong>{activeSearchNavigator.query}</strong>
              <span className="muted-text">
                {activeSearchNavigator.activePosition + 1} / {activeSearchNavigator.historyIndices.length}
              </span>
            </div>
            <div className="search-inline-actions">
              <button
                className="ghost-button icon-button"
                disabled={activeSearchNavigator.activePosition <= 0}
                onClick={() => stepSearchJumpTarget(-1)}
                type="button"
              >
                <ChevronLeft size={15} />
              </button>
              <button
                className="ghost-button icon-button"
                disabled={activeSearchNavigator.activePosition >= activeSearchNavigator.historyIndices.length - 1}
                onClick={() => stepSearchJumpTarget(1)}
                type="button"
              >
                <ChevronRight size={15} />
              </button>
              <button
                className="ghost-button compact-button"
                onClick={() => clearSearchJumpTarget()}
                type="button"
              >
                <X size={14} />
                Close
              </button>
            </div>
          </div>
        ) : null}
        <ScrollArea.Root className="conversation-scroll">
          <ScrollArea.Viewport
            className="conversation-viewport"
            onScroll={handleConversationScroll}
            ref={conversationViewportRef}
          >
            <div className="conversation-stack">
              {transcript.length === 0 ? (
                <div className="workspace-idle">
                  <div className={`workspace-idle-card${shouldShowOnboarding ? " workspace-onboarding-card" : ""}`}>
                    <div className="workspace-idle-mark">
                      <img alt="Atlas" className="workspace-idle-logo workspace-idle-logo-large" src="/AtlasLogo.png" />
                    </div>
                    <span className="workspace-idle-kicker">
                      {shouldShowOnboarding ? "First-run setup" : selectedModel ? formatModelLabel(selectedModel) : "New thread"}
                    </span>
                    <h2>{idleTitle}</h2>
                    <p>{idleDescription}</p>
                    {shouldShowOnboarding ? (
                      <div className="workspace-onboarding-steps">
                        <section className={`workspace-onboarding-step ${currentUserId ? "complete" : "active"}`}>
                          <div className="workspace-onboarding-step-head">
                            <span className="workspace-onboarding-step-index">1</span>
                            <div className="workspace-onboarding-step-copy">
                              <strong>Create or select a profile</strong>
                              <p>Chats, memory, and search stay scoped to the active local profile.</p>
                            </div>
                            <span className="workspace-onboarding-step-state">{currentUserId ? "Ready" : "Needed"}</span>
                          </div>
                          {currentUserId ? (
                            <div className="workspace-onboarding-summary">
                              Using <strong>{currentUserId}</strong>{currentUserProfile ? ` - ${describeUserProtection(currentUserProfile)}` : ""}.
                            </div>
                          ) : (
                            <div className="workspace-onboarding-step-body">
                              {visibleUsers.length > 0 ? (
                                <div className="workspace-onboarding-profile-list">
                                  {visibleUsers.map((user) => {
                                    const isProtected = user.protection === "password";
                                    const isLocked = Boolean(user.locked);
                                    const isUnlocking = unlockTargetUserId === user.user_id;
                                    return (
                                      <div className="workspace-onboarding-profile-card" key={user.user_id}>
                                        <div className="workspace-onboarding-profile-copy">
                                          <strong>{user.user_id}</strong>
                                          <span>{describeUserProtection(user)}</span>
                                        </div>
                                        {!isLocked ? (
                                          <button
                                            className="ghost-button compact-button"
                                            onClick={() => {
                                              void activateUser(user);
                                            }}
                                            type="button"
                                          >
                                            Use profile
                                          </button>
                                        ) : (
                                          <button
                                            className="ghost-button compact-button"
                                            onClick={() => {
                                              setUnlockTargetUserId(user.user_id);
                                              setUnlockPassword("");
                                            }}
                                            type="button"
                                          >
                                            Unlock
                                          </button>
                                        )}
                                        {isProtected && isLocked && isUnlocking ? (
                                          <div className="workspace-onboarding-inline-form">
                                            <input
                                              className="text-input"
                                              onChange={(event) => setUnlockPassword(event.currentTarget.value)}
                                              placeholder="Profile password"
                                              type="password"
                                              value={unlockPassword}
                                            />
                                            <button
                                              className="primary-button compact-button"
                                              disabled={!unlockPassword.trim() || unlockOnboardingUser.isPending}
                                              onClick={() =>
                                                unlockOnboardingUser.mutate({
                                                  userId: user.user_id,
                                                  password: unlockPassword.trim(),
                                                })
                                              }
                                              type="button"
                                            >
                                              {unlockOnboardingUser.isPending ? "Unlocking..." : "Unlock"}
                                            </button>
                                          </div>
                                        ) : null}
                                      </div>
                                    );
                                  })}
                                </div>
                              ) : (
                                <div className="workspace-onboarding-summary">
                                  No profiles exist yet. Create the first one here.
                                </div>
                              )}

                              <div className="workspace-onboarding-create">
                                <div className="workspace-onboarding-inline-form">
                                  <input
                                    className="text-input"
                                    onChange={(event) => setOnboardingUserId(event.currentTarget.value)}
                                    placeholder="new_profile"
                                    value={onboardingUserId}
                                  />
                                  <div className="segmented-control">
                                    <button
                                      className={`segmented-button ${onboardingUserProtection === "passwordless" ? "active" : ""}`}
                                      onClick={() => setOnboardingUserProtection("passwordless")}
                                      type="button"
                                    >
                                      Passwordless
                                    </button>
                                    <button
                                      className={`segmented-button ${onboardingUserProtection === "password" ? "active" : ""}`}
                                      onClick={() => setOnboardingUserProtection("password")}
                                      type="button"
                                    >
                                      Password
                                    </button>
                                  </div>
                                </div>
                                {onboardingUserProtection === "password" ? (
                                  <div className="workspace-onboarding-inline-form">
                                    <input
                                      className="text-input"
                                      onChange={(event) => setOnboardingUserPassword(event.currentTarget.value)}
                                      placeholder="Profile password"
                                      type="password"
                                      value={onboardingUserPassword}
                                    />
                                  </div>
                                ) : null}
                                <div className="workspace-onboarding-inline-form">
                                  <button
                                    className="primary-button compact-button"
                                    disabled={
                                      !onboardingUserId.trim() ||
                                      createOnboardingUser.isPending ||
                                      (onboardingUserProtection === "password" && !onboardingUserPassword.trim())
                                    }
                                    onClick={() => createOnboardingUser.mutate()}
                                    type="button"
                                  >
                                    {createOnboardingUser.isPending ? "Creating..." : "Create profile"}
                                  </button>
                                </div>
                                {createOnboardingUser.isError ? (
                                  <div className="error-inline">{getMutationErrorMessage(createOnboardingUser.error)}</div>
                                ) : null}
                                {unlockOnboardingUser.isError ? (
                                  <div className="error-inline">{getMutationErrorMessage(unlockOnboardingUser.error)}</div>
                                ) : null}
                              </div>
                            </div>
                          )}
                        </section>

                        <section
                          className={`workspace-onboarding-step ${
                            !currentUserId ? "blocked" : ollamaOnline && hasLocalModels ? "complete" : "active"
                          }`}
                        >
                          <div className="workspace-onboarding-step-head">
                            <span className="workspace-onboarding-step-index">2</span>
                            <div className="workspace-onboarding-step-copy">
                              <strong>Confirm local model access</strong>
                              <p>Atlas needs Ollama running and at least one installed chat model before the first turn.</p>
                            </div>
                            <span className="workspace-onboarding-step-state">
                              {ollamaOnline && hasLocalModels ? "Ready" : !currentUserId ? "Waiting" : "Needed"}
                            </span>
                          </div>
                          <div className="workspace-onboarding-step-body">
                            {!currentUserId ? (
                              <div className="workspace-onboarding-summary">Finish step 1 first.</div>
                            ) : !ollamaOnline ? (
                              <>
                                <div className="workspace-onboarding-summary">
                                  Atlas is online, but Ollama is not responding at <strong>{status?.ollama_url}</strong>.
                                </div>
                                <div className="workspace-onboarding-inline-form">
                                  <code className="workspace-onboarding-command">ollama serve</code>
                                  <button className="ghost-button compact-button" onClick={() => void refreshModels()} type="button">
                                    Refresh
                                  </button>
                                </div>
                              </>
                            ) : !hasLocalModels ? (
                              <>
                                <div className="workspace-onboarding-summary">
                                  Ollama is running, but there are no local chat models installed yet.
                                </div>
                                <div className="workspace-onboarding-inline-form">
                                  <code className="workspace-onboarding-command">ollama pull qwen3.5:9b</code>
                                  <button className="ghost-button compact-button" onClick={() => void refreshModels()} type="button">
                                    Refresh
                                  </button>
                                </div>
                              </>
                            ) : (
                              <div className="workspace-onboarding-summary">
                                Ready with <strong>{formatModelLabel(selectedModel)}</strong> at{" "}
                                <strong>{formatTemperatureLabel(selectedTemperature)}</strong>. You can still change both in the header before the first message.
                              </div>
                            )}
                          </div>
                        </section>

                        <section className={`workspace-onboarding-step ${canStartChat ? "complete" : "blocked"}`}>
                          <div className="workspace-onboarding-step-head">
                            <span className="workspace-onboarding-step-index">3</span>
                            <div className="workspace-onboarding-step-copy">
                              <strong>Start the first chat</strong>
                              <p>Once the profile and model are ready, use the composer below to send the first message.</p>
                            </div>
                            <span className="workspace-onboarding-step-state">{canStartChat ? "Ready" : "Waiting"}</span>
                          </div>
                          <div className="workspace-onboarding-step-body">
                            {canStartChat ? (
                              <div className="workspace-onboarding-inline-form">
                                <button
                                  className="primary-button compact-button"
                                  onClick={() => promptInputRef.current?.focus()}
                                  type="button"
                                >
                                  Focus composer
                                </button>
                                <span className="muted-text">Type the first prompt below and click Send.</span>
                              </div>
                            ) : (
                              <div className="workspace-onboarding-summary">
                                Complete the first two steps to unlock the composer.
                              </div>
                            )}
                          </div>
                        </section>
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}
              {transcript.map((message, index) => {
                const branchAfterMessageCount = countConversationMessagesThroughIndex(transcript, index);
                const canBranchMessage = isBranchableMessage(message) && branchAfterMessageCount > 0 && Boolean(currentUserId);
                const retryContext = getRetryContext(transcript, index);

                return isContextCompactionMessage(message) ? (
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
                  <article
                    className={`message-card ${message.role}${message.historyIndex === highlightedHistoryIndex ? " search-hit-active" : ""}`}
                    data-history-index={message.historyIndex}
                    key={`${message.role}-${index}-${message.content.length}`}
                  >
                    <div className="message-meta message-meta-row">
                      <span>{formatMessageRoleLabel(message.role)}</span>
                      <div className="message-actions" aria-label="Message actions">
                        <button
                          className="ghost-button icon-button compact-button"
                          onClick={() => void handleCopyMessage(message, index)}
                          type="button"
                        >
                          <Copy size={14} />
                          <span>{copiedMessageKey === messageActionKey(message, index, "copy") ? "Copied" : "Copy"}</span>
                        </button>
                        <button
                          className="ghost-button icon-button compact-button"
                          onClick={() => handleQuoteMessage(message)}
                          type="button"
                        >
                          <CornerUpLeft size={14} />
                          <span>Quote</span>
                        </button>
                        {canBranchMessage ? (
                          <button
                            className="ghost-button icon-button compact-button"
                            disabled={branchMessage.isPending || retryAssistantTurn.isPending}
                            onClick={() => branchMessage.mutate({ afterMessageCount: branchAfterMessageCount })}
                            type="button"
                          >
                            <GitBranch size={14} />
                            <span>{branchMessage.isPending ? "Branching..." : "Branch"}</span>
                          </button>
                        ) : null}
                        {retryContext ? (
                          <button
                            className="ghost-button icon-button compact-button"
                            disabled={retryAssistantTurn.isPending || branchMessage.isPending || isStreaming}
                            onClick={() =>
                              retryAssistantTurn.mutate({
                                afterMessageCount: retryContext.afterMessageCount,
                                prompt: retryContext.prompt,
                                attachments: retryContext.attachments,
                              })
                            }
                            type="button"
                          >
                            <RotateCcw size={14} />
                            <span>{retryAssistantTurn.isPending ? "Retrying..." : "Retry"}</span>
                          </button>
                        ) : null}
                      </div>
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
                );
              })}
              {currentThreadHasActiveRun && isStreaming && !liveAnswer ? (
                <article className={`message-card ${currentRunMode === "compact" ? "system" : "assistant"} message-card-waiting`}>
                  <div className="message-meta">
                    <span>{currentRunMode === "compact" ? "SYSTEM" : formatMessageRoleLabel("assistant")}</span>
                  </div>
                  {currentRunMode === "compact" ? (
                    <div className="stream-waiting-line" aria-live="polite">
                      <span>{compactWaitingLabel(currentStage)}</span>
                      <span className="stream-dots" aria-hidden="true">
                        <span />
                        <span />
                        <span />
                      </span>
                    </div>
                  ) : (
                    <>
                      <button
                        aria-expanded={liveThinking ? isThinkingExpanded : false}
                        className={`thinking-toggle ${liveThinking ? "interactive" : ""}`}
                        onClick={() => {
                          if (!liveThinking) {
                            return;
                          }
                          setIsThinkingExpanded((current) => !current);
                        }}
                        type="button"
                      >
                        <span className="stream-waiting-line" aria-live="polite">
                          <span>{chatWaitingLabel(currentStage)}</span>
                          <span className="stream-dots" aria-hidden="true">
                            <span />
                            <span />
                            <span />
                          </span>
                        </span>
                        {liveThinking ? (
                          isThinkingExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />
                        ) : null}
                      </button>
                      {isThinkingExpanded && liveThinking ? (
                        <div className="thinking-panel">
                          <pre className="thinking-panel-text">{liveThinking}</pre>
                        </div>
                      ) : null}
                    </>
                  )}
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
          ref={promptInputRef}
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
          <button className="primary-button" disabled={isStreaming || (!prompt.trim() && attachments.length === 0) || !canStartChat} type="submit">
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
  return message.kind === "context_compacted" ? "Context compacted" : "System";
}

function timelineSystemBadgeClass(message: ConversationMessage) {
  return message.kind === "context_compacted" ? "compacted" : "muted";
}

function timelineEphemeralLabel(message: ConversationMessage) {
  return message.kind === "context_compacted" ? "during this response" : "live";
}

function chatWaitingLabel(stage: string) {
  if (stage === "queued") {
    return "Queued";
  }
  if (stage === "stopping") {
    return "Stopping";
  }
  return "Deciding";
}

function compactWaitingLabel(stage: string) {
  if (stage === "queued") {
    return "Compaction queued";
  }
  if (stage === "stopping") {
    return "Stopping compaction";
  }
  return "Compacting older context";
}

function isBranchableMessage(message: ConversationMessage) {
  return (message.role === "user" || message.role === "assistant") && !message.ephemeral && !message.kind;
}

function countConversationMessagesThroughIndex(transcript: ConversationMessage[], index: number) {
  return transcript.slice(0, index + 1).filter((item) => isBranchableMessage(item)).length;
}

function getRetryContext(transcript: ConversationMessage[], index: number) {
  const message = transcript[index];
  if (message.role !== "assistant" || message.ephemeral || message.kind) {
    return null;
  }
  const laterAssistant = transcript
    .slice(index + 1)
    .some((item) => item.role === "assistant" && !item.ephemeral && !item.kind);
  if (laterAssistant) {
    return null;
  }
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const candidate = transcript[cursor];
    if (candidate.role !== "user" || candidate.ephemeral || candidate.kind) {
      continue;
    }
    return {
      afterMessageCount: countConversationMessagesThroughIndex(transcript, cursor),
      prompt: candidate.content,
      attachments: candidate.attachments ?? [],
    };
  }
  return null;
}

function buildQuotedPrompt(content: string) {
  return content
    .split(/\r?\n/)
    .map((line) => `> ${line}`)
    .join("\n");
}

function messageActionKey(message: ConversationMessage, index: number, action: string) {
  return `${action}:${message.runId || message.timestamp || message.historyIndex || index}:${message.role}`;
}

function describeUserProtection(user: { protection?: string; locked?: boolean }) {
  if (user.protection === "password") {
    return user.locked ? "Password protected - Locked" : "Password protected";
  }
  return "Passwordless";
}

function getMutationErrorMessage(error: unknown) {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "The request did not complete.";
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
