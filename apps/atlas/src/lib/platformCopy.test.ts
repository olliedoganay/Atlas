import { describe, expect, it } from "vitest";

import { detectDesktopPlatform, ollamaInstallCopy, platformShellName } from "./platformCopy";

describe("platform copy helpers", () => {
  it("detects common desktop platforms", () => {
    expect(detectDesktopPlatform("Win32", "")).toBe("windows");
    expect(detectDesktopPlatform("MacIntel", "")).toBe("macos");
    expect(detectDesktopPlatform("Linux x86_64", "Wayland")).toBe("linux");
  });

  it("uses platform-specific Ollama setup copy", () => {
    expect(platformShellName("windows")).toBe("PowerShell");
    expect(platformShellName("linux")).toBe("Terminal");
    expect(ollamaInstallCopy("linux")).toContain("distro");
  });
});
