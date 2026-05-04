import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({
    onCloseRequested: vi.fn(),
    setTitle: vi.fn(),
  }),
}));

import { buildClientPreviewBlob, CLIENT_PREVIEW_SANDBOX } from "./CodeRunnerPage";

function readBlobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read blob."));
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.readAsText(blob);
  });
}

describe("CodeRunnerPage client preview", () => {
  it("keeps complete HTML documents intact for blob previews", async () => {
    const code = [
      "<!DOCTYPE html>",
      "<html>",
      "<head><style>canvas{background:#111}</style></head>",
      "<body><canvas id=\"gameCanvas\"></canvas><script>window.atlasPreviewRan=true;</script></body>",
      "</html>",
    ].join("");

    const blob = buildClientPreviewBlob(code);

    expect(blob.type).toBe("text/html;charset=utf-8");
    await expect(readBlobText(blob)).resolves.toBe(code);
  });

  it("allows scripts without granting same-origin access", () => {
    const tokens = CLIENT_PREVIEW_SANDBOX.split(" ");

    expect(tokens).toContain("allow-scripts");
    expect(tokens).toContain("allow-pointer-lock");
    expect(tokens).not.toContain("allow-same-origin");
  });
});
