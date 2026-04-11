import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Database, Info, Monitor, Plus, SlidersHorizontal } from "lucide-react";

import { ResetDialog } from "../components/ResetDialog";
import { createMemory, createUser, deleteMemory, deleteUser, getMemories, getModels, getStatus, getUsers, resetAll } from "../lib/api";
import { useAtlasStore } from "../store/useAtlasStore";

type SettingsSection = "general" | "models" | "data" | "about";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const theme = useAtlasStore((state) => state.theme);
  const setTheme = useAtlasStore((state) => state.setTheme);
  const currentUserId = useAtlasStore((state) => state.currentUserId);
  const crossChatMemoryEnabled = useAtlasStore((state) => state.crossChatMemoryEnabled);
  const autoCompactLongChats = useAtlasStore((state) => state.autoCompactLongChats);
  const setCurrentUserId = useAtlasStore((state) => state.setCurrentUserId);
  const setCurrentThreadId = useAtlasStore((state) => state.setCurrentThreadId);
  const setCurrentThreadTitle = useAtlasStore((state) => state.setCurrentThreadTitle);
  const setDraftThreadModel = useAtlasStore((state) => state.setDraftThreadModel);
  const setDraftThreadTemperature = useAtlasStore((state) => state.setDraftThreadTemperature);
  const setCrossChatMemoryEnabled = useAtlasStore((state) => state.setCrossChatMemoryEnabled);
  const setAutoCompactLongChats = useAtlasStore((state) => state.setAutoCompactLongChats);
  const [dialog, setDialog] = useState<"all" | "user" | null>(null);
  const [section, setSection] = useState<SettingsSection>("general");
  const [newUserId, setNewUserId] = useState("");
  const [memoryDraft, setMemoryDraft] = useState("");
  const [pendingDeleteUserId, setPendingDeleteUserId] = useState<string | null>(null);
  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: getStatus,
    staleTime: 5000,
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
  const { data: memories = [] } = useQuery({
    queryKey: ["memories", currentUserId],
    queryFn: () => getMemories(currentUserId),
    enabled: Boolean(currentUserId),
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
  const manualMemories = useMemo(
    () =>
      memories.filter(
        (memory) =>
          memory.metadata?.source === "manual" ||
          memory.metadata?.kind === "memory_note",
      ),
    [memories],
  );
  const defaultModel = models?.default_model ?? status?.default_chat_model ?? status?.chat_model ?? "";

  useEffect(() => {
    if (usersFetched && currentUserId && !visibleUsers.some((user) => user.user_id === currentUserId)) {
      setCurrentUserId("");
      setCurrentThreadId("main");
      setCurrentThreadTitle("main");
      setDraftThreadModel(defaultModel);
      setDraftThreadTemperature(null);
    }
  }, [
    currentUserId,
    defaultModel,
    setCurrentThreadId,
    setCurrentThreadTitle,
    setCurrentUserId,
    setDraftThreadModel,
    setDraftThreadTemperature,
    visibleUsers,
    usersFetched,
  ]);

  const allReset = useMutation({
    mutationFn: resetAll,
    onSuccess: async () => {
      setCurrentThreadId("main");
      setCurrentThreadTitle("main");
      await queryClient.invalidateQueries();
    },
  });
  const createUserMutation = useMutation({
    mutationFn: async () => createUser(newUserId.trim()),
    onSuccess: async (user) => {
      setCurrentUserId(user.user_id);
      setCurrentThreadId("main");
      setCurrentThreadTitle("main");
      setNewUserId("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["users"] }),
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["thread-history"] }),
      ]);
    },
  });
  const createMemoryMutation = useMutation({
    mutationFn: async () => {
      if (!currentUserId) {
        throw new Error("Select a user before saving memory.");
      }
      return createMemory(currentUserId, memoryDraft.trim());
    },
    onSuccess: async () => {
      setMemoryDraft("");
      await queryClient.invalidateQueries({ queryKey: ["memories", currentUserId] });
    },
  });
  const deleteMemoryMutation = useMutation({
    mutationFn: async (memoryId: string) => {
      if (!currentUserId) {
        throw new Error("Select a user before deleting memory.");
      }
      return deleteMemory(currentUserId, memoryId);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["memories", currentUserId] });
    },
  });
  const deleteUserMutation = useMutation({
    mutationFn: async (userId: string) => deleteUser(userId),
    onSuccess: async (_, deletedUserId) => {
      queryClient.setQueryData(["users"], (existing: Array<{ user_id: string; updated_at?: string }> | undefined) =>
        (existing ?? []).filter((user) => user.user_id !== deletedUserId),
      );
      queryClient.removeQueries({ queryKey: ["threads", deletedUserId] });
      queryClient.removeQueries({ queryKey: ["thread-history", deletedUserId] });
      queryClient.removeQueries({ queryKey: ["memories", deletedUserId] });

      if (currentUserId === deletedUserId) {
        setCurrentUserId("");
        setCurrentThreadId("main");
        setCurrentThreadTitle("main");
        setDraftThreadModel(defaultModel);
        setDraftThreadTemperature(null);
      }

      setPendingDeleteUserId(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["users"] }),
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["thread-history"] }),
        queryClient.invalidateQueries({ queryKey: ["memories"] }),
      ]);
    },
  });

  const sections = [
    { id: "general", label: "General", icon: SlidersHorizontal },
    { id: "models", label: "Models", icon: Monitor },
    { id: "data", label: "Data", icon: Database },
    { id: "about", label: "About", icon: Info },
  ] as const;
  const activeSectionLabel = sections.find((item) => item.id === section)?.label ?? "General";
  const activeSectionDescription =
    section === "general"
      ? "Operator identity, theme, and memory behavior."
      : section === "models"
        ? "Runtime defaults, temperature behavior, and local model inventory."
        : section === "data"
          ? "Backend lifecycle controls and durable local state."
          : "Runtime facts and desktop version information.";

  return (
    <div className="settings-page">
      <div className="settings-layout">
        <aside className="settings-nav">
          {sections.map(({ id, label, icon: Icon }) => (
            <button
              className={`settings-nav-button ${section === id ? "active" : ""}`}
              key={id}
              onClick={() => setSection(id)}
              type="button"
            >
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </aside>

        <section className="settings-body">
          <div className="settings-section-header">
            <h2>{activeSectionLabel}</h2>
            <p>{activeSectionDescription}</p>
          </div>

          {section === "general" ? (
            <div className="settings-rows">
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Theme</strong>
                  <p>Choose the desktop appearance.</p>
                </div>
                <div className="segmented-control">
                  <button
                    className={`segmented-button ${theme === "light" ? "active" : ""}`}
                    onClick={() => setTheme("light")}
                    type="button"
                  >
                    Light
                  </button>
                  <button
                    className={`segmented-button ${theme === "dark" ? "active" : ""}`}
                    onClick={() => setTheme("dark")}
                    type="button"
                  >
                    Dark
                  </button>
                </div>
              </div>

              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Current user</strong>
                  <p>Persistent memory is scoped to this user. Switch between saved users here.</p>
                </div>
                <select
                  className="select-input settings-select"
                  onChange={(event) => {
                    const nextUser = event.currentTarget.value;
                    setCurrentUserId(nextUser);
                    setCurrentThreadId("main");
                    setCurrentThreadTitle("main");
                    void Promise.all([
                      queryClient.invalidateQueries({ queryKey: ["threads"] }),
                      queryClient.invalidateQueries({ queryKey: ["thread-history"] }),
                    ]);
                  }}
                  value={currentUserId}
                >
                  {!currentUserId ? <option value="">No user selected</option> : null}
                  {visibleUsers.map((user) => (
                    <option key={user.user_id} value={user.user_id}>
                      {user.user_id}
                    </option>
                  ))}
                </select>
              </div>

              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Cross-chat memory</strong>
                  <p>When enabled, Atlas can recall durable facts from other chats for the current user.</p>
                </div>
                <div className="segmented-control">
                  <button
                    className={`segmented-button ${crossChatMemoryEnabled ? "active" : ""}`}
                    onClick={() => setCrossChatMemoryEnabled(true)}
                    type="button"
                  >
                    On
                  </button>
                  <button
                    className={`segmented-button ${!crossChatMemoryEnabled ? "active" : ""}`}
                    onClick={() => setCrossChatMemoryEnabled(false)}
                    type="button"
                  >
                    Off
                  </button>
                </div>
              </div>

              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Auto compact long chats</strong>
                  <p>Atlas trims old thread context automatically using the effective context window detected from Ollama.</p>
                </div>
                <div className="segmented-control">
                  <button
                    className={`segmented-button ${autoCompactLongChats ? "active" : ""}`}
                    onClick={() => setAutoCompactLongChats(true)}
                    type="button"
                  >
                    On
                  </button>
                  <button
                    className={`segmented-button ${!autoCompactLongChats ? "active" : ""}`}
                    onClick={() => setAutoCompactLongChats(false)}
                    type="button"
                  >
                    Off
                  </button>
                </div>
              </div>

              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Add user</strong>
                  <p>Create a new persistent memory namespace and switch to it immediately.</p>
                </div>
                <div className="settings-inline-form">
                  <input
                    className="text-input settings-user-input"
                    onChange={(event) => setNewUserId(event.currentTarget.value)}
                    placeholder="new_user"
                    value={newUserId}
                  />
                  <button
                    className="primary-button compact-button"
                    disabled={!newUserId.trim() || createUserMutation.isPending}
                    onClick={() => createUserMutation.mutate()}
                    type="button"
                  >
                    <Plus size={15} />
                    {createUserMutation.isPending ? "Adding..." : "Add"}
                  </button>
                </div>
              </div>

              <div className="settings-row danger">
                <div className="settings-row-copy">
                  <strong>Delete current user</strong>
                  <p>Delete this user and remove their chats, saved runs, durable world state, and manual memories.</p>
                </div>
                <button
                  className="danger-button compact-button"
                  disabled={!currentUserId || deleteUserMutation.isPending}
                  onClick={() => {
                    setPendingDeleteUserId(currentUserId);
                    setDialog("user");
                  }}
                  type="button"
                >
                  {deleteUserMutation.isPending ? "Deleting..." : "Delete user"}
                </button>
              </div>

            </div>
          ) : null}

          {section === "models" ? (
            <div className="settings-rows">
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Default chat model</strong>
                  <p>New chats start with this model unless you choose a different one before the first message.</p>
                </div>
                <span>{models?.default_model ?? status?.default_chat_model ?? status?.chat_model ?? "..."}</span>
              </div>
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Embed model</strong>
                  <p>Used for local semantic memory retrieval.</p>
                </div>
                <span>{status?.embed_model ?? "..."}</span>
              </div>
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Default temperature</strong>
                  <p>New chats start with this sampling preset unless you choose another one before the first message.</p>
                </div>
                <span>{formatTemperature(models?.default_temperature ?? status?.default_chat_temperature)}</span>
              </div>
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Active profile</strong>
                  <p>The currently loaded runtime profile.</p>
                </div>
                <span>{status?.active_profile ?? "default"}</span>
              </div>
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Local Ollama models</strong>
                  <p>These are the locally available chat models Atlas can bind to a new thread.</p>
                </div>
                <span>{models?.models?.join(", ") || "..."}</span>
              </div>
            </div>
          ) : null}

          {section === "data" ? (
            <div className="settings-rows">
              <div className="settings-row danger">
                <div className="settings-row-copy">
                  <strong>Wipe all local data</strong>
                  <p>Clears every chat, saved run, persistent memory, and local cache for Atlas in one step.</p>
                </div>
                <button className="danger-button compact-button" onClick={() => setDialog("all")} type="button">
                  Wipe all
                </button>
              </div>
              <div className="settings-row settings-row-block">
                <div className="settings-row-copy">
                  <strong>Remember</strong>
                  <p>Store a manual note in persistent memory for the current user.</p>
                </div>
                <div className="settings-column">
                  <div className="settings-inline-form">
                    <input
                      className="text-input settings-memory-input"
                      onChange={(event) => setMemoryDraft(event.currentTarget.value)}
                      placeholder="Remember this across chats"
                      value={memoryDraft}
                    />
                    <button
                      className="primary-button compact-button"
                      disabled={!currentUserId || !memoryDraft.trim() || createMemoryMutation.isPending}
                      onClick={() => createMemoryMutation.mutate()}
                      type="button"
                    >
                      {createMemoryMutation.isPending ? "Saving..." : "Remember"}
                    </button>
                  </div>
                  <div className="settings-memory-list">
                    {manualMemories.length === 0 ? (
                      <div className="empty-inline">No manual memories saved for this user yet.</div>
                    ) : (
                      manualMemories.map((memory) => (
                        <div className="stack-card settings-memory-card" key={memory.memory_id}>
                          <p>{memory.memory}</p>
                          <div className="inline-actions">
                            <span className="muted-text">{memory.memory_id}</span>
                            <button
                              className="danger-button compact-button"
                              disabled={!currentUserId || deleteMemoryMutation.isPending}
                              onClick={() => deleteMemoryMutation.mutate(memory.memory_id)}
                              type="button"
                            >
                              Forget
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {section === "about" ? (
            <div className="settings-rows">
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Runtime</strong>
                  <p>The managed local service currently connected to the desktop shell.</p>
                </div>
                <span>{status?.backend ?? "Atlas local runtime"}</span>
              </div>
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Active profile</strong>
                  <p>The runtime profile currently loaded for local inference.</p>
                </div>
                <span>{status?.active_profile ?? "default"}</span>
              </div>
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Version</strong>
                  <p>Desktop shell and local runtime identity.</p>
                </div>
                <span>Atlas Desktop v0.1.0</span>
              </div>
            </div>
          ) : null}
        </section>
      </div>

      <ResetDialog
        confirmLabel="Wipe all local data"
        description="This clears every local chat, saved run, and persistent memory while keeping your desktop theme preference."
        onConfirm={async () => {
          await allReset.mutateAsync();
        }}
        onOpenChange={(open) => setDialog(open ? "all" : null)}
        open={dialog === "all"}
        title="Reset all local data"
      />
      <ResetDialog
        confirmLabel={`Delete ${pendingDeleteUserId || "user"}`}
        description={
          pendingDeleteUserId
            ? `This permanently deletes ${pendingDeleteUserId} and clears their chats, saved runs, and persistent memory.`
            : "This permanently deletes the selected user and clears their chats, saved runs, and persistent memory."
        }
        onConfirm={async () => {
          if (!pendingDeleteUserId) {
            return;
          }
          await deleteUserMutation.mutateAsync(pendingDeleteUserId);
        }}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDeleteUserId(null);
          }
          setDialog(open ? "user" : null);
        }}
        open={dialog === "user"}
        title="Delete user"
      />
    </div>
  );
}

function formatTemperature(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "...";
  }
  if (Math.abs(value - 0.2) < 1e-9) {
    return "Precise (0.2)";
  }
  if (Math.abs(value - 0.6) < 1e-9) {
    return "Balanced (0.6)";
  }
  if (Math.abs(value - 0.9) < 1e-9) {
    return "Creative (0.9)";
  }
  return value.toFixed(1);
}
