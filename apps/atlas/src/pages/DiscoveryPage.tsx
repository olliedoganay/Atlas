import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Database, Monitor, RefreshCcw, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import { getDiscovery, type DiscoveryReport } from "../lib/api";
import {
  discoveryStatusLabel,
  discoveryStatusTone,
  formatDiscoveryFitLabel,
  formatDiscoveryMemory,
  formatGpuMemoryLabel,
  formatGpuSourceLabel,
  selectPrimaryGpu,
} from "../lib/discoveryUi";

type DiscoveryFilter =
  | "all"
  | "installed"
  | "needs-pull"
  | "chat"
  | "coding"
  | "reasoning"
  | "vision"
  | "embedding";

const FILTER_OPTIONS: Array<{ key: DiscoveryFilter; label: string }> = [
  { key: "all", label: "All" },
  { key: "chat", label: "Chat" },
  { key: "coding", label: "Coding" },
  { key: "reasoning", label: "Reasoning" },
  { key: "vision", label: "Vision" },
  { key: "embedding", label: "Embedding" },
  { key: "installed", label: "Installed" },
  { key: "needs-pull", label: "Needs Pull" },
];

export function DiscoveryPage() {
  const queryClient = useQueryClient();
  const [copiedCommand, setCopiedCommand] = useState("");
  const [activeFilter, setActiveFilter] = useState<DiscoveryFilter>("all");
  const { data, isPending, isFetching, isError, error } = useQuery({
    queryKey: ["discovery"],
    queryFn: getDiscovery,
    staleTime: 10000,
    retry: 1,
    refetchOnWindowFocus: false,
  });

  const recommendedModels = data?.recommended_models ?? [];
  const primaryGpu = data ? selectPrimaryGpu(data.system.gpus) : null;
  const nextStep = data ? selectNextStep(recommendedModels) : null;

  const filteredRecommendations = useMemo(
    () => recommendedModels.filter((item) => matchesDiscoveryFilter(item, activeFilter)),
    [activeFilter, recommendedModels],
  );
  const comfortableCount = recommendedModels.filter(
    (item) => item.fit === "good" || item.fit === "tight",
  ).length;
  const readyCount = recommendedModels.filter(
    (item) => item.installed && item.fit !== "too-large" && item.fit !== "unavailable",
  ).length;
  const needsPullCount = recommendedModels.filter(
    (item) => !item.installed && item.fit !== "too-large" && item.fit !== "unavailable",
  ).length;
  const cautionCount = recommendedModels.filter(
    (item) => item.fit === "cpu-only" || item.fit === "too-large" || item.fit === "unavailable",
  ).length;

  const refreshDiscovery = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["status"] }),
      queryClient.invalidateQueries({ queryKey: ["models"] }),
      queryClient.invalidateQueries({ queryKey: ["discovery"] }),
    ]);
  };

  const copyCommand = async (command: string) => {
    try {
      await navigator.clipboard.writeText(command);
      setCopiedCommand(command);
      window.setTimeout(() => {
        setCopiedCommand((current) => (current === command ? "" : current));
      }, 1400);
    } catch {
      setCopiedCommand("");
    }
  };

  return (
    <section className="page-shell discovery-page">
      <div className="workspace-header">
        <div className="workspace-header-copy">
          <h1>Discovery</h1>
          <p className="workspace-header-summary">
            Choose the next local model from real hardware data instead of guesswork.
          </p>
        </div>
        <div className="workspace-header-controls discovery-header-controls">
          <button className="ghost-button" onClick={() => void refreshDiscovery()} type="button">
            <RefreshCcw size={16} />
            {isFetching ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {isError ? (
        <div className="error-banner">
          Discovery is unavailable right now.{" "}
          {error instanceof Error ? error.message : "Atlas could not load the discovery report."}
        </div>
      ) : null}

      {!data && isPending ? (
        <article className="stack-card discovery-hero">
          <div className="discovery-hero-copy">
            <p className="workspace-section-label">Discovery</p>
            <h2>Building a local hardware snapshot</h2>
            <p>Atlas is checking Ollama, local models, and this machine&apos;s hardware profile.</p>
          </div>
          <span className="status-pill starting">
            <span className="status-dot" />
            Loading
          </span>
        </article>
      ) : null}

      {data ? (
        <>
          <div className="discovery-command-center">
            <article
              className={`stack-card discovery-panel discovery-panel-primary discovery-hero-${discoveryStatusTone(
                data.atlas.status,
              )}`}
            >
              <div className="stack-card-top discovery-decision-head">
                <div>
                  <p className="workspace-section-label">Decision</p>
                  <strong>{nextStep ? (nextStep.installed ? "Use this now" : "Install this next") : "No pick available"}</strong>
                  <p>{data.atlas.summary}</p>
                </div>
                <span className={`status-pill subtle ${discoveryStatusTone(data.atlas.status)}`}>
                  {discoveryStatusLabel(data.atlas.status)}
                </span>
              </div>

              {nextStep ? (
                <article className="discovery-spotlight-card discovery-spotlight-primary">
                  <div className="discovery-spotlight-top">
                    <div>
                      <h2>{nextStep.name}</h2>
                      <p>{nextStep.title}</p>
                    </div>
                    <span className={`status-pill subtle ${fitTone(nextStep.fit)}`}>
                      {formatDiscoveryFitLabel(nextStep.fit)}
                    </span>
                  </div>
                  <div className="discovery-model-tags">
                    {recommendationTags(nextStep).map((tag) => (
                      <span className="discovery-tag" key={`${nextStep.name}-${tag}`}>
                        {tag}
                      </span>
                    ))}
                  </div>
                  <p className="discovery-spotlight-reason">{nextStep.reason}</p>
                  {nextStep.installed ? (
                    <span className="discovery-local-state">
                      {nextStep.configured_default ? "Configured in Atlas" : "Installed locally"}
                    </span>
                  ) : (
                    <div className="discovery-command-row">
                      <button
                        aria-label={`Copy ${nextStep.name} pull command`}
                        className="primary-button compact-button"
                        onClick={() => void copyCommand(nextStep.pull_command)}
                        title="Copy pull command"
                        type="button"
                      >
                        <Copy size={14} />
                        {copiedCommand === nextStep.pull_command ? "Copied" : "Copy"}
                      </button>
                      <code className="discovery-command-inline">{nextStep.pull_command}</code>
                    </div>
                  )}
                </article>
              ) : null}

              <div className="discovery-signal-grid">
                <SignalStat label="Good fits" value={comfortableCount} footnote="Good or tight" />
                <SignalStat label="Ready" value={readyCount} footnote="Installed" />
                <SignalStat label="Pulls" value={needsPullCount} footnote="Worth adding" />
                <SignalStat label="Caution" value={cautionCount} footnote="Slow or unknown" />
              </div>
            </article>

            <article className="stack-card discovery-panel discovery-context-panel">
              <div className="stack-card-top">
                <div>
                  <p className="workspace-section-label">Context</p>
                  <strong>This machine</strong>
                </div>
                <Monitor size={18} />
              </div>

              <div className="discovery-summary-grid">
                <DetailRow label="GPU" value={primaryGpu?.name || "CPU / RAM only"} subvalue={formatGpuMemoryLabel(primaryGpu)} />
                <DetailRow label="RAM" value={formatDiscoveryMemory(data.system.memory.total_gb)} subvalue={data.system.os} />
                <DetailRow label="Chat" value={data.atlas.effective_chat_model || "Not ready"} subvalue={effectiveChatLabel(data.atlas.effective_chat_model_source)} />
                <DetailRow label="Memory" value={data.atlas.configured_embed_model} subvalue={data.atlas.configured_embed_model_installed ? "Installed locally" : "Missing locally"} />
              </div>

              {data.system.gpus.length ? (
                <details className="discovery-details-drawer">
                  <summary>
                    <span>Hardware details</span>
                    <small>{gpuCountLabel(data.system.gpus.length)} | {capitalize(data.system.detection.confidence)} confidence</small>
                  </summary>
                  <div className="discovery-gpu-list">
                    {data.system.gpus.map((gpu) => (
                      <div className="discovery-gpu-row" key={`${gpu.name}-${gpu.kind || "unknown"}`}>
                        <div className="discovery-gpu-copy">
                          <strong>{gpu.name}</strong>
                          <p>{formatGpuMemoryLabel(gpu)}</p>
                        </div>
                        <span className="status-pill subtle muted">{gpuKindLabel(gpu.kind)}</span>
                        <small className="discovery-gpu-source">{formatGpuSourceLabel(gpu)}</small>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}

              {data.atlas.notes.length || data.system.detection.notes.length ? (
                <details className="discovery-details-drawer">
                  <summary>
                    <span>Notes</span>
                    <small>{data.atlas.notes.length + data.system.detection.notes.length}</small>
                  </summary>
                  <div className="discovery-note-list">
                    {[...data.atlas.notes, ...data.system.detection.notes].map((note) => (
                      <p className="muted-text" key={note}>{note}</p>
                    ))}
                  </div>
                </details>
              ) : null}
            </article>
          </div>

          <article className="stack-card discovery-panel discovery-catalog-panel">
            <div className="stack-card-top discovery-catalog-head">
              <div>
                <p className="workspace-section-label">Recommendations</p>
                <strong>Model catalog</strong>
              </div>
              <Sparkles size={18} />
            </div>

            <div className="discovery-filter-bar" role="tablist" aria-label="Recommendation filters">
              {FILTER_OPTIONS.map((filter) => {
                const count = recommendedModels.filter((item) =>
                  matchesDiscoveryFilter(item, filter.key),
                ).length;
                return (
                  <button
                    aria-selected={activeFilter === filter.key}
                    className={`discovery-filter-chip${activeFilter === filter.key ? " active" : ""}`}
                    key={filter.key}
                    onClick={() => setActiveFilter(filter.key)}
                    role="tab"
                    type="button"
                  >
                    <span>{filter.label}</span>
                    <small>{count}</small>
                  </button>
                );
              })}
            </div>

            {filteredRecommendations.length ? (
              <div className="discovery-model-list">
                {filteredRecommendations.map((item) => (
                  <RecommendationRow
                    copiedCommand={copiedCommand}
                    item={item}
                    key={item.name}
                    onCopy={copyCommand}
                  />
                ))}
              </div>
            ) : (
              <div className="discovery-empty-state">
                <Sparkles size={16} />
                <div>
                  <strong>No models match this filter</strong>
                  <p>Try a broader category or refresh the discovery snapshot.</p>
                </div>
              </div>
            )}
          </article>

          <article className="stack-card discovery-panel discovery-inventory-panel">
                <div className="stack-card-top">
                  <div>
                    <p className="workspace-section-label">Installed locally</p>
                    <strong>Current Ollama inventory</strong>
                  </div>
                  <Database size={18} />
                </div>
                <p className="discovery-panel-summary">
                  {data.installed_models.length
                    ? `${data.installed_models.length} model${
                        data.installed_models.length === 1 ? "" : "s"
                      } available to Atlas.`
                    : "No local models detected yet."}
                </p>

                {data.installed_models.length ? (
                  <div className="discovery-installed-grid">
                    {data.installed_models.map((item) => (
                      <div className="discovery-installed-card" key={item.name}>
                        <div className="discovery-installed-main">
                          <strong>{item.name}</strong>
                          <p>{installedRoleLabel(item)}</p>
                        </div>
                        <div className="discovery-model-tags">
                          {installedTags(item).map((tag) => (
                            <span className="discovery-tag" key={`${item.name}-${tag}`}>
                              {tag}
                            </span>
                          ))}
                        </div>
                        <p className="discovery-installed-meta">{installedFootnote(item)}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="discovery-empty-state">
                    <Database size={16} />
                    <div>
                      <strong>No installed models detected</strong>
                      <p>Start Ollama, pull at least one chat model, then refresh this page.</p>
                    </div>
                  </div>
                )}
              </article>
        </>
      ) : null}
    </section>
  );
}

function DetailRow({ label, value, subvalue }: { label: string; value: string; subvalue?: string | null }) {
  return (
    <div className="discovery-detail-row">
      <span className="discovery-detail-label">{label}</span>
      <strong>{value}</strong>
      {subvalue ? <small>{subvalue}</small> : null}
    </div>
  );
}

function SignalStat({ label, value, footnote }: { label: string; value: number; footnote: string }) {
  return (
    <div className="discovery-signal-stat">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{footnote}</small>
    </div>
  );
}

function RecommendationRow({
  item,
  copiedCommand,
  onCopy,
}: {
  item: DiscoveryReport["recommended_models"][number];
  copiedCommand: string;
  onCopy: (command: string) => Promise<void>;
}) {
  return (
    <article className={`discovery-model-row discovery-model-row-${fitTone(item.fit)}`}>
      <div className="discovery-model-headline">
        <h3>{item.name}</h3>
        <p>{item.title}</p>
      </div>

      <div className="discovery-model-fit">
        <span className={`status-pill subtle ${fitTone(item.fit)}`}>
          {formatDiscoveryFitLabel(item.fit)}
        </span>
        <small>
          {useCaseLabel(item.use_case)} | {item.runtime}
        </small>
      </div>

      <p className="discovery-model-reason">{item.reason}</p>

      {item.installed ? (
        <span className="discovery-local-state">
          {item.configured_default ? "Configured" : "Installed"}
        </span>
      ) : (
        <div className="discovery-row-command">
          <button
            aria-label={`Copy ${item.name} pull command`}
            className="ghost-button icon-button"
            onClick={() => void onCopy(item.pull_command)}
            title={copiedCommand === item.pull_command ? "Copied" : "Copy pull command"}
            type="button"
          >
            <Copy size={14} />
          </button>
          <code className="discovery-command-inline">{item.pull_command}</code>
        </div>
      )}
    </article>
  );
}

function installedRoleLabel(item: DiscoveryReport["installed_models"][number]) {
  if (item.atlas_role === "embedding") {
    return "Used for memory retrieval";
  }
  if (item.atlas_role === "vision") {
    return "Chat model with image support";
  }
  if (item.atlas_role === "chat") {
    return "Chat-capable local model";
  }
  return "Installed locally";
}

function installedFootnote(item: DiscoveryReport["installed_models"][number]) {
  const flags = [];
  if (item.configured_chat_model) {
    flags.push("Atlas chat default");
  }
  if (item.configured_embed_model) {
    flags.push("Atlas memory default");
  }
  if (item.supports_images) {
    flags.push("Vision support");
  }
  if (item.supports_reasoning) {
    flags.push("Reasoning support");
  }
  return flags.length ? flags.join(" | ") : "Available locally";
}

function installedTags(item: DiscoveryReport["installed_models"][number]) {
  const tags = [capitalize(item.atlas_role)];
  if (item.configured_chat_model) {
    tags.push("Configured chat");
  }
  if (item.configured_embed_model) {
    tags.push("Configured memory");
  }
  if (item.supports_images) {
    tags.push("Vision");
  }
  if (item.supports_reasoning) {
    tags.push("Reasoning");
  }
  return tags;
}

function fitTone(fit: DiscoveryReport["recommended_models"][number]["fit"]) {
  if (fit === "good") {
    return "online";
  }
  if (fit === "tight") {
    return "starting";
  }
  if (fit === "cpu-only") {
    return "warning";
  }
  return "muted";
}

function matchesDiscoveryFilter(
  item: DiscoveryReport["recommended_models"][number],
  filter: DiscoveryFilter,
) {
  if (filter === "all") {
    return true;
  }
  if (filter === "installed") {
    return item.installed;
  }
  if (filter === "needs-pull") {
    return !item.installed;
  }
  return item.use_case === filter;
}

function selectNextStep(models: DiscoveryReport["recommended_models"]) {
  return (
    models.find((item) => !item.installed && item.configured_default) ??
    models.find(
      (item) =>
        !item.installed &&
        item.fit !== "too-large" &&
        item.fit !== "unavailable" &&
        item.atlas_role === "chat",
    ) ??
    models.find((item) => !item.installed && item.fit !== "too-large" && item.fit !== "unavailable") ??
    models.find((item) => !item.installed) ??
    models[0] ??
    null
  );
}

function recommendationTags(item: DiscoveryReport["recommended_models"][number]) {
  const tags = [useCaseLabel(item.use_case), item.runtime];
  if (item.installed) {
    tags.push("Installed");
  } else {
    tags.push("Needs pull");
  }
  if (item.configured_default) {
    tags.push("Configured in Atlas");
  }
  if (item.supports_images) {
    tags.push("Vision capable");
  }
  return tags;
}

function effectiveChatLabel(source: DiscoveryReport["atlas"]["effective_chat_model_source"]) {
  if (source === "configured") {
    return "Configured default";
  }
  if (source === "fallback") {
    return "Fallback installed model";
  }
  return "No local chat model";
}

function useCaseLabel(value: DiscoveryReport["recommended_models"][number]["use_case"]) {
  if (value === "chat") {
    return "General chat";
  }
  if (value === "coding") {
    return "Coding";
  }
  if (value === "embedding") {
    return "Memory";
  }
  if (value === "vision") {
    return "Vision";
  }
  return "Reasoning";
}

function gpuCountLabel(value: number) {
  if (value === 1) {
    return "1 graphics adapter detected";
  }
  return `${value} graphics adapters detected`;
}

function gpuKindLabel(kind: DiscoveryReport["system"]["gpus"][number]["kind"]) {
  if (kind === "dedicated") {
    return "Dedicated";
  }
  if (kind === "integrated") {
    return "Integrated";
  }
  return "GPU";
}

function capitalize(value: string) {
  if (!value) {
    return "";
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
}
