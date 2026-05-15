import { afterEach, describe, expect, it, vi } from "vitest";

import { buildChatMarkdownExport, chatExportFilename, downloadMarkdownFile } from "./chatExport";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("chat export helpers", () => {
  it("builds a markdown transcript with metadata and attachments", () => {
    const markdown = buildChatMarkdownExport(
      {
        title: "Research Notes",
        threadId: "thread-1",
        userId: "ollie",
        model: "llama3.1:8b",
      },
      [
        {
          role: "user",
          content: "Summarize this.",
          timestamp: "2026-05-15T08:00:00Z",
          attachments: [{ name: "notes.md", media_type: "text/markdown", kind: "file", byte_size: 2048 }],
        },
        { role: "assistant", content: "Here is the summary." },
      ],
    );

    expect(markdown).toContain("# Research Notes");
    expect(markdown).toContain("- Profile: ollie");
    expect(markdown).toContain("- Model: llama3.1:8b");
    expect(markdown).toContain("- notes.md (file, 2 KB)");
    expect(markdown).toContain("## Model");
  });

  it("normalizes export filenames", () => {
    expect(chatExportFilename("Atlas Chat / Linux Plan", "thread-1")).toBe("atlas-chat-linux-plan.md");
    expect(chatExportFilename("", "thread-1")).toBe("thread-1.md");
  });

  it("downloads markdown through a temporary object URL", () => {
    const createObjectURL = vi.fn(() => "blob:atlas");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    downloadMarkdownFile("chat.md", "# Chat\n");

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:atlas");

    click.mockRestore();
  });
});
