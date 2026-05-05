import { describe, expect, it } from "vitest";

import { buildContextMeter } from "./contextMeter";

describe("buildContextMeter", () => {
  it("uses the post-compaction baseline during an active compacted run", () => {
    const meter = buildContextMeter({
      contextUsage: {
        context_window: 8192,
        auto_compact_ratio: 0.72,
        auto_compact_threshold: 5898,
        representation_tokens: 5600,
      },
      compactionNotice: {
        detectedContextWindow: 8192,
        historyRepresentationTokensAfterCompaction: 320,
      },
      visibleHistory: [],
      hasActiveRun: true,
      pendingPrompt: "this prompt is already included in the compaction baseline".repeat(160),
      liveAnswer: "answer".repeat(80),
      draftPrompt: "",
    });

    expect(meter.tokensUsed).toBe(440);
    expect(meter.remainingPercent).toBe(93);
    expect(meter.tone).toBe("ok");
  });

  it("keeps charging live answer text before a compaction event arrives", () => {
    const meter = buildContextMeter({
      contextUsage: {
        context_window: 8192,
        auto_compact_ratio: 0.72,
        auto_compact_threshold: 5898,
        representation_tokens: 300,
      },
      visibleHistory: [],
      hasActiveRun: true,
      pendingPrompt: "make a python and html example",
      liveAnswer: "x".repeat(22000),
      draftPrompt: "",
    });

    expect(meter.tokensUsed).toBeGreaterThan(5700);
    expect(meter.remainingPercent).toBeLessThan(4);
    expect(meter.tone).toBe("critical");
  });

  it("falls back to the visible history estimate when the backend has not reported usage yet", () => {
    const meter = buildContextMeter({
      visibleHistory: [
        {
          content: "a".repeat(400),
          attachments: [{ text_content: "b".repeat(80) }],
        },
      ],
      hasActiveRun: false,
      draftPrompt: "c".repeat(20),
    });

    expect(meter.detected).toBe(false);
    expect(meter.fromServer).toBe(false);
    expect(meter.contextWindow).toBe(8192);
    expect(meter.tokensUsed).toBe(125);
  });
});
