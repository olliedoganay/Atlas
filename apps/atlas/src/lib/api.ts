import { invoke } from "@tauri-apps/api/core";

type BackendRuntime = {
  host: string;
  port: number;
  token: string;
};

let runtimePromise: Promise<BackendRuntime> | null = null;
let lastRuntime: BackendRuntime | null = null;

export type ThemeMode = "light" | "dark";
export type RunMode = "chat" | "compact";

export type ThreadSummary = {
  user_id: string;
  thread_id: string;
  title?: string;
  chat_model?: string;
  temperature?: number | null;
  last_mode?: string;
  updated_at?: string;
  last_prompt?: string;
  last_run_id?: string;
};

export type ImageAttachment = {
  name: string;
  media_type: string;
  data_url: string;
};

export type UserSummary = {
  user_id: string;
  updated_at?: string;
  protection?: "passwordless" | "password";
  locked?: boolean;
};

export type StoredMemory = {
  memory: string;
  memory_id: string;
  score?: number | null;
  metadata?: Record<string, unknown> | null;
};

export type BackendStatus = {
  status: string;
  product_name: string;
  backend: string;
  default_chat_model: string;
  chat_model: string;
  default_chat_temperature: number;
  chat_temperature: number;
  embed_model: string;
  ollama_url: string;
  runtime_mode: string;
  busy: boolean;
  security: {
    profile_key_protection: string;
    run_artifacts_encrypted_at_rest: boolean;
    run_index_encrypted_at_rest: boolean;
    packaged_logs_default: string;
    sqlite_encrypted_at_rest: boolean;
    sqlite_paths: string[];
    vector_store: string;
    vector_store_encrypted_at_rest: boolean;
    vector_store_path: string;
  };
};

export type TemperaturePreset = {
  label: string;
  value: number;
};

export type ModelCatalog = {
  default_model: string;
  default_temperature: number;
  temperature_presets: TemperaturePreset[];
  models: string[];
  model_details: Array<{
    name: string;
    family?: string;
    families?: string[];
    supports_images?: boolean;
  }>;
};

export type RunStatusEvent = {
  type: string;
  timestamp: string;
  payload: Record<string, unknown>;
};

export type RunSummary = {
  run_id: string;
  mode: string;
  user_id: string;
  thread_id: string;
  chat_model?: string;
  temperature?: number | null;
  prompt: string;
  status: string;
  started_at: string;
  completed_at?: string | null;
  answer: string;
  events: RunStatusEvent[];
  error?: string | null;
  thread_summary?: string;
  compacted_message_count?: number;
  detected_context_window?: number;
};

export type ThreadMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  attachments?: ImageAttachment[];
  kind?: string;
  run_id?: string;
  timestamp?: string;
  thread_summary?: string;
  compacted_message_count?: number;
  newly_compacted_message_count?: number;
  detected_context_window?: number;
  history_representation_tokens_before_compaction?: number;
  history_representation_tokens_after_compaction?: number;
  compaction_reason?: string;
};

export type ChatSearchResult = {
  thread_id: string;
  thread_title: string;
  chat_model?: string;
  updated_at?: string;
  match_type: "thread" | "message";
  role?: "user" | "assistant" | null;
  history_index?: number | null;
  snippet: string;
};

export type ChatSearchResponse = {
  query: string;
  current_thread_id: string;
  current_thread_results: ChatSearchResult[];
  other_thread_results: ChatSearchResult[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const primaryRuntime = await getBackendRuntime();

  try {
    return await requestWithRuntime<T>(primaryRuntime, path, init);
  } catch (error) {
    invalidateBackendRuntime();
    const refreshedRuntime = await getBackendRuntime();
    const changedRuntime =
      refreshedRuntime.host !== primaryRuntime.host ||
      refreshedRuntime.port !== primaryRuntime.port ||
      refreshedRuntime.token !== primaryRuntime.token;

    if (!changedRuntime) {
      throw error;
    }

    return requestWithRuntime<T>(refreshedRuntime, path, init);
  }
}

export function getStatus() {
  return request<BackendStatus>("/status");
}

export function getModels() {
  return request<ModelCatalog>("/models");
}

export function getHealth() {
  return request<{ status: string; product: string }>("/health");
}

export function getThreads(userId?: string) {
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  return request<ThreadSummary[]>(`/threads${query}`);
}

export function getUsers() {
  return request<UserSummary[]>("/users");
}

export function createUser(userId: string, password?: string) {
  return request<UserSummary>("/users", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, password: password || null }),
  });
}

