import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/webviewWindow", () => ({
  WebviewWindow: class MockWebviewWindow {
    once() {
      return undefined;
    }
  },
}));

import {
  consumePendingRun,
  isClientLanguage,
  resolveRunnableLanguage,
  stashPendingRun,
} from "./runner";

describe("runner helpers", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("normalizes runnable language aliases", () => {
    expect(resolveRunnableLanguage(" py ")).toBe("python");
    expect(resolveRunnableLanguage("JS")).toBe("javascript");
    expect(resolveRunnableLanguage("c#")).toBe("csharp");
  });

  it("returns null for unsupported languages", () => {
    expect(resolveRunnableLanguage("brainfuck")).toBeNull();
    expect(resolveRunnableLanguage("")).toBeNull();
  });

  it("detects client-only languages", () => {
    expect(isClientLanguage("html")).toBe(true);
    expect(isClientLanguage("python")).toBe(false);
  });

  it("round-trips pending runs through localStorage", () => {
    stashPendingRun("token-1", {
      language: "python",
      code: "print('hello')",
    });

    expect(consumePendingRun("token-1")).toEqual({
      language: "python",
      code: "print('hello')",
    });
    expect(consumePendingRun("token-1")).toBeNull();
  });

  it("returns null for malformed pending payloads", () => {
    window.localStorage.setItem("atlas-runner:broken", "{not-json");

    expect(consumePendingRun("broken")).toBeNull();
    expect(window.localStorage.getItem("atlas-runner:broken")).toBeNull();
  });
});
