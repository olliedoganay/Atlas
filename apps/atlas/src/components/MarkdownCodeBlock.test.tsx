import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const runnerMocks = vi.hoisted(() => ({
  openRunnerWindow: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../lib/runner", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/runner")>();
  return {
    ...actual,
    openRunnerWindow: runnerMocks.openRunnerWindow,
  };
});

import { MarkdownCodeBlock } from "./MarkdownCodeBlock";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function render(element: React.ReactElement) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => {
    root?.render(element);
  });
  return container;
}

describe("MarkdownCodeBlock", () => {
  afterEach(() => {
    act(() => {
      root?.unmount();
    });
    root = null;
    container?.remove();
    container = null;
    runnerMocks.openRunnerWindow.mockClear();
  });

  it("shows Run next to Copy for runnable code blocks", async () => {
    const node = render(<MarkdownCodeBlock code="print('hello')" language="python" />);

    const buttons = Array.from(node.querySelectorAll("button"));
    expect(buttons).toHaveLength(2);
    expect(buttons[0].textContent).toContain("Run");
    expect(buttons[1].textContent).toContain("Copy");

    await act(async () => {
      buttons[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(runnerMocks.openRunnerWindow).toHaveBeenCalledWith({
      language: "python",
      code: "print('hello')",
    });
  });

  it("only shows Copy for unsupported code blocks", () => {
    const node = render(<MarkdownCodeBlock code="not runnable" language="brainfuck" />);

    const buttons = Array.from(node.querySelectorAll("button"));
    expect(buttons).toHaveLength(1);
    expect(buttons[0].textContent).toContain("Copy");
  });
});
