import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { ImageAttachment, ThemeMode } from "../lib/api";

type CompactionNotice = {
  runId: string;
  userId: string;
  threadId: string;
  compactedMessageCount: number;
  newlyCompactedMessageCount: number;
  threadSummary: string;
  detectedContextWindow: number;
  historyRepresentationTokensBeforeCompaction?: number;
  historyRepresentationTokensAfterCompaction?: number;
};

type AtlasState = {
  theme: ThemeMode;
  currentUserId: string;
  currentThreadId: string;
  currentThreadTitle: string;
  draftThreadModel: string;
  draftThreadTemperature: number | null;
  crossChatMemoryEnabled: boolean;
  autoCompactLongChats: boolean;
  navCollapsed: boolean;
  settingsSidebarCollapsed: boolean;
  currentRunId: string | null;
  activeRunUserId: string | null;
  activeRunThreadId: string | null;
  currentStage: string;
  pendingPrompt: string;
  pendingAttachments: ImageAttachment[];
  liveAnswer: string;
  liveError: string;
  compactionNotice: CompactionNotice | null;
  isStreaming: boolean;
  setTheme: (theme: ThemeMode) => void;
  setCurrentUserId: (value: string) => void;
  setCurrentThreadId: (value: string) => void;
  setCurrentThreadTitle: (value: string) => void;
  setDraftThreadModel: (value: string) => void;
  setDraftThreadTemperature: (value: number | null) => void;
  setCrossChatMemoryEnabled: (value: boolean) => void;
  setAutoCompactLongChats: (value: boolean) => void;
  toggleNavCollapsed: () => void;
  toggleSettingsSidebarCollapsed: () => void;
  beginRun: (
    runId: string,
    prompt: string,
    userId: string,
    threadId: string,
    attachments?: ImageAttachment[],
  ) => void;
  appendToken: (text: string) => void;
  setStage: (stage: string) => void;
  completeRun: () => void;
  failRun: (message: string) => void;
  showCompactionNotice: (notice: CompactionNotice) => void;
  clearCompactionNotice: () => void;
  clearLiveRun: () => void;
};

const defaultTheme = "dark";

export const useAtlasStore = create<AtlasState>()(
  persist(
    (set) => ({
      theme: defaultTheme,
      currentUserId: "",
      currentThreadId: "main",
      currentThreadTitle: "main",
      draftThreadModel: "",
      draftThreadTemperature: null,
      crossChatMemoryEnabled: true,
      autoCompactLongChats: true,
      navCollapsed: false,
      settingsSidebarCollapsed: false,
      currentRunId: null,
      activeRunUserId: null,
      activeRunThreadId: null,
      currentStage: "idle",
      pendingPrompt: "",
      pendingAttachments: [],
      liveAnswer: "",
      liveError: "",
      compactionNotice: null,
      isStreaming: false,
      setTheme: (theme) => set({ theme }),
      setCurrentUserId: (value) => set({ currentUserId: value }),
      setCurrentThreadId: (value) => set({ currentThreadId: value }),
      setCurrentThreadTitle: (value) => set({ currentThreadTitle: value }),
      setDraftThreadModel: (value) => set({ draftThreadModel: value }),
      setDraftThreadTemperature: (value) => set({ draftThreadTemperature: value }),
      setCrossChatMemoryEnabled: (value) => set({ crossChatMemoryEnabled: value }),
      setAutoCompactLongChats: (value) => set({ autoCompactLongChats: value }),
      toggleNavCollapsed: () => set((state) => ({ navCollapsed: !state.navCollapsed })),
      toggleSettingsSidebarCollapsed: () =>
        set((state) => ({ settingsSidebarCollapsed: !state.settingsSidebarCollapsed })),
      beginRun: (runId, prompt, userId, threadId, attachments = []) =>
        set({
          currentRunId: runId,
          activeRunUserId: userId,
          activeRunThreadId: threadId,
          pendingPrompt: prompt,
          pendingAttachments: attachments,
          currentStage: "starting",
          liveAnswer: "",
          liveError: "",
          compactionNotice: null,
          isStreaming: true,
        }),
      appendToken: (text) => set((state) => ({ liveAnswer: `${state.liveAnswer}${text}` })),
      setStage: (stage) => set({ currentStage: stage }),
      completeRun: () =>
        set({
          currentRunId: null,
          activeRunUserId: null,
          activeRunThreadId: null,
          isStreaming: false,
          pendingPrompt: "",
          pendingAttachments: [],
          liveAnswer: "",
          liveError: "",
          compactionNotice: null,
          currentStage: "completed",
        }),
      failRun: (message) =>
        set({
          currentRunId: null,
          isStreaming: false,
          liveError: message,
          compactionNotice: null,
          currentStage: "failed",
        }),
      showCompactionNotice: (notice) => set({ compactionNotice: notice }),
      clearCompactionNotice: () => set({ compactionNotice: null }),
      clearLiveRun: () =>
        set({
          currentRunId: null,
          activeRunUserId: null,
          activeRunThreadId: null,
          currentStage: "idle",
          pendingPrompt: "",
          pendingAttachments: [],
          liveAnswer: "",
          liveError: "",
          compactionNotice: null,
          isStreaming: false,
        }),
    }),
    {
      name: "atlas-ui-state",
      version: 5,
      migrate: (persistedState, version) => {
        if (!persistedState || typeof persistedState !== "object") {
          return persistedState as AtlasState;
        }
        const state = persistedState as Partial<AtlasState>;
        const migrated: Partial<AtlasState> = { ...state };
        if (version < 2) {
          migrated.draftThreadTemperature = null;
        }
        if (version < 3) {
          migrated.navCollapsed = false;
          migrated.settingsSidebarCollapsed = false;
        }
        if (version < 4) {
          migrated.currentUserId = typeof migrated.currentUserId === "string" ? migrated.currentUserId : "";
        }
        return migrated as AtlasState;
      },
      partialize: (state) => ({
        theme: state.theme,
        currentUserId: state.currentUserId,
        currentThreadId: state.currentThreadId,
        currentThreadTitle: state.currentThreadTitle,
        draftThreadModel: state.draftThreadModel,
        draftThreadTemperature: state.draftThreadTemperature,
        crossChatMemoryEnabled: state.crossChatMemoryEnabled,
        autoCompactLongChats: state.autoCompactLongChats,
        navCollapsed: state.navCollapsed,
        settingsSidebarCollapsed: state.settingsSidebarCollapsed,
      }),
      storage: createJSONStorage(() => localStorage),
    },
  ),
);
