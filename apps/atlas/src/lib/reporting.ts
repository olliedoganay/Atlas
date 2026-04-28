export const ATLAS_SUPPORT_EMAIL = "partex@msn.com";

const MAX_REPORTED_OUTPUT_LENGTH = 1800;

type AiContentReportInput = {
  threadTitle?: string | null;
  threadId?: string | null;
  model?: string | null;
  messageRef?: string | null;
  output?: string | null;
};

export function buildAiContentReportMailto(input: AiContentReportInput = {}) {
  const subject = "Atlas Chat AI content report";
  const body = [
    "Please review this AI-generated content report.",
    "",
    `Thread: ${input.threadTitle || "Unknown"}`,
    `Thread ID: ${input.threadId || "Unknown"}`,
    `Model: ${input.model || "Unknown"}`,
    `Message reference: ${input.messageRef || "Unknown"}`,
    "",
    "Reported output:",
    truncateReportedOutput(input.output || ""),
    "",
    "Why is this content inappropriate?",
    "",
  ].join("\n");

  return `mailto:${ATLAS_SUPPORT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

export function buildGeneralAiReportMailto() {
  const subject = "Atlas Chat AI content report";
  const body = [
    "Please describe the AI-generated content you want to report.",
    "",
    "Thread or model, if known:",
    "",
    "Why is this content inappropriate?",
    "",
  ].join("\n");

  return `mailto:${ATLAS_SUPPORT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function truncateReportedOutput(output: string) {
  const normalized = output.trim();
  if (normalized.length <= MAX_REPORTED_OUTPUT_LENGTH) {
    return normalized;
  }
  return `${normalized.slice(0, MAX_REPORTED_OUTPUT_LENGTH)}\n\n[Output truncated for email length.]`;
}
