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
  representation_tokens?: number | null;
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
  remainingPercent: number;
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

  let liveCharEstimate = 0;
  if (input.hasActiveRun) {
    if (compactedBaseTokens > 0) {
      liveCharEstimate += (input.liveAnswer ?? "").length;
    } else {
      liveCharEstimate += (input.pendingPrompt ?? "").length;
      liveCharEstimate += (input.liveAnswer ?? "").length;
      for (const attachment of input.pendingAttachments ?? []) {
        if (attachment.text_content) {
          liveCharEstimate += attachment.text_content.length;
        }
      }
    }
  }
  liveCharEstimate += (input.draftPrompt ?? "").length;

  const projectedTokens = tokensUsed + Math.ceil(liveCharEstimate / 4);
  const rawRemaining = 1 - projectedTokens / autoCompactBudget;
  const remainingRatio = Math.max(0, Math.min(1, rawRemaining));
  const remainingPercent = Math.round(remainingRatio * 100);
  const tone = remainingRatio <= 0.1 ? "critical" : remainingRatio <= 0.25 ? "warning" : "ok";

  return {
    contextWindow,
    autoCompactBudget,
    tokensUsed: projectedTokens,
    remainingPercent,
    tone,
    detected: detectedWindow > 0,
    fromServer: Boolean(input.contextUsage),
  };
}