export function unlockUser(userId: string, password?: string) {
  return request<UserSummary>(`/users/${encodeURIComponent(userId)}/unlock`, {
    method: "POST",
    body: JSON.stringify({ password: password || null }),
  });
}

export function lockUser(userId: string) {
  return request<UserSummary>(`/users/${encodeURIComponent(userId)}/lock`, {
    method: "POST",
  });
}

export function deleteUser(userId: string) {
  return request<{ status: string; user_id: string }>(
    `/users/${encodeURIComponent(userId)}?confirmation_user_id=${encodeURIComponent(userId)}`,
    {
      method: "DELETE",
    },
  );
}

export function getMemories(userId: string, limit = 50) {
  return request<StoredMemory[]>(`/memories?user_id=${encodeURIComponent(userId)}&limit=${limit}`);
}

export function createMemory(userId: string, text: string) {
  return request<{ status: string; user_id: string; memory_id: string; text: string }>("/memories", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, text }),
  });
}

export function deleteMemory(userId: string, memoryId: string) {
  return request<{ status: string; user_id: string; memory_id: string }>(
    `/memories/${encodeURIComponent(memoryId)}?user_id=${encodeURIComponent(userId)}`,
    {
      method: "DELETE",
    },
  );
}

export function renameThread(threadId: string, userId: string, title: string) {
  return request<ThreadSummary>(`/threads/${encodeURIComponent(threadId)}/title`, {
    method: "PATCH",
    body: JSON.stringify({ user_id: userId, title }),
  });
}

