import { describe, expect, it } from "vitest";

import { normalizeSettingsSection, PROFILE_SETTINGS_PATH } from "./settingsSections";

describe("settings section routing", () => {
  it("normalizes known settings sections", () => {
    expect(normalizeSettingsSection("profiles")).toBe("profiles");
    expect(normalizeSettingsSection("models")).toBe("models");
  });

  it("falls back to general for missing or unknown sections", () => {
    expect(normalizeSettingsSection(null)).toBe("general");
    expect(normalizeSettingsSection("users")).toBe("general");
  });

  it("exposes a direct profile management path", () => {
    expect(PROFILE_SETTINGS_PATH).toBe("/settings?section=profiles");
  });
});
