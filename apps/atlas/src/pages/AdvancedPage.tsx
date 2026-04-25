import { useQueries, useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { EmptyState } from "../components/ui/EmptyState";
import { getModels, getRun, getStatus, getThreads } from "../lib/api";
import { displayThreadTitle } from "../lib/threadTitles";
import { useAtlasStore } from "../store/useAtlasStore";

export function AdvancedPage() {
  const navigate = useNavigate();
  const currentUserId = useAtlasStore((state) => state.currentUserId);
  const currentThreadId = useAtlasStore((state) => state.currentThreadId);

  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: getStatus,
    staleTime: 5000,
  });
  const { data: models } = useQuery({
    queryKey: ["models"],
    queryFn: getModels,
    staleTime: 10000,
  });
  const { data: threads = [] } = useQuery({
    queryKey: ["threads", currentUserId],
    queryFn: () => getThreads(currentUserId),
    enabled: Boolean(currentUserId),
    staleTime: 2000,
  });

  const recentRunIds = threads
    .map((thread) => thread.last_run_id)
    .filter((value, index, items): value is string => Boolean(value) && items.indexOf(value) === index)
    .slice(0, 6);
  const recentRunQueries = useQueries({
    queries: recentRunIds.map((runId) => ({
      queryKey: ["run", runId],
      queryFn: () => getRun(runId),
      staleTime: 2000,
    })),
  });
  const recentRuns = recentRunQueries
    .map((query) => query.data)
    .filter((item): item is NonNullable<(typeof recentRunQueries)[number]["data"]> => Boolean(item));
  const currentThread = threads.find((thread) => thread.thread_id === currentThreadId) ?? null;
  const currentRun = recentRuns.find((run) => run.thread_id === currentThreadId) ?? recentRuns[0] ?? null;

  return (
    <section className="advanced-page">
      <div className="workspace-header">
        <div className="workspace-header-copy">
          <h1>Diagnostics</h1>
          <p className="workspace-header-summary">Runtime health and recent run metrics.</p>
        </div>
      </div>

      <div className="advanced-grid">
        <article className="stack-card advanced-card">
          <div className="advanced-card-head">
            <div>
              <p className="workspace-section-label">Runtime</p>
              <h3>Local status</h3>
            </div>
          </div>
          <dl className="advanced-stat-list">
            <div>
              <dt>Backend</dt>
              <dd>{status ? "Online" : "Offline"}</dd>
            </div>
            <div>
              <dt>Ollama</dt>
              <dd>{models?.ollama_online ? "Connected" : "Unavailable"}</dd>
            </div>
            <div>
              <dt>Models</dt>
              <dd>{models?.models.length ?? 0}</dd>
            </div>
            <div>
              <dt>Security</dt>
              <dd>
                {status?.security.sqlite_encrypted_at_rest && status?.security.vector_store_encrypted_at_rest
                  ? "Encrypted at rest"
                  : "Partial hardening"}
              </dd>
            </div>
          </dl>
        </article>

        <article className="stack-card advanced-card">
          <div className="advanced-card-head">
            <div>
              <p className="workspace-section-label">Current thread</p>
              <h3>{displayThreadTitle(currentThread, currentThreadId, "No active thread")}</h3>
            </div>
          </div>
          <dl className="advanced-stat-list">
            <div>
              <dt>Model</dt>
              <dd>{currentThread?.chat_model || "Not set"}</dd>
            </div>
            <div>
              <dt>Temperature</dt>
              <dd>{formatTemperature(currentThread?.temperature)}</dd>
            </div>
            <div>
              <dt>Last run</dt>
              <dd>{currentThread?.last_run_id || "None"}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{formatDate(currentThread?.updated_at)}</dd>
            </div>
          </dl>
        </article>
      </div>

      <div className="advanced-runs">
        <div className="advanced-runs-head">
          <div>
            <p className="workspace-section-label">Runs</p>
            <h2>Recent run metrics</h2>
          </div>
          {currentRun ? <span className="muted-text">Showing the latest local runs for this profile.</span> : null}
        </div>

        {recentRuns.length > 0 ? (
          <div className="advanced-run-list">
            {recentRuns.map((run) => (
              <article className="stack-card advanced-run-card" key={run.run_id}>
                <div className="advanced-run-head">
                  <div>
                    <strong>{displayThreadTitle(run.thread_title, run.thread_id)}</strong>
                    <p>{run.chat_model || "Local model"} - {run.mode}</p>
                  </div>
                  <span
                    className={`status-pill subtle ${run.status === "completed" ? "online" : run.status === "failed" ? "offline" : "muted"}`}
                  >
                    {run.status}
                  </span>
                </div>
                <dl className="advanced-metric-grid">
                  <div>
                    <dt>First token</dt>
                    <dd>{formatDuration(run.diagnostics?.first_token_latency_ms)}</dd>
                  </div>
                  <div>
                    <dt>Total</dt>
                    <dd>{formatDuration(run.diagnostics?.total_duration_ms)}</dd>
                  </div>
                  <div>
                    <dt>Tokens/sec</dt>
                    <dd>{formatTokensPerSecond(run.diagnostics?.output_tokens_per_second_estimate)}</dd>
                  </div>
                  <div>
                    <dt>Output tokens</dt>
                    <dd>{formatInteger(run.diagnostics?.output_tokens_estimate)}</dd>
                  </div>
                  <div>
                    <dt>Compaction gain</dt>
                    <dd>{formatInteger(run.diagnostics?.compaction_gain_tokens_estimate)}</dd>
                  </div>
                  <div>
                    <dt>Compactions</dt>
                    <dd>{formatInteger(run.diagnostics?.compaction_events_count)}</dd>
                  </div>
                </dl>
                <div className="advanced-run-foot">
                  <span>{formatDate(run.started_at)}</span>
                  <span>{truncateText(run.prompt || "No prompt", 96)}</span>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<Activity size={18} />}
            title="No diagnostics yet"
            description="Run a chat first. Atlas Chat will show timing, compaction gain, and output estimates here."
            actions={
              <button
                className="primary-button compact-button"
                onClick={() => navigate("/workspace")}
                type="button"
              >
                Open Workspace
              </button>
            }
          />
        )}
      </div>
    </section>
  );
}

function formatTemperature(value: number | null | undefined) {
  if (value === undefined) {
    return "Not set";
  }
  if (value === null || Number.isNaN(value)) {
    return "Model setting";
  }
  return value.toFixed(1);
}

function formatDate(value?: string) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return "-";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(date);
}

function formatDuration(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  if (value < 1000) {
    return `${value} ms`;
  }
  return `${(value / 1000).toFixed(2)} s`;
}

function formatTokensPerSecond(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return `${value.toFixed(2)} tok/s`;
}

function formatInteger(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value) || value <= 0) {
    return "-";
  }
  return value.toLocaleString();
}

function truncateText(value: string, maxLength: number) {
  const normalized = value.trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength).trimEnd()}...`;
}
