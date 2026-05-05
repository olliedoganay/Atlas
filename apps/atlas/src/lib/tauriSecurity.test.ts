import tauriConfig from "../../src-tauri/tauri.conf.json";
import { describe, expect, it } from "vitest";

const FRAME_SOURCES = ["'self'", "about:", "data:", "blob:", "http://127.0.0.1:*", "http://localhost:*"];

function directiveValue(csp: string, directive: string): string {
  const entry = csp
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${directive} `));
  return entry ?? "";
}

describe("Tauri security policy", () => {
  it("allows runner iframe previews in packaged and dev CSPs", () => {
    const policies = [tauriConfig.app.security.csp, tauriConfig.app.security.devCsp];

    for (const policy of policies) {
      const frameSrc = directiveValue(policy, "frame-src");
      expect(frameSrc).not.toContain("'none'");
      for (const source of FRAME_SOURCES) {
        expect(frameSrc).toContain(source);
      }
    }
  });
});
