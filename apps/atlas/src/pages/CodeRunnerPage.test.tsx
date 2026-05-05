import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({
    onCloseRequested: vi.fn().mockResolvedValue(() => undefined),
    setTitle: vi.fn().mockResolvedValue(undefined),
  }),
}));

vi.mock("react-router-dom", () => ({
  useParams: () => ({ token: "token-1" }),
}));

const apiMocks = vi.hoisted(() => ({
  getRunnerStatus: vi.fn(),
  execCode: vi.fn(),
  stopRunnerRun: vi.fn(),
  streamRunnerRun: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  getRunnerStatus: apiMocks.getRunnerStatus,
  execCode: apiMocks.execCode,
  stopRunnerRun: apiMocks.stopRunnerRun,
  streamRunnerRun: apiMocks.streamRunnerRun,
}));

import { buildClientPreviewBlob, buildClientPreviewDocument, CLIENT_PREVIEW_SANDBOX, CodeRunnerPage } from "./CodeRunnerPage";

function readBlobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read blob."));
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.readAsText(blob);
  });
}

describe("CodeRunnerPage client preview", () => {
  beforeEach(() => {
    window.localStorage.clear();
    apiMocks.getRunnerStatus.mockResolvedValue({ available: true });
    apiMocks.execCode.mockResolvedValue({ run_id: "run-1" });
    apiMocks.stopRunnerRun.mockResolvedValue({ run_id: "run-1", status: "stopping" });
    apiMocks.streamRunnerRun.mockReturnValue(vi.fn());
  });

  afterEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("keeps complete HTML documents intact while adding preview diagnostics", async () => {
    const code = [
      "<!DOCTYPE html>",
      "<html>",
      "<head><style>canvas{background:#111}</style></head>",
      "<body><canvas id=\"gameCanvas\"></canvas><script>window.atlasPreviewRan=true;</script></body>",
      "</html>",
    ].join("");

    const preview = buildClientPreviewDocument(code, "test-channel");

    expect(preview).toContain("<!DOCTYPE html>");
    expect(preview).toContain("<style>canvas{background:#111}</style>");
    expect(preview).toContain("<canvas id=\"gameCanvas\"></canvas>");
    expect(preview).toContain("<script>window.atlasPreviewRan=true;</script>");
    expect(preview).toContain('http-equiv="Content-Security-Policy"');
    expect(preview).toContain("style-src-elem");
    expect(preview).toContain("atlas-client-preview");
    expect(preview).toContain("test-channel");
  });

  it("wraps HTML fragments in a runnable preview document", () => {
    const preview = buildClientPreviewDocument("<h1>Hello</h1>", "fragment-channel");

    expect(preview).toContain("<!DOCTYPE html>");
    expect(preview).toContain('<meta charset="utf-8" />');
    expect(preview).toContain("<body><h1>Hello</h1></body>");
    expect(preview).toContain("fragment-channel");
  });

  it("can still build raw HTML blobs for callers that need them", async () => {
    const code = "<!DOCTYPE html><html><body>raw</body></html>";
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

  it("stops an active server run when the run page unmounts", async () => {
    window.localStorage.setItem(
      "atlas-runner:token-1",
      JSON.stringify({ language: "python", code: "print('hello')" }),
    );
    const { root, container } = renderRunnerPage();

    await flushEffects();
    expect(apiMocks.execCode).toHaveBeenCalledWith("python", "print('hello')");

    act(() => {
      root.unmount();
    });
    container.remove();

    expect(apiMocks.stopRunnerRun).toHaveBeenCalledWith("run-1");
  });

  it("shows a retry path when Docker is unavailable", async () => {
    apiMocks.getRunnerStatus.mockResolvedValue({ available: false, reason: "Docker is stopped." });
    window.localStorage.setItem(
      "atlas-runner:token-1",
      JSON.stringify({ language: "python", code: "print('hello')" }),
    );
    const { root, container } = renderRunnerPage();

    await flushEffects();

    expect(container.textContent).toContain("Docker Desktop isn't running");
    expect(container.textContent).toContain("Docker is stopped.");
    expect(container.textContent).toContain("Retry");

    act(() => {
      root.unmount();
    });
    container.remove();
  });
});

function renderRunnerPage(): { root: Root; container: HTMLDivElement } {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() => {
    root.render(<CodeRunnerPage />);
  });
  return { root, container };
}

async function flushEffects() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}
