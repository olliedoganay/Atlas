import type { ChatAttachment } from "./api";
import { displayThreadTitle } from "./threadTitles";

export type ExportableThread = {
  title?: string | null;
  threadId: string;
  userId: string;
  model?: string | null;
};

export type ExportableMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  attachments?: ChatAttachment[];
  timestamp?: string;
};

export function buildChatMarkdownExport(thread: ExportableThread, messages: ExportableMessage[]) {
  const title = displayThreadTitle(thread.title, thread.threadId, "Atlas Chat");
  const lines = [
    `# ${escapeMarkdownHeading(title)}`,
    "",
    `- Profile: ${thread.userId || "Unknown"}`,
    `- Thread: ${thread.threadId}`,
    `- Model: ${thread.model || "Unknown"}`,
    `- Exported: ${new Date().toISOString()}`,
    "",
  ];

  messages.forEach((message) => {
    const role = message.role === "assistant" ? "Model" : titleCase(message.role);
    const timestamp = message.timestamp ? ` · ${message.timestamp}` : "";
    lines.push(`## ${role}${timestamp}`, "");
    if (message.attachments?.length) {
      lines.push("Attachments:");
      message.attachments.forEach((attachment) => {
        const size = formatAttachmentSize(attachment.byte_size);
        const kind = attachment.kind || (attachment.media_type?.startsWith("image/") ? "image" : "file");
        lines.push(`- ${attachment.name || "attachment"} (${kind}${size ? `, ${size}` : ""})`);
      });
      lines.push("");
    }
    lines.push(message.content || "_No text content._", "");
  });

  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trimEnd() + "\n";
}

export function downloadMarkdownFile(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function chatExportFilename(title: string, threadId: string) {
  const base = (title || threadId || "atlas-chat")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 72);
  return `${base || "atlas-chat"}.md`;
}

function escapeMarkdownHeading(value: string) {
  return value.replace(/^[#\s]+/, "").trim() || "Atlas Chat";
}

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatAttachmentSize(value?: number) {
  if (!value || value <= 0) {
    return "";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const precision = size >= 10 || unitIndex === 0 || Number.isInteger(size) ? 0 : 1;
  return `${size.toFixed(precision)} ${units[unitIndex]}`;
}
