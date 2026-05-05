type TextAttachment = {
  text_content?: string | null;
};

type MeterHistoryItem = {
  content?: string | null;
  thread_summary?: string | null;
  attachments?: TextAttachment[] | null;
};

type MeterContextUsage = {
  context_window?: number | null;
  auto_compact_ratio?: number | null;
  auto_compact_threshold?: number | null;
  auto_compact_margin_tokens?: number | null;
  representation_tokens?: number | null;
  summary_tokens?: number | null;
  raw_message_tokens?: number | null;
  compacted_message_count?: number | null;
  recent_raw_message_count?: number | null;
  message_count?: number | null;
};

type MeterCompactionNotice = {
  detectedContextWindow?: number | null;
  historyRepresentationTokensAfterCompaction?: number | null;
};

export type ContextMeterInput = {
  contextUsage?: MeterContextUsage | null;
  compactionNotice?: MeterCompactionNotice | null;
  runDetectedContextWindow?: number | null;
  visibleHistory: MeterHistoryItem[];
  hasActiveRun: boolean;
  pendingPrompt?: string | null;
  pendingAttachments?: TextAttachment[] | null;
  liveAnswer?: string | null;
  draftPrompt?: string | null;
};

export type ContextMeter = {
  contextWindow: number;
  autoCompactBudget: number;
  tokensUsed: number;
  projectedTokensUsed: number;
  liveAnswerTokens: number;
  summaryTokens: number;
  rawMessageTokens: number;
  compactedMessageCount: number;
  recentRawMessageCount: number;
  messageCount: number;
  remainingPercent: number;
  projectedRemainingPercent: number;
  tone: "ok" | "warning" | "critical";
  detected: boolean;
  fromServer: boolean;
};

const FALLBACK_CONTEXT_WINDOW = 8192;
const DEFAULT_AUTO_COMPACT_RATIO = 0.72;

function positiveNumber(value: unknown): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}

function estimateHistoryTokens(visibleHistory: MeterHistoryItem[]): number {
  let charCount = 0;
  for (const item of visibleHistory) {
    charCount += (item.content ?? "").length;
    if (item.thread_summary) {
      charCount += item.thread_summary.length;
    }
    for (const attachment of item.attachments ?? []) {
      if (attachment.text_content) {
        charCount += attachment.text_content.length;
      }
    }
  }
  return Math.ceil(charCount / 4);
}

export function buildContextMeter(input: ContextMeterInput): ContextMeter {
  const autoCompactRatio = positiveNumber(input.contextUsage?.auto_compact_ratio) || DEFAULT_AUTO_COMPACT_RATIO;
  const detectedWindow = positiveNumber(
    input.contextUsage?.context_window ||
      input.compactionNotice?.detectedContextWindow ||
      input.runDetectedContextWindow,
  );
  const contextWindow = detectedWindow > 0 ? detectedWindow : FALLBACK_CONTEXT_WINDOW;
  const serverThreshold = positiveNumber(input.contextUsage?.auto_compact_threshold);
  const autoCompactBudget =
    serverThreshold > 0
      ? serverThreshold
      : Math.max(1024, Math.round(contextWindow * autoCompactRatio));

  const compactedBaseTokens =
    input.hasActiveRun ? positiveNumber(input.compactionNotice?.historyRepresentationTokensAfterCompaction) : 0;
  let tokensUsed = compactedBaseTokens || Number(input.contextUsage?.representation_tokens ?? -1);
  if (!Number.isFinite(tokensUsed) || tokensUsed < 0) {
    tokensUsed = estimateHistoryTokens(input.visibleHistory);
  }

  let pendingCharEstimate = 0;
  if (input.hasActiveRun) {
    if (compactedBaseTokens > 0) {
      // The compaction event already includes the pending user turn in its post-compaction baseline.
    } else {
      pendingCharEstimate += (input.pendingPrompt ?? "").length;
      for (const attachment of input.pendingAttachments ?? []) {
        if (attachment.text_content) {
          pendingCharEstimate += attachment.text_content.length;
        }
      }
    }
  }
  pendingCharEstimate += (input.draftPrompt ?? "").length;

  const liveAnswerTokens = input.hasActiveRun ? Math.ceil((input.liveAnswer ?? "").length / 4) : 0;
  const tokensWithPendingPrompt = tokensUsed + Math.ceil(pendingCharEstimate / 4);
  const projectedTokens = tokensWithPendingPrompt + liveAnswerTokens;
  const rawRemaining = 1 - tokensWithPendingPrompt / autoCompactBudget;
  const remainingRatio = Math.max(0, Math.min(1, rawRemaining));
  const remainingPercent = Math.round(remainingRatio * 100);
  const projectedRemainingRatio = Math.max(0, Math.min(1, 1 - projectedTokens / autoCompactBudget));
  const tone = remainingRatio <= 0.1 ? "critical" : remainingRatio <= 0.25 ? "warning" : "ok";

  return {
    contextWindow,
    autoCompactBudget,
    tokensUsed: tokensWithPendingPrompt,
    projectedTokensUsed: projectedTokens,
    liveAnswerTokens,
    summaryTokens: positiveNumber(input.contextUsage?.summary_tokens),
    rawMessageTokens: positiveNumber(input.contextUsage?.raw_message_tokens),
    compactedMessageCount: positiveNumber(input.contextUsage?.compacted_message_count),
    recentRawMessageCount: positiveNumber(input.contextUsage?.recent_raw_message_count),
    messageCount: positiveNumber(input.contextUsage?.message_count),
    remainingPercent,
    projectedRemainingPercent: Math.round(projectedRemainingRatio * 100),
    tone,
    detected: detectedWindow > 0,
    fromServer: Boolean(input.contextUsage),
  };
}
