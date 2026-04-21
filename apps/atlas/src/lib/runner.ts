import { WebviewWindow } from "@tauri-apps/api/webviewWindow";

const SERVER_LANGUAGES = [
  "python",
  "javascript",
  "typescript",
  "go",
  "rust",
  "c",
  "cpp",
  "java",
  "ruby",
  "php",
  "bash",
  "csharp",
  "kotlin",
  "swift",
  "perl",
  "lua",
  "r",
  "elixir",
  "dart",
] as const;

const CLIENT_LANGUAGES = ["html"] as const;

const LANGUAGE_ALIASES: Record<string, string> = {
  py: "python",
  python3: "python",
  js: "javascript",
  node: "javascript",
  ts: "typescript",
  golang: "go",
  rs: "rust",
  "c++": "cpp",
  cxx: "cpp",
  cc: "cpp",
  rb: "ruby",
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  cs: "csharp",
  "c#": "csharp",
  kt: "kotlin",
  kts: "kotlin",
  pl: "perl",
  ex: "elixir",
  exs: "elixir",
  htm: "html",
};

export const RUNNABLE_LANGUAGES: readonly string[] = [...SERVER_LANGUAGES, ...CLIENT_LANGUAGES];

export function resolveRunnableLanguage(language: string): string | null {
  const normalized = (language || "").trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  if ((RUNNABLE_LANGUAGES as readonly string[]).includes(normalized)) {
    return normalized;
  }
  if (normalized in LANGUAGE_ALIASES) {
    return LANGUAGE_ALIASES[normalized];
  }
  return null;
}

export function isClientLanguage(language: string): boolean {
  return (CLIENT_LANGUAGES as readonly string[]).includes(language);
}

type PendingRun = {
  language: string;
  code: string;
};

const PENDING_PREFIX = "atlas-runner:";

function storageKey(token: string) {
  return `${PENDING_PREFIX}${token}`;
}

export function stashPendingRun(token: string, payload: PendingRun) {
  try {
    window.localStorage.setItem(storageKey(token), JSON.stringify(payload));
  } catch {
    // ignore quota / privacy failures — the consumer will show an error
  }
}

export function consumePendingRun(token: string): PendingRun | null {
  const key = storageKey(token);
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    raw = null;
  }
  if (!raw) {
    return null;
  }
  try {
    window.localStorage.removeItem(key);
  } catch {
    // best-effort cleanup
  }
  try {
    return JSON.parse(raw) as PendingRun;
  } catch {
    return null;
  }
}

function makeToken(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function openRunnerWindow(payload: PendingRun) {
  const token = makeToken();
  stashPendingRun(token, payload);

  const label = `runner-${token}`;
  const title = `Atlas Run · ${payload.language}`;
  const url = `index.html#/runner/${token}`;

  const runner = new WebviewWindow(label, {
    url,
    title,
    width: 960,
    height: 680,
    resizable: true,
    focus: true,
  });

  await new Promise<void>((resolve, reject) => {
    runner.once("tauri://created", () => resolve());
    runner.once("tauri://error", (event) => {
      reject(new Error(String((event.payload as { message?: string } | undefined)?.message ?? event.payload ?? "unknown")));
    });
  });

  return runner;
}
