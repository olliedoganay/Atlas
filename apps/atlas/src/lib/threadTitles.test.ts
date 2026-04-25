import { describe, expect, it } from "vitest";

import { displayThreadTitle, editableThreadTitle, requestThreadTitle } from "./threadTitles";

describe("thread title helpers", () => {
  it("hides generated draft ids from the UI", () => {
    const id = "atlas-2026-04-24-21-48-23-818-b8e566";

    expect(displayThreadTitle("", id)).toBe("New chat");
    expect(editableThreadTitle(id, id)).toBe("");
    expect(requestThreadTitle("", id)).toBeUndefined();
  });

  it("keeps intentional user titles", () => {
    expect(displayThreadTitle("Research plan", "atlas-2026-04-24-21-48-23-818-b8e566")).toBe(
      "Research plan",
    );
    expect(requestThreadTitle("Research plan", "atlas-2026-04-24-21-48-23-818-b8e566")).toBe(
      "Research plan",
    );
  });

  it("normalizes the built-in main thread", () => {
    expect(displayThreadTitle("", "main")).toBe("Main");
  });
});
