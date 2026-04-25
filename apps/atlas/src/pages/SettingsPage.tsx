import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getVersion } from "@tauri-apps/api/app";
import { useEffect, useMemo, useState } from "react";
import {
  Database,
  Info,
  Lock,
  Monitor,
  Plug,
  RefreshCw,
  SlidersHorizontal,
  Trash2,
  Unlock,
  UserPlus,
  Users,
  X,
} from "lucide-react";

import { ResetDialog } from "../components/ResetDialog";
import { Chip, ChipList } from "../components/ui/Chip";
import { EmptyState } from "../components/ui/EmptyState";
import { SettingsRow } from "../components/ui/SettingsRow";
import { StatusPill } from "../components/ui/StatusPill";
import {
  createMemory,
  createUser,
  deleteMemory,
  deleteUser,
  getMemories,
  getModels,
  getStatus,
  getUsers,
  lockUser,
  resetAll,
  unlockUser,
} from "../lib/api";
import { useAtlasStore } from "../store/useAtlasStore";

type SettingsSection = "general" | "profiles" | "models" | "connections" | "data" | "about";
type UserProtectionMode = "passwordless" | "password";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const theme = useAtlasStore((state) => state.theme);
  const setTheme = useAtlasStore((state) => state.setTheme);
  const currentUserId = useAtlasStore((state) => state.currentUserId);
  const crossChatMemoryEnabled = useAtlasStore((state) => state.crossChatMemoryEnabled);
  const autoCompactLongChats = useAtlasStore((state) => state.autoCompactLongChats);
  const crtScanlines = useAtlasStore((state) => state.crtScanlines);
  const setCrtScanlines = useAtlasStore((state) => state.setCrtScanlines);
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
  const [newUserProtection, setNewUserProtection] = useState<UserProtectionMode>("passwordless");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [memoryDraft, setMemoryDraft] = useState("");
  const [pendingDeleteUserId, setPendingDeleteUserId] = useState<string | null>(null);
  const [unlockTargetUserId, setUnlockTargetUserId] = useState<string | null>(null);
  const [unlockPassword, setUnlockPassword] = useState("");
  const [appVersion, setAppVersion] = useState("1.0.8");
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
  const currentUser = useMemo(
    () => visibleUsers.find((user) => user.user_id === currentUserId) ?? null,
    [currentUserId, visibleUsers],
  );
  const manualMemories = useMemo(
    () =>
      memories.filter(
        (memory) =>
          memory.metadata?.source === "manual" ||
          memory.metadata?.kind === "memory_note",
      ),
    [memories],
  );
  const security = status?.security;
  const allDataEncrypted = Boolean(
    security?.run_artifacts_encrypted_at_rest &&
      security?.run_index_encrypted_at_rest &&
      security?.sqlite_encrypted_at_rest &&
      security?.vector_store_encrypted_at_rest,
  );

  useEffect(() => {
    if (usersFetched && currentUserId && (!currentUser || currentUser.locked)) {
      setCurrentUserId("");
      setCurrentThreadId("main");
      setCurrentThreadTitle("main");
      setDraftThreadModel("");
      setDraftThreadTemperature(null);
    }
  }, [
    currentUserId,
    setCurrentThreadId,
    setCurrentThreadTitle,
    setCurrentUserId,
    setDraftThreadModel,
    setDraftThreadTemperature,
    currentUser,
    usersFetched,
  ]);

  useEffect(() => {
    let cancelled = false;
    void getVersion()
      .then((version) => {
        if (!cancelled && version.trim()) {
          setAppVersion(version.trim());
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const allReset = useMutation({
    mutationFn: resetAll,
    onSuccess: async () => {
      setCurrentThreadId("main");
      setCurrentThreadTitle("main");
      await queryClient.invalidateQueries();
    },
  });

  const switchToUser = async (userId: string) => {
    setCurrentUserId(userId);
    setCurrentThreadId("main");
    setCurrentThreadTitle("main");
    setDraftThreadModel("");
    setDraftThreadTemperature(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["users"] }),
      queryClient.invalidateQueries({ queryKey: ["threads"] }),
      queryClient.invalidateQueries({ queryKey: ["thread-history"] }),
      queryClient.invalidateQueries({ queryKey: ["memories"] }),
    ]);
  };

  const createUserMutation = useMutation({
    mutationFn: async () =>
      createUser(
        newUserId.trim(),
        newUserProtection === "password" ? newUserPassword.trim() : undefined,
      ),
    onSuccess: async (user) => {
      setNewUserId("");
      setNewUserPassword("");
      setNewUserProtection("passwordless");
      setUnlockPassword("");
      setUnlockTargetUserId(null);
      await switchToUser(user.user_id);
    },
  });
  const unlockUserMutation = useMutation({
    mutationFn: async (payload: { userId: string; password?: string }) =>
      unlockUser(payload.userId, payload.password),
    onSuccess: async (user) => {
      setUnlockPassword("");
      setUnlockTargetUserId(null);
      await switchToUser(user.user_id);
    },
  });
  const lockUserMutation = useMutation({
    mutationFn: async (userId: string) => lockUser(userId),
    onSuccess: async (user) => {
      if (currentUserId === user.user_id) {
        setCurrentUserId("");
        setCurrentThreadId("main");
        setCurrentThreadTitle("main");
        setDraftThreadModel("");
        setDraftThreadTemperature(null);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["users"] }),
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["thread-history"] }),
        queryClient.invalidateQueries({ queryKey: ["memories"] }),
      ]);
    },
  });
  const createMemoryMutation = useMutation({
    mutationFn: async () => {
      if (!currentUserId) {
        throw new Error("Select a profile before saving memory.");
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
        throw new Error("Select a profile before deleting memory.");
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
        setDraftThreadModel("");
        setDraftThreadTemperature(null);
      }

      setPendingDeleteUserId(null);
      setUnlockPassword("");
      setUnlockTargetUserId(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["users"] }),
        queryClient.invalidateQueries({ queryKey: ["threads"] }),
        queryClient.invalidateQueries({ queryKey: ["thread-history"] }),
        queryClient.invalidateQueries({ queryKey: ["memories"] }),
      ]);
    },
  });

  const refreshModels = async () => {
    await queryClient.invalidateQueries({ queryKey: ["models"] });
    await queryClient.invalidateQueries({ queryKey: ["status"] });
  };

  const sections = [
    { id: "general", label: "General", icon: SlidersHorizontal },
    { id: "profiles", label: "Profiles", icon: Users },
    { id: "models", label: "Models", icon: Monitor },
    { id: "connections", label: "Connections", icon: Plug },
    { id: "data", label: "Data", icon: Database },
    { id: "about", label: "About", icon: Info },
  ] as const;
  const activeSectionLabel = sections.find((item) => item.id === section)?.label ?? "General";
  const activeSectionDescription =
    section === "general"
      ? "Interface preferences and conversation behavior."
      : section === "profiles"
        ? "Local profiles, password protection, and account lifecycle."
      : section === "models"
        ? "Installed local model inventory and sampling behavior."
        : section === "connections"
          ? "Local services Atlas Chat depends on."
          : section === "data"
            ? "Storage protection, reset controls, and manual memory."
            : "Product identity and release details.";

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
              <SettingsRow
                label="Theme"
                description="Choose the desktop palette. Every theme uses the same minimal layout and control treatment."
              >
                <div className="segmented-control">
                  {[
                    { id: "light", label: "Light" },
                    { id: "dark", label: "Dark" },
                    { id: "crt-green", label: "CRT Green" },
                    { id: "crt-amber", label: "CRT Amber" },
                    { id: "synthwave", label: "Synthwave" },
                    { id: "nasa", label: "NASA" },
                  ].map((option) => (
                    <button
                      className={`segmented-button ${theme === option.id ? "active" : ""}`}
                      key={option.id}
                      onClick={() => setTheme(option.id as typeof theme)}
                      type="button"
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </SettingsRow>

              {theme === "crt-green" || theme === "crt-amber" ? (
                <SettingsRow
                  label="Scanlines"
                  description="Add a light terminal texture while keeping the minimal interface intact."
                >
                  <div className="segmented-control">
                    <button
                      className={`segmented-button ${crtScanlines ? "active" : ""}`}
                      onClick={() => setCrtScanlines(true)}
                      type="button"
                    >
                      On
                    </button>
                    <button
                      className={`segmented-button ${!crtScanlines ? "active" : ""}`}
                      onClick={() => setCrtScanlines(false)}
                      type="button"
                    >
                      Off
                    </button>
                  </div>
                </SettingsRow>
              ) : null}

              <SettingsRow
                label="Cross-chat memory"
                description="Allow saved memories to inform replies for the current profile."
              >
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
              </SettingsRow>

              <SettingsRow
                label="Auto compact long chats"
                description="Atlas Chat trims old thread context automatically using the effective context window detected from Ollama."
              >
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
              </SettingsRow>
            </div>
          ) : null}

          {section === "profiles" ? (
            <div className="settings-rows">
              {visibleUsers.length === 0 ? (
                <EmptyState
                  icon={<Users size={18} />}
                  title="No profiles yet"
                  description="Create your first profile to start chatting. Profiles separate chats and memories on this machine."
                />
              ) : (
                <div className="settings-column">
                  {visibleUsers.map((user) => {
                    const isCurrent = currentUserId === user.user_id;
                    const isUnlocking = unlockTargetUserId === user.user_id;
                    const isProtected = user.protection === "password";
                    const isLocked = Boolean(user.locked);
                    return (
                      <div className="stack-card settings-user-card" key={user.user_id}>
                        <div className="settings-user-card-header">
                          <div className="settings-user-card-copy">
                            <strong>{user.user_id}</strong>
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                              {isProtected ? (isLocked ? <Lock size={12} /> : <Unlock size={12} />) : null}
                              {describeUserProtection(user)}
                            </span>
                          </div>
                          <div className="inline-actions">
                            {isCurrent ? <StatusPill intent="info" dot={false}>Current</StatusPill> : null}
                            {isProtected && !isLocked ? (
                              <button
                                className="ghost-button compact-button"
                                disabled={lockUserMutation.isPending}
                                onClick={() => lockUserMutation.mutate(user.user_id)}
                                type="button"
                              >
                                <Lock size={14} />
                                Lock
                              </button>
                            ) : null}
                            {!isLocked ? (
                              <button
                                className="primary-button compact-button"
                                disabled={isCurrent}
                                onClick={() => {
                                  void switchToUser(user.user_id);
                                }}
                                type="button"
                              >
                                {isCurrent ? "In use" : "Use profile"}
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
                                <Unlock size={14} />
                                Unlock
                              </button>
                            )}
                            {!isCurrent ? (
                              <button
                                aria-label={`Delete profile ${user.user_id}`}
                                className="danger-button compact-button"
                                onClick={() => {
                                  setPendingDeleteUserId(user.user_id);
                                  setDialog("user");
                                }}
                                type="button"
                              >
                                <Trash2 size={14} />
                              </button>
                            ) : null}
                          </div>
                        </div>
                        {isProtected && isLocked && isUnlocking ? (
                          <div className="settings-column">
                            <div className="settings-inline-form">
                              <input
                                aria-label="Profile password"
                                autoFocus
                                className="text-input settings-user-input"
                                onChange={(event) => setUnlockPassword(event.currentTarget.value)}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter" && unlockPassword.trim()) {
                                    unlockUserMutation.mutate({ userId: user.user_id, password: unlockPassword.trim() });
                                  }
                                }}
                                placeholder="Enter profile password"
                                type="password"
                                value={unlockPassword}
                              />
                              <button
                                className="primary-button compact-button"
                                disabled={!unlockPassword.trim() || unlockUserMutation.isPending}
                                onClick={() =>
                                  unlockUserMutation.mutate({
                                    userId: user.user_id,
                                    password: unlockPassword.trim(),
                                  })
                                }
                                type="button"
                              >
                                {unlockUserMutation.isPending ? "Unlocking..." : "Unlock and use"}
                              </button>
                              <button
                                className="ghost-button compact-button"
                                onClick={() => {
                                  setUnlockTargetUserId(null);
                                  setUnlockPassword("");
                                }}
                                type="button"
                              >
                                Cancel
                              </button>
                            </div>
                            {unlockUserMutation.isError ? (
                              <div className="error-inline">{getMutationErrorMessage(unlockUserMutation.error)}</div>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}

              <SettingsRow
                label="Create profile"
                description="Choose a profile name and decide whether Atlas Chat should require a password to unlock it."
                block
              >
                <div className="settings-column">
                  <div className="settings-inline-form">
                    <input
                      aria-label="New profile name"
                      className="text-input settings-user-input"
                      onChange={(event) => setNewUserId(event.currentTarget.value)}
                      placeholder="my_profile"
                      value={newUserId}
                    />
                    <div className="segmented-control">
                      <button
                        className={`segmented-button ${newUserProtection === "passwordless" ? "active" : ""}`}
                        onClick={() => setNewUserProtection("passwordless")}
                        type="button"
                      >
                        Passwordless
                      </button>
                      <button
                        className={`segmented-button ${newUserProtection === "password" ? "active" : ""}`}
                        onClick={() => setNewUserProtection("password")}
                        type="button"
                      >
                        Password
                      </button>
                    </div>
                  </div>
                  {newUserProtection === "password" ? (
                    <div className="settings-inline-form">
                      <input
                        aria-label="Profile password"
                        className="text-input settings-user-input"
                        onChange={(event) => setNewUserPassword(event.currentTarget.value)}
                        placeholder="Profile password"
                        type="password"
                        value={newUserPassword}
                      />
                    </div>
                  ) : null}
                  <div className="settings-inline-form">
                    <button
                      className="primary-button compact-button"
                      disabled={
                        !newUserId.trim() ||
                        createUserMutation.isPending ||
                        (newUserProtection === "password" && !newUserPassword.trim())
                      }
                      onClick={() => createUserMutation.mutate()}
                      type="button"
                    >
                      <UserPlus size={15} />
                      {createUserMutation.isPending ? "Creating..." : "Create profile"}
                    </button>
                  </div>
                  {createUserMutation.isError ? (
                    <div className="error-inline">{getMutationErrorMessage(createUserMutation.error)}</div>
                  ) : null}
                </div>
              </SettingsRow>
            </div>
          ) : null}

          {section === "models" ? (
            <div className="settings-rows">
              <SettingsRow
                label="Initial temperature"
                description="Initial sampling value for new threads. Override per thread in Workspace."
              >
                <Chip intent="muted">{formatTemperature(models?.default_temperature ?? status?.default_chat_temperature)}</Chip>
              </SettingsRow>

              <SettingsRow
                label="Embed model"
                description="Used for local semantic memory retrieval."
              >
                <Chip intent={status?.embed_model ? "accent" : "muted"}>{status?.embed_model || "Not configured"}</Chip>
              </SettingsRow>

              <SettingsRow
                label="Installed local models"
                description="Local chat models Atlas Chat can bind to a thread. Pull more from Discovery."
                block
              >
                <div className="settings-column">
                  <div className="inline-actions" style={{ justifyContent: "space-between" }}>
                    <span style={{ color: "var(--muted)", fontSize: "var(--text-sm)" }}>
                      {models?.ollama_online
                        ? `${models.models.length} model${models.models.length === 1 ? "" : "s"} installed`
                        : "Waiting for Ollama"}
                    </span>
                    <button
                      className="ghost-button compact-button"
                      onClick={refreshModels}
                      type="button"
                    >
                      <RefreshCw size={14} />
                      Refresh
                    </button>
                  </div>
                  {models?.ollama_online && models.has_local_models ? (
                    <ChipList>
                      {models.models.map((m) => (
                        <Chip key={m}>{m}</Chip>
                      ))}
                    </ChipList>
                  ) : models?.ollama_online ? (
                    <EmptyState
                      icon={<Monitor size={18} />}
                      title="No models installed"
                      description="Open Discovery to find a model that fits your machine."
                    />
                  ) : (
                    <EmptyState
                      icon={<Plug size={18} />}
                      title="Ollama not reachable"
                      description="Atlas Chat needs Ollama running locally. Check Connections."
                    />
                  )}
                </div>
              </SettingsRow>
            </div>
          ) : null}

          {section === "connections" ? (
            <div className="settings-rows">
              <SettingsRow
                label="Ollama"
                description="Local model runtime. Atlas Chat checks this before opening a new chat."
              >
                <div className="inline-actions">
                  <span style={{ color: "var(--muted)", fontSize: "var(--text-sm)" }}>
                    {status?.ollama_url || "127.0.0.1:11434"}
                  </span>
                  <StatusPill intent={models?.ollama_online ? "ok" : "error"}>
                    {models?.ollama_online ? "Connected" : "Not running"}
                  </StatusPill>
                </div>
              </SettingsRow>

              <SettingsRow
                label="Runtime mode"
                description="Indicates which capabilities the backend has loaded."
              >
                <Chip intent="muted">{status?.runtime_mode || "unknown"}</Chip>
              </SettingsRow>

              <SettingsRow
                label="Backend"
                description="Local FastAPI process managed by the desktop shell."
              >
                <StatusPill intent={status ? "ok" : "warn"}>{status ? "Online" : "Booting"}</StatusPill>
              </SettingsRow>

              <SettingsRow
                label="Code runner"
                description="Server-side code execution requires Docker. HTML previews work without it."
              >
                <StatusPill intent="info">Optional</StatusPill>
              </SettingsRow>
            </div>
          ) : null}

          {section === "data" ? (
            <div className="settings-rows">
              <SettingsRow
                label="Local protection"
                description={
                  allDataEncrypted
                    ? "Run files, SQLite state, and local vector storage are encrypted at rest. Packaged backend logs stay off unless you enable them explicitly."
                    : "Atlas Chat is storing local data without at-rest protection on this runtime."
                }
              >
                <StatusPill intent={allDataEncrypted ? "ok" : "warn"}>
                  {allDataEncrypted ? "Encrypted" : "Unprotected"}
                </StatusPill>
              </SettingsRow>

              <SettingsRow
                label="Wipe all local data"
                description="Clears every chat, saved run, persistent memory, and local cache for Atlas Chat in one step."
                danger
              >
                <button className="danger-button compact-button" onClick={() => setDialog("all")} type="button">
                  Wipe all
                </button>
              </SettingsRow>

              <SettingsRow
                label="Remember"
                description="Create and remove manual memories for the current profile."
                block
              >
                <div className="settings-column">
                  <div className="settings-inline-form">
                    <input
                      aria-label="Memory text"
                      className="text-input settings-memory-input"
                      onChange={(event) => setMemoryDraft(event.currentTarget.value)}
                      placeholder={currentUserId ? "Remember this across chats" : "Select a profile first"}
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
                    {!currentUserId ? (
                      <EmptyState
                        title="No profile selected"
                        description="Switch to a profile to view and add memories."
                      />
                    ) : manualMemories.length === 0 ? (
                      <EmptyState
                        title="No memories yet"
                        description="Add a fact above and Atlas Chat will recall it across chats for this profile."
                      />
                    ) : (
                      manualMemories.map((memory) => (
                        <div className="stack-card settings-memory-card" key={memory.memory_id}>
                          <p>{memory.memory}</p>
                          <div className="inline-actions">
                            <button
                              aria-label="Delete memory"
                              className="danger-button compact-button"
                              disabled={!currentUserId || deleteMemoryMutation.isPending}
                              onClick={() => deleteMemoryMutation.mutate(memory.memory_id)}
                              type="button"
                            >
                              <X size={14} />
                              Forget
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </SettingsRow>
            </div>
          ) : null}

          {section === "about" ? (
            <div className="settings-about">
              <section className="settings-about-hero" aria-labelledby="about-product-title">
                <div className="settings-about-hero-copy">
                  <p className="eyebrow">Atlas Chat Desktop</p>
                  <h3 id="about-product-title">{status?.product_name || "Atlas Chat"}</h3>
                  <p>
                    A local-first desktop app for private chats with local Ollama models. Includes profile-scoped memory,
                    hardware-aware model discovery, and a sandboxed code runner.
                  </p>
                </div>
                <div className="settings-about-release">
                  <span>Current version</span>
                  <strong>{`v${appVersion}`}</strong>
                </div>
              </section>

              <div className="settings-rows settings-about-rows">
                <SettingsRow label="Privacy model" description="Chats, saved runs, and memory live on this device.">
                  <Chip intent="muted">Stored locally</Chip>
                </SettingsRow>
                <SettingsRow label="Updates" description="New versions ship through the Microsoft Store.">
                  <Chip intent="muted">Microsoft Store</Chip>
                </SettingsRow>
                <SettingsRow label="License" description="Open source under MIT. Brand and trademark are not licensed.">
                  <Chip intent="muted">MIT</Chip>
                </SettingsRow>
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
        confirmLabel={`Delete ${pendingDeleteUserId || "profile"}`}
        description={
          pendingDeleteUserId
            ? `This permanently deletes ${pendingDeleteUserId} and clears their chats, saved runs, and persistent memory.`
            : "This permanently deletes the selected profile and clears their chats, saved runs, and persistent memory."
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
        title="Delete profile"
      />

    </div>
  );
}

function formatTemperature(value?: number | null) {
  if (value === null || value === undefined) {
    return "Model setting";
  }
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "Model setting";
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
  return value.toFixed(2);
}

function describeUserProtection(user: { protection?: string; locked?: boolean }) {
  if (user.protection === "password") {
    return user.locked ? "Password protected — Locked" : "Password protected";
  }
  return "Passwordless";
}

function getMutationErrorMessage(error: unknown) {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "The request did not complete.";
}
