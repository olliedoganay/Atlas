import * as ScrollArea from "@radix-ui/react-scroll-area";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  Plus,
  RotateCcw,
  Search,
  Settings,
  Workflow,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { duplicateThread, getModels, getStatus, getThreads, getUsers, resetThread, restartManagedBackend, type ThreadSummary } from "../lib/api";
import { ChatSearchDialog } from "./ChatSearchDialog";
import { ResetDialog } from "./ResetDialog";
import { RunStreamCoordinator } from "./RunStreamCoordinator";
import { useAtlasStore } from "../store/useAtlasStore";

const navigation = [
  { to: "/workspace", label: "Workspace", icon: Workflow },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function AtlasShell() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const currentUserId = useAtlasStore((state) => state.currentUserId);
  const currentThreadId = useAtlasStore((state) => state.currentThreadId);
  const currentThreadTitle = useAtlasStore((state) => state.currentThreadTitle);
  const draftThreadModel = useAtlasStore((state) => state.draftThreadModel);
  const draftThreadTemperature = useAtlasStore((state) => state.draftThreadTemperature);
  const navCollapsed = useAtlasStore((state) => state.navCollapsed);
  const setCurrentUserId = useAtlasStore((state) => state.setCurrentUserId);
  const setCurrentThreadId = useAtlasStore((state) => state.setCurrentThreadId);
  const setCurrentThreadTitle = useAtlasStore((state) => state.setCurrentThreadTitle);
  const setDraftThreadModel = useAtlasStore((state) => state.setDraftThreadModel);
  const setDraftThreadTemperature = useAtlasStore((state) => state.setDraftThreadTemperature);
  const setSearchJumpTarget = useAtlasStore((state) => state.setSearchJumpTarget);
  const toggleNavCollapsed = useAtlasStore((state) => state.toggleNavCollapsed);
  const isWorkspaceRoute = location.pathname === "/workspace";
  const [threadToDelete, setThreadToDelete] = useState<ThreadSummary | null>(null);
  const [isSearchOpen, setIsSearchOpen] = useState(false);

  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: getStatus,
    refetchInterval: 5000,
    retry: 1,
    refetchOnWindowFocus: false,
  });
  const { data: models } = useQuery({
    queryKey: ["models"],
    queryFn: getModels,
    staleTime: 10000,
    retry: 1,
    refetchOnWindowFocus: false,
  });
  const { data: users = [], isFetched: usersFetched } = useQuery({
    queryKey: ["users"],
    queryFn: getUsers,
    staleTime: 5000,
    retry: 1,
    refetchOnWindowFocus: false,
  });
  const currentUserProfile = users.find((user) => user.user_id === currentUserId);
  const currentUserLocked = Boolean(currentUserProfile?.locked);
  const { data: threads = [] } = useQuery({
    queryKey: ["threads", currentUserId],
    queryFn: () => getThreads(currentUserId),
    enabled: isWorkspaceRoute && Boolean(currentUserId) && !currentUserLocked,
    staleTime: 2000,
  });

  const deleteThreadMutation = useMutation({
    mutationFn: async (thread: ThreadSummary) => resetThread(thread.thread_id, thread.user_id || currentUserId),
    onMutate: async (thread) => {
      const resolvedUserId = thread.user_id || currentUserId;
      const queryKey = ["threads", resolvedUserId] as const;
      const deletedWasCurrent = resolvedUserId === currentUserId && thread.thread_id === currentThreadId;

      await queryClient.cancelQueries({ queryKey });
      const previousThreads = queryClient.getQueryData<ThreadSummary[]>(queryKey) ?? [];
      const nextThreads = previousThreads.filter(
        (item) => !isSameThread(item, thread, resolvedUserId),
      );

      queryClient.setQueryData(queryKey, nextThreads);
      queryClient.removeQueries({ queryKey: ["thread-history", resolvedUserId, thread.thread_id] });

      if (deletedWasCurrent) {
        const remaining = nextThreads.filter((item) => !isSameThread(item, thread, resolvedUserId));
        if (remaining.length > 0) {
          setCurrentThreadId(remaining[0].thread_id);
          setCurrentThreadTitle(remaining[0].title || remaining[0].thread_id);
          setDraftThreadModel(remaining[0].chat_model || defaultModel);
          setDraftThreadTemperature(resolveThreadTemperature(remaining[0], defaultTemperature));
        } else {
          createThread();
        }
      }
      return {
        previousThreads,
        queryKey,
        deletedWasCurrent,
        previousCurrentThreadId: currentThreadId,
        previousCurrentThreadTitle: currentThreadTitle,
        previousDraftThreadModel: draftThreadModel,
        previousDraftThreadTemperature: draftThreadTemperature,
      };
    },
    onError: (_error, _thread, context) => {
      if (context?.previousThreads) {
        queryClient.setQueryData(context.queryKey, context.previousThreads);
      }
      if (context?.deletedWasCurrent) {
        setCurrentThreadId(context.previousCurrentThreadId);
        setCurrentThreadTitle(context.previousCurrentThreadTitle);
        setDraftThreadModel(context.previousDraftThreadModel);
        setDraftThreadTemperature(context.previousDraftThreadTemperature);
      }
    },
    onSuccess: async () => {
      setThreadToDelete(null);
    },
    onSettled: async (_result, _error, thread) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads", thread.user_id || currentUserId] }),
        queryClient.invalidateQueries({ queryKey: ["thread-history", thread.user_id || currentUserId] }),
      ]);
    },
  });
  const duplicateThreadMutation = useMutation({
    mutationFn: async (thread: ThreadSummary) => duplicateThread(thread.thread_id, thread.user_id || currentUserId),
    onSuccess: async (thread) => {
      setCurrentThreadId(thread.thread_id);
      setCurrentThreadTitle(thread.title || thread.thread_id);
      setDraftThreadModel(thread.chat_model || defaultModel);
      setDraftThreadTemperature(resolveThreadTemperature(thread, defaultTemperature));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["threads", currentUserId] }),
        queryClient.invalidateQueries({ queryKey: ["thread-history", currentUserId] }),
      ]);
    },
  });

  const defaultModel =
    models?.default_model || status?.default_chat_model || status?.chat_model || draftThreadModel || "";
  const defaultTemperature =
    models?.default_temperature ?? status?.default_chat_temperature ?? status?.chat_temperature ?? 0.2;
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

  const displayThreadItems = useMemo(() => {
    if (!currentThreadId || threadItems.some((item) => item.thread_id === currentThreadId)) {
      return threadItems;
    }
    return [
      {
        user_id: currentUserId,
        thread_id: currentThreadId,
        title: currentThreadTitle || currentThreadId,
        chat_model: draftThreadModel || defaultModel,
        temperature: draftThreadTemperature,
        last_mode: "chat",
        updated_at: new Date().toISOString(),
        last_prompt: "",
        last_run_id: "",
      },
      ...threadItems,
    ];
  }, [currentThreadId, currentThreadTitle, currentUserId, defaultModel, defaultTemperature, draftThreadModel, draftThreadTemperature, threadItems]);

  useEffect(() => {
    if (usersFetched && currentUserId && (!currentUserProfile || currentUserProfile.locked)) {
      setCurrentUserId("");
      setCurrentThreadTitle("main");
      setCurrentThreadId("main");
    }
  }, [currentUserId, currentUserProfile, setCurrentThreadId, setCurrentThreadTitle, setCurrentUserId, usersFetched]);

  useEffect(() => {
    if (isWorkspaceRoute && !currentThreadId && threadItems.length) {
      setCurrentThreadId(threadItems[0].thread_id);
      setCurrentThreadTitle(threadItems[0].title || threadItems[0].thread_id);
    }
  }, [currentThreadId, isWorkspaceRoute, setCurrentThreadId, setCurrentThreadTitle, threadItems]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!isWorkspaceRoute || !currentUserId) {
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setIsSearchOpen(true);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentUserId, isWorkspaceRoute]);

  const restartBackend = async () => {
    await restartManagedBackend();
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["status"] }),
      queryClient.invalidateQueries({ queryKey: ["models"] }),
      queryClient.invalidateQueries({ queryKey: ["threads"] }),
    ]);
  };

  const selectThread = (thread: ThreadSummary) => {
    setCurrentThreadId(thread.thread_id);
    setCurrentThreadTitle(thread.title || thread.thread_id);
    setDraftThreadModel(thread.chat_model || defaultModel);
    setDraftThreadTemperature(resolveThreadTemperature(thread, defaultTemperature));
  };

  const createThread = () => {
    setCurrentThreadId(buildDraftThreadId());
    setCurrentThreadTitle("");
    setDraftThreadModel(defaultModel);
    setDraftThreadTemperature(null);
  };

  const userLabel = currentUserId || "No user selected";
  const backendOnline = Boolean(status);

  return (
    <div className={`app-shell ${navCollapsed ? "nav-collapsed" : ""}`}>
      <RunStreamCoordinator />
      <aside className={`global-nav ${navCollapsed ? "collapsed" : ""}`}>
        <div className="brand-lockup">
          <div className="brand-lockup-main">
            {navCollapsed ? <img alt="Atlas" className="brand-logo" src="/AtlasLogo.png" /> : null}
            <div className="brand-copy">
              <strong>Atlas</strong>
              <span>Local Workstation</span>
            </div>
          </div>
          <button className="ghost-button icon-button nav-toggle" onClick={toggleNavCollapsed} type="button">
            {navCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
        </div>

        <div className="global-nav-main">
          <nav className="nav-links">
            {navigation.map(({ to, label, icon: Icon }) => (
              <NavLink
                className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
                key={to}
                to={to}
              >
                <Icon size={18} />
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>

          {isWorkspaceRoute ? (
            <section className="shell-threads">
              {navCollapsed ? (
                <div className="collapsed-thread-list">
                  <button
                    className="ghost-button icon-button"
                    disabled={!currentUserId}
                    onClick={() => setIsSearchOpen(true)}
                    title="Search chats"
                    type="button"
                  >
                    <Search size={16} />
                  </button>
                  <button className="primary-button icon-button" disabled={!currentUserId} onClick={createThread} type="button">
                    <Plus size={16} />
                  </button>
                  {displayThreadItems.map((thread) => (
                    <button
                      className={`collapsed-thread-button ${thread.thread_id === currentThreadId ? "active" : ""}`}
                      key={thread.thread_id}
                      onClick={() => selectThread(thread)}
                      title={thread.thread_id}
                      type="button"
                    >
                      {thread.thread_id.slice(0, 1).toUpperCase()}
                    </button>
                  ))}
                </div>
              ) : (
                <>
                  <div className="workspace-section-head">
                    <div>
                      <p className="workspace-section-label">Chats</p>
                      <p className="muted-text">{formatChatCount(displayThreadItems.length)}</p>
                    </div>
                    <button className="primary-button icon-button" disabled={!currentUserId} onClick={createThread} type="button">
                      <Plus size={16} />
                    </button>
                  </div>

                  <button
                    className="search-launcher"
                    disabled={!currentUserId}
                    onClick={() => setIsSearchOpen(true)}
                    type="button"
                  >
                    <Search size={16} />
                    <span>Search chats</span>
                    <span className="search-launcher-shortcut">Ctrl+K</span>
                  </button>

                  <ScrollArea.Root className="thread-scroll shell-thread-scroll">
                    <ScrollArea.Viewport className="thread-scroll-viewport">
                      <div className="thread-list">
                        {displayThreadItems.map((thread) => (
                          <div
                            className={`thread-card ${thread.thread_id === currentThreadId ? "active" : ""}`}
                            key={thread.thread_id}
                          >
                            <button
                              aria-label={`Duplicate ${thread.title || thread.thread_id}`}
                              className="ghost-button icon-button thread-card-duplicate"
                              onClick={() => duplicateThreadMutation.mutate(thread)}
                              type="button"
                            >
                              <Copy size={14} />
                            </button>
                            <button
                              aria-label={`Delete ${thread.title || thread.thread_id}`}
                              className="ghost-button icon-button thread-card-delete"
                              onClick={() => setThreadToDelete(thread)}
                              type="button"
                            >
                              <X size={14} />
                            </button>
                            <button
                              className="thread-card-main"
                              onClick={() => selectThread(thread)}
                              type="button"
                            >
                              <div className="thread-card-top">
                                <strong>{thread.title || thread.thread_id}</strong>
                              </div>
                              <p>{thread.last_prompt || "Empty draft chat"}</p>
                              <div className="thread-card-foot">
                                <span>{thread.chat_model ? formatModelLabel(thread.chat_model) : "Select model"}</span>
                                <span>{formatDate(thread.updated_at)}</span>
                              </div>
                            </button>
                          </div>
                        ))}
                        {displayThreadItems.length === 0 ? (
                          <div className="thread-empty">
                            <p>{currentUserId ? "No chats yet for this profile." : "Choose a profile in the workspace first."}</p>
                            <button className="ghost-button compact-button" disabled={!currentUserId} onClick={createThread} type="button">
                              <Plus size={15} />
                              {currentUserId ? "Create first chat" : "Create chat"}
                            </button>
                          </div>
                        ) : null}
                      </div>
                    </ScrollArea.Viewport>
                    <ScrollArea.Scrollbar className="scrollbar" orientation="vertical">
                      <ScrollArea.Thumb className="scrollbar-thumb" />
                    </ScrollArea.Scrollbar>
                  </ScrollArea.Root>
                </>
              )}
            </section>
          ) : null}
        </div>

        <div className="nav-footer">
          <div className="nav-user">
            <div className="nav-user-avatar">{userLabel.slice(0, 1).toUpperCase()}</div>
            <div className="nav-user-copy">
              <strong>{userLabel}</strong>
              <span>Active profile</span>
            </div>
          </div>
          <div className={`status-pill ${backendOnline ? "online" : "offline"}`}>
            <span className="status-dot" />
            <span>{backendOnline ? "Backend online" : "Backend offline"}</span>
          </div>
          {!backendOnline ? (
            <button className="ghost-button full-width" onClick={restartBackend} type="button">
              <RotateCcw size={16} />
              Restart backend
            </button>
          ) : null}
        </div>
      </aside>

      <main className="main-shell">
        <section className="route-shell">
          <Outlet />
        </section>
      </main>

      <ResetDialog
        confirmLabel="Delete chat"
        description={`Delete "${threadToDelete?.title || threadToDelete?.thread_id || ""}", its thread history, traces, and thread-linked learned state?`}
        onConfirm={async () => {
          if (!threadToDelete) {
            return;
          }
          await deleteThreadMutation.mutateAsync(threadToDelete);
        }}
        onOpenChange={(open) => setThreadToDelete(open ? threadToDelete : null)}
        open={Boolean(threadToDelete)}
        title="Delete chat"
      />
      <ChatSearchDialog
        currentThreadId={currentThreadId}
        currentThreadTitle={currentThreadTitle}
        currentUserId={currentUserId}
        onOpenChange={setIsSearchOpen}
        onPick={(result, query) => {
          const existingThread = threadItems.find((item) => item.thread_id === result.thread_id);
          const targetThread: ThreadSummary = existingThread ?? {
            user_id: currentUserId,
            thread_id: result.thread_id,
            title: result.thread_title || result.thread_id,
            chat_model: result.chat_model || defaultModel,
            temperature: null,
            last_mode: "chat",
            updated_at: result.updated_at,
            last_prompt: "",
            last_run_id: "",
          };
          selectThread(targetThread);
          setSearchJumpTarget({
            userId: currentUserId,
            threadId: result.thread_id,
            historyIndex: typeof result.history_index === "number" ? result.history_index : null,
            query,
          });
          setIsSearchOpen(false);
        }}
        open={isSearchOpen}
      />
    </div>
  );
}

function formatDate(value?: string) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatModelLabel(value: string) {
  return value || "Select model";
}

function formatChatCount(count: number) {
  return `${count} ${count === 1 ? "chat" : "chats"}`;
}

function resolveThreadTemperature(thread: ThreadSummary | null | undefined, fallback: number): number | null {
  if (!thread || !Object.prototype.hasOwnProperty.call(thread, "temperature")) {
    return fallback;
  }
  return typeof thread.temperature === "number" && Number.isFinite(thread.temperature) ? thread.temperature : null;
}

function isSameThread(thread: ThreadSummary, target: ThreadSummary, fallbackUserId: string) {
  const threadUserId = thread.user_id || fallbackUserId;
  const targetUserId = target.user_id || fallbackUserId;
  return threadUserId === targetUserId && thread.thread_id === target.thread_id;
}

function buildDraftThreadId() {
  const timestamp = new Date().toISOString().replace(/[:.T]/g, "-").replace("Z", "");
  const suffix = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID().slice(0, 6)
    : Math.random().toString(36).slice(2, 8);
  return `atlas-${timestamp}-${suffix}`;
}
