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

    expect(meter.tokensUsed).toBe(320);
    expect(meter.projectedTokensUsed).toBe(440);
    expect(meter.remainingPercent).toBe(95);
    expect(meter.projectedRemainingPercent).toBe(93);
    expect(meter.tone).toBe("ok");
  });

  it("keeps the stable meter from draining on unsaved live answer text", () => {
    const meter = buildContextMeter({
      contextUsage: {
        context_window: 8192,
        auto_compact_ratio: 0.72,
        auto_compact_threshold: 5898,
        representation_tokens: 300,
        summary_tokens: 120,
        raw_message_tokens: 180,
        compacted_message_count: 4,
        recent_raw_message_count: 2,
        message_count: 6,
      },
      visibleHistory: [],
      hasActiveRun: true,
      pendingPrompt: "make a python and html example",
      liveAnswer: "x".repeat(22000),
      draftPrompt: "",
    });

    expect(meter.tokensUsed).toBeLessThan(400);
    expect(meter.remainingPercent).toBeGreaterThan(90);
    expect(meter.projectedTokensUsed).toBeGreaterThan(5700);
    expect(meter.projectedRemainingPercent).toBeLessThan(4);
    expect(meter.summaryTokens).toBe(120);
    expect(meter.rawMessageTokens).toBe(180);
    expect(meter.compactedMessageCount).toBe(4);
    expect(meter.recentRawMessageCount).toBe(2);
    expect(meter.messageCount).toBe(6);
    expect(meter.tone).toBe("ok");
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
