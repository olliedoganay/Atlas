import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useAtlasStore } from "./useAtlasStore";

const initialState = useAtlasStore.getInitialState();

describe("useAtlasStore run state", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useAtlasStore.setState(initialState, true);
  });

  afterEach(() => {
    window.localStorage.clear();
    useAtlasStore.setState(initialState, true);
  });

  it("clears the active run mode when a run fails", () => {
    useAtlasStore.getState().beginRun("run-1", "compact", "", "user-1", "main", []);

    useAtlasStore.getState().failRun("Compaction failed.", "user-1", "main");

    const state = useAtlasStore.getState();
    expect(state.currentRunId).toBeNull();
    expect(state.currentRunMode).toBeNull();
    expect(state.isStreaming).toBe(false);
    expect(state.liveError).toBe("Compaction failed.");
  });

  it("toggles pinned chat keys per profile", () => {
    useAtlasStore.getState().togglePinnedThread("ollie", "main");
    expect(useAtlasStore.getState().pinnedThreadKeys).toEqual(["ollie::main"]);

    useAtlasStore.getState().togglePinnedThread("ollie", "main");
    expect(useAtlasStore.getState().pinnedThreadKeys).toEqual([]);
  });
});
