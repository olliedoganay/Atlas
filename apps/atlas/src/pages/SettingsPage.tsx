import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getVersion } from "@tauri-apps/api/app";
import { useEffect, useMemo, useState } from "react";
import {
  Database,
  Info,
  Lock,
  Monitor,
  Plus,
  SlidersHorizontal,
  Unlock,
  Users,
} from "lucide-react";

import { ResetDialog } from "../components/ResetDialog";
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

type SettingsSection = "general" | "users" | "models" | "data" | "about";
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
  const [appVersion, setAppVersion] = useState("1.0.7");
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
  const preselectedModel = models?.configured_chat_model ?? status?.configured_chat_model ?? status?.chat_model ?? "";
  const security = status?.security;

  useEffect(() => {
    if (usersFetched && currentUserId && (!currentUser || currentUser.locked)) {
      setCurrentUserId("");
      setCurrentThreadId("main");
      setCurrentThreadTitle("main");
      setDraftThreadModel(preselectedModel);
      setDraftThreadTemperature(null);
    }
  }, [
    currentUserId,
    preselectedModel,
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
      .catch(() => {
        // Keep the manifest fallback if the runtime API is unavailable.
      });

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
    setDraftThreadModel(preselectedModel);
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
        setDraftThreadModel(preselectedModel);
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
        setDraftThreadModel(preselectedModel);
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

  const sections = [
    { id: "general", label: "General", icon: SlidersHorizontal },
    { id: "users", label: "Users", icon: Users },
    { id: "models", label: "Models", icon: Monitor },
    { id: "data", label: "Data", icon: Database },
    { id: "about", label: "About", icon: Info },
  ] as const;
  const activeSectionLabel = sections.find((item) => item.id === section)?.label ?? "General";
  const activeSectionDescription =
    section === "general"
      ? "Interface preferences and conversation behavior."
      : section === "users"
        ? "Local profiles, access, and account lifecycle."
      : section === "models"
        ? "Ollama connection and installed model inventory."
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
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Theme</strong>
                  <p>Choose the desktop palette. Every theme uses the same minimal layout and control treatment.</p>
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
                  <button
                    className={`segmented-button ${theme === "crt-green" ? "active" : ""}`}
                    onClick={() => setTheme("crt-green")}
                    type="button"
                  >
                    CRT Green
                  </button>
                  <button
                    className={`segmented-button ${theme === "crt-amber" ? "active" : ""}`}
                    onClick={() => setTheme("crt-amber")}
                    type="button"
                  >
                    CRT Amber
                  </button>
                  <button
                    className={`segmented-button ${theme === "synthwave" ? "active" : ""}`}
                    onClick={() => setTheme("synthwave")}
                    type="button"
                  >
                    Synthwave
                  </button>
                  <button
                    className={`segmented-button ${theme === "nasa" ? "active" : ""}`}
                    onClick={() => setTheme("nasa")}
                    type="button"
                  >
                    NASA
                  </button>
                </div>
              </div>

              {theme === "crt-green" || theme === "crt-amber" ? (
                <div className="settings-row">
                  <div className="settings-row-copy">
                    <strong>Scanlines</strong>
                    <p>Add a light terminal texture while keeping the minimal interface intact.</p>
                  </div>
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
                </div>
              ) : null}

              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Cross-chat memory</strong>
                  <p>Allow saved memories to inform replies for the current profile.</p>
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
            </div>
          ) : null}

          {section === "users" ? (
            <div className="settings-rows">
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Current profile</strong>
                  <p>Select which local profile Atlas should use for chats, memory, and search.</p>
                </div>
                <span>
                  {currentUser
                    ? `${currentUser.user_id} | ${describeUserProtection(currentUser)}`
                    : "No profile selected"}
                </span>
              </div>

              <div className="settings-row settings-row-block">
                <div className="settings-row-copy">
                  <strong>Profiles</strong>
                  <p>Password-protected profiles stay locked until you unlock them in this session.</p>
                </div>
                <div className="settings-column">
                  {visibleUsers.length === 0 ? (
                    <div className="empty-inline">No profiles created yet.</div>
                  ) : (
                    visibleUsers.map((user) => {
                      const isCurrent = currentUserId === user.user_id;
                      const isUnlocking = unlockTargetUserId === user.user_id;
                      const isProtected = user.protection === "password";
                      const isLocked = Boolean(user.locked);
                      return (
                        <div className="stack-card settings-user-card" key={user.user_id}>
                          <div className="settings-user-card-header">
                            <div className="settings-user-card-copy">
                              <strong>{user.user_id}</strong>
                              <span>{describeUserProtection(user)}</span>
                            </div>
                            <div className="inline-actions">
                              {isCurrent ? <span className="muted-text">Current</span> : null}
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
                                  <Unlock size={14} />
                                  Unlock
                                </button>
                              )}
                            </div>
                          </div>
                          {isProtected && isLocked && isUnlocking ? (
                            <div className="settings-column">
                              <div className="settings-inline-form">
                                <input
                                  className="text-input settings-user-input"
                                  onChange={(event) => setUnlockPassword(event.currentTarget.value)}
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
                    })
                  )}
                </div>
              </div>

              <div className="settings-row settings-row-block">
                <div className="settings-row-copy">
                  <strong>Create profile</strong>
                  <p>Choose a profile name and decide whether Atlas should require a password to unlock it.</p>
                </div>
                <div className="settings-column">
                  <div className="settings-inline-form">
                    <input
                      className="text-input settings-user-input"
                      onChange={(event) => setNewUserId(event.currentTarget.value)}
                      placeholder="new_profile"
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
                      <Plus size={15} />
                      {createUserMutation.isPending ? "Creating..." : "Create profile"}
                    </button>
                  </div>
                  {createUserMutation.isError ? (
                    <div className="error-inline">{getMutationErrorMessage(createUserMutation.error)}</div>
                  ) : null}
                </div>
              </div>

              <div className="settings-row danger">
                <div className="settings-row-copy">
                  <strong>Delete current profile</strong>
                  <p>Delete this profile and remove its chats, saved runs, durable world state, and manual memories.</p>
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
                  <strong>Ollama connection</strong>
                  <p>Atlas checks the local Ollama runtime before it opens a new chat.</p>
                </div>
                <span>{models?.ollama_online ? "Connected" : "Unavailable"}</span>
              </div>
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Chat model selection</strong>
                  <p>New threads use the model selected in Workspace. Atlas does not preselect a bundled model.</p>
                </div>
                <span>{preselectedModel || "Per thread"}</span>
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
                  <strong>Temperature behavior</strong>
                  <p>New threads use model-default sampling unless you choose another value before the first message.</p>
                </div>
                <span>{formatTemperature(models?.default_temperature ?? status?.default_chat_temperature)}</span>
              </div>
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Local chat models</strong>
                  <p>These are the installed local chat models Atlas can bind to a new thread.</p>
                </div>
                <span>
                  {models?.ollama_online
                    ? models?.has_local_models
                      ? models.models.join(", ")
                      : "No local models found"
                    : "Waiting for Ollama"}
                </span>
              </div>
            </div>
          ) : null}

          {section === "data" ? (
            <div className="settings-rows">
              <div className="settings-row">
                <div className="settings-row-copy">
                  <strong>Local protection</strong>
                  <p>
                    {security?.run_artifacts_encrypted_at_rest &&
                    security?.run_index_encrypted_at_rest &&
                    security?.sqlite_encrypted_at_rest &&
                    security?.vector_store_encrypted_at_rest
                      ? "Run files, SQLite state, and local vector storage are encrypted at rest on this Windows device. Packaged backend logs stay off unless you enable them explicitly."
                      : "Atlas is storing local data without at-rest protection on this runtime."}
                  </p>
                </div>
                <span>
                  {security?.run_artifacts_encrypted_at_rest &&
                  security?.run_index_encrypted_at_rest &&
                  security?.sqlite_encrypted_at_rest &&
                  security?.vector_store_encrypted_at_rest
                    ? "DPAPI + SQLCipher"
                    : "Unprotected"}
                </span>
              </div>
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
                  <p>Create and remove manual memories for the current profile.</p>
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
            <div className="settings-about">
              <section className="settings-about-hero" aria-labelledby="about-product-title">
                <div className="settings-about-hero-copy">
                  <p className="eyebrow">Atlas Desktop</p>
                  <h3 id="about-product-title">{status?.product_name || "Atlas"}</h3>
                  <p>
                    A local-first Windows workstation for private chats, model discovery, memory, and controlled code execution.
                  </p>
                </div>
                <div className="settings-about-release">
                  <span>Current version</span>
                  <strong>{`v${appVersion}`}</strong>
                </div>
              </section>

              <div className="settings-rows settings-about-rows">
                <div className="settings-row">
                  <div className="settings-row-copy">
                    <strong>Product</strong>
                    <p>Desktop application for local model workflows.</p>
                  </div>
                  <span>Local-first desktop app</span>
                </div>
                <div className="settings-row">
                  <div className="settings-row-copy">
                    <strong>Privacy model</strong>
                    <p>Chats, saved runs, and memory are managed on this device.</p>
                  </div>
                  <span>Stored locally</span>
                </div>
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

function formatTemperature(value?: number | null) {
  if (value === null) {
    return "Model default";
  }
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