export function duplicateThread(threadId: string, userId: string) {
  return request<ThreadSummary>(`/threads/${encodeURIComponent(threadId)}/duplicate`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
}

export function getThreadHistory(threadId: string, userId?: string) {
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  return request<ThreadMessage[]>(`/threads/${encodeURIComponent(threadId)}/history${query}`);
}

export function searchChats(query: string, userId: string, currentThreadId?: string, limit = 8) {
  const params = new URLSearchParams({
    user_id: userId,
    q: query,
    limit: String(limit),
  });
  if (currentThreadId) {
    params.set("current_thread_id", currentThreadId);
  }
  return request<ChatSearchResponse>(`/search?${params.toString()}`);
}

export function getRun(runId: string) {
  return request<RunSummary>(`/runs/${encodeURIComponent(runId)}`);
}

export function cancelRun(runId: string) {
  return request<{ status: string; run_id: string; detail?: string }>(`/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
  });
}

export function startChat(
  prompt: string,
  userId: string,
  threadId: string,
  chatModel?: string,
  temperature?: number | null,
  threadTitle?: string,
  crossChatMemory = true,
  autoCompactLongChats = true,
  images: ImageAttachment[] = [],
) {
  return request<{ run_id: string; status: string; mode: RunMode; chat_model: string; temperature: number | null }>("/chat", {
    method: "POST",
    body: JSON.stringify({
      prompt,
      user_id: userId,
      thread_id: threadId,
      chat_model: chatModel,
      temperature,
      thread_title: threadTitle,
      cross_chat_memory: crossChatMemory,
      auto_compact_long_chats: autoCompactLongChats,
      images,
    }),
  });
}

export function startCompact(threadId: string, userId: string) {
  return request<{ run_id: string; status: string; mode: RunMode; chat_model: string; temperature: number | null }>(
    `/threads/${encodeURIComponent(threadId)}/compact`,
    {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    },
  );
}

export function resetThread(threadId: string, userId?: string) {
  return request<Record<string, unknown>>("/admin/reset/thread", {
    method: "POST",
    body: JSON.stringify({ thread_id: threadId, user_id: userId }),
  });
}

export function resetAll() {
  return request<Record<string, unknown>>("/admin/reset/all", {
    method: "POST",
    body: JSON.stringify({ confirmation: "RESET ATLAS" }),
  });
}

export function streamRun(
  mode: RunMode,
  runId: string,
  onEvent: (event: RunStatusEvent) => void,
  onError: (message: string) => void,
): () => void {
  let source: EventSource | null = null;
  let closed = false;
  void getBackendRuntime()
    .then((runtime) => {
      if (closed) {
        return;
      }
      const tokenQuery = runtime.token ? `?token=${encodeURIComponent(runtime.token)}` : "";
      source = new EventSource(`${buildApiUrl(runtime)}/${mode}/stream/${encodeURIComponent(runId)}${tokenQuery}`);
      const handler = (event: Event) => {
        const message = event as MessageEvent<string>;
        try {
          onEvent(JSON.parse(message.data) as RunStatusEvent);
        } catch (error) {
          onError(error instanceof Error ? error.message : "Failed to parse stream event.");
        }
      };

      const eventNames = [
        "run_started",
        "stage_changed",
        "thinking_token",
        "token",
        "context_compacted",
        "run_completed",
        "run_failed",
      ];
      eventNames.forEach((name) => source?.addEventListener(name, handler as EventListener));
      source.onerror = () => {
        onError("Atlas stream disconnected.");
        source?.close();
      };
    })
    .catch((error) => {
      onError(error instanceof Error ? error.message : "Atlas runtime is unavailable.");
    });

  return () => {
    closed = true;
    source?.close();
  };
}

export function invalidateBackendRuntime() {
  runtimePromise = null;
}

export async function restartManagedBackend(options?: { attempts?: number; delayMs?: number }) {
  await invoke("restart_backend");
  invalidateBackendRuntime();
  return waitForBackendReady(options);
}

export async function waitForBackendReady(options?: { attempts?: number; delayMs?: number }) {
  const attempts = Math.max(1, options?.attempts ?? 30);
  const delayMs = Math.max(50, options?.delayMs ?? 250);
  let lastError: unknown = null;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await getStatus();
    } catch (error) {
      lastError = error;
      invalidateBackendRuntime();
      if (attempt < attempts - 1) {
        await sleep(delayMs);
      }
    }
  }

  if (lastError instanceof Error) {
    throw lastError;
  }
  throw new Error("Atlas backend did not become ready.");
}

async function getBackendRuntime(): Promise<BackendRuntime> {
  if (!runtimePromise) {
    runtimePromise = resolveBackendRuntime();
  }
  return runtimePromise;
}

async function resolveBackendRuntime(): Promise<BackendRuntime> {
  try {
    const runtime = await invoke<BackendRuntime>("backend_runtime");
    lastRuntime = runtime;
    return runtime;
  } catch (error) {
    if (lastRuntime) {
      return lastRuntime;
    }
    throw error instanceof Error ? error : new Error("Atlas backend runtime is unavailable.");
  }
}

function buildApiUrl(runtime: BackendRuntime): string {
  return `http://${runtime.host}:${runtime.port}`;
}

async function requestWithRuntime<T>(runtime: BackendRuntime, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${buildApiUrl(runtime)}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(runtime.token ? { "X-Atlas-Instance-Token": runtime.token } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    const payload =
      contentType.includes("application/json") ? await response.json() : { detail: await response.text() };
    throw new Error(String(payload.detail ?? payload.error ?? response.statusText));
  }

  return (await response.json()) as T;
}

function sleep(delayMs: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, delayMs);
  });
}
