import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, RefreshCcw } from "lucide-react";
import { useMemo, useState } from "react";

import { getDiscovery, type DiscoveryReport } from "../lib/api";
import {
  discoveryStatusLabel,
  discoveryStatusTone,
  formatDiscoveryFitLabel,
  formatDiscoveryMemory,
  formatGpuMemoryLabel,
  selectPrimaryGpu,
} from "../lib/discoveryUi";

type DiscoveryFilter = "needs-pull" | "installed" | "all";

const FILTER_OPTIONS: Array<{ key: DiscoveryFilter; label: string }> = [
  { key: "needs-pull", label: "Pull candidates" },
  { key: "installed", label: "Installed" },
  { key: "all", label: "All" },
];

export function DiscoveryPage() {
  const queryClient = useQueryClient();
  const [copiedCommand, setCopiedCommand] = useState("");
  const [activeFilter, setActiveFilter] = useState<DiscoveryFilter>("needs-pull");
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
  const installedCount = recommendedModels.filter((item) => item.installed).length;
  const needsPullCount = recommendedModels.length - installedCount;
  const sortedRecommendations = useMemo(
    () => sortRecommendations(recommendedModels, nextStep?.name),
    [recommendedModels, nextStep?.name],
  );
  const filteredRecommendations = useMemo(
    () => sortedRecommendations.filter((item) => matchesDiscoveryFilter(item, activeFilter)),
    [activeFilter, sortedRecommendations],
  );

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
      <div className="workspace-header discovery-page-header">
        <div className="workspace-header-copy">
          <h1>Discovery</h1>
          <p className="workspace-header-summary">Find a practical local model for this machine.</p>
        </div>
        <div className="workspace-header-controls discovery-header-controls">
          <button
            aria-label="Refresh discovery"
            className="ghost-button icon-button discovery-icon-action"
            onClick={() => void refreshDiscovery()}
            title={isFetching ? "Refreshing" : "Refresh"}
            type="button"
          >
            <RefreshCcw size={15} />
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
        <div className="discovery-loading-line">
          <span className="status-pill starting">
            <span className="status-dot" />
            Loading
          </span>
          <p>Checking Ollama, local models, and hardware.</p>
        </div>
      ) : null}

      {data ? (
        <div className="discovery-stack">
          <div className={`discovery-facts discovery-facts-${discoveryStatusTone(data.atlas.status)}`}>
            <Fact label="Status" value={discoveryStatusLabel(data.atlas.status)} />
            <Fact label="GPU" value={primaryGpu ? `${shortGpuName(primaryGpu.name)} · ${formatGpuMemoryLabel(primaryGpu)}` : "CPU only"} />
            <Fact label="RAM" value={`${formatDiscoveryMemory(data.system.memory.total_gb)} · ${data.system.os}`} />
            <Fact label="Models" value={`${installedCount} installed · ${needsPullCount} pull candidates`} />
          </div>

          <section className="discovery-recommendation" aria-label="Primary recommendation">
            <div className="discovery-recommendation-copy">
              <p className="workspace-section-label">{nextStep?.installed ? "Use now" : "Install next"}</p>
              <h2>{nextStep ? nextStep.name : "No recommendation"}</h2>
              <p>
                {nextStep
                  ? `${nextStep.title} · ${formatDiscoveryFitLabel(nextStep.fit)} · ${roleRuntimeLabel(nextStep)}`
                  : data.atlas.summary}
              </p>
            </div>

            {nextStep ? (
              <div className="discovery-recommendation-action">
                {nextStep.installed ? (
                  <span className="discovery-ready-text">
                    <Check size={14} />
                    Installed
                  </span>
                ) : (
                  <button
                    aria-label={`Copy ${nextStep.name} pull command`}
                    className="ghost-button icon-button discovery-copy-action"
                    onClick={() => void copyCommand(nextStep.pull_command)}
                    title={copiedCommand === nextStep.pull_command ? "Copied" : nextStep.pull_command}
                    type="button"
                  >
                    {copiedCommand === nextStep.pull_command ? <Check size={14} /> : <Copy size={14} />}
                  </button>
                )}
              </div>
            ) : null}
          </section>

          <section className="discovery-model-picker" aria-label="Model recommendations">
            <div className="discovery-picker-head">
              <div>
                <p className="workspace-section-label">Models</p>
                <h2>{filterHeading(activeFilter)}</h2>
              </div>
              <span>{filteredRecommendations.length}</span>
            </div>

            <div className="discovery-filter-tabs" role="tablist" aria-label="Recommendation filters">
              {FILTER_OPTIONS.map((filter) => {
                const count = recommendedModels.filter((item) =>
                  matchesDiscoveryFilter(item, filter.key),
                ).length;
                return (
                  <button
                    aria-selected={activeFilter === filter.key}
                    className={`discovery-filter-tab${activeFilter === filter.key ? " active" : ""}`}
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
                <strong>No models in this view</strong>
              </div>
            )}
          </section>
        </div>
      ) : null}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <span className="discovery-fact">
      <span>{label}</span>
      <strong>{value}</strong>
    </span>
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
    <article className="discovery-model-row">
      <div className="discovery-model-name">
        <h3>{item.name}</h3>
        <p>{item.title}</p>
      </div>

      <span className={`discovery-fit-label ${fitTone(item.fit)}`}>
        {formatDiscoveryFitLabel(item.fit)}
      </span>

      <span className="discovery-model-role">{roleRuntimeLabel(item)}</span>

      <div className="discovery-model-action">
        {item.installed ? (
          <span className="discovery-ready-text">
            <Check size={14} />
            Installed
          </span>
        ) : (
          <button
            aria-label={`Copy ${item.name} pull command`}
            className="ghost-button icon-button discovery-copy-action"
            onClick={() => void onCopy(item.pull_command)}
            title={copiedCommand === item.pull_command ? "Copied" : item.pull_command}
            type="button"
          >
            {copiedCommand === item.pull_command ? <Check size={14} /> : <Copy size={14} />}
          </button>
        )}
      </div>
    </article>
  );
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
  return !item.installed;
}

function sortRecommendations(
  models: DiscoveryReport["recommended_models"],
  primaryName: string | undefined,
) {
  return [...models].sort((left, right) => {
    const leftPrimary = left.name === primaryName ? 0 : 1;
    const rightPrimary = right.name === primaryName ? 0 : 1;
    if (leftPrimary !== rightPrimary) {
      return leftPrimary - rightPrimary;
    }

    const leftInstall = left.installed ? 1 : 0;
    const rightInstall = right.installed ? 1 : 0;
    if (leftInstall !== rightInstall) {
      return leftInstall - rightInstall;
    }

    const leftFit = fitRank(left.fit);
    const rightFit = fitRank(right.fit);
    if (leftFit !== rightFit) {
      return leftFit - rightFit;
    }

    return left.name.localeCompare(right.name);
  });
}

function selectNextStep(models: DiscoveryReport["recommended_models"]) {
  return (
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

function filterHeading(filter: DiscoveryFilter) {
  if (filter === "installed") {
    return "Installed models";
  }
  if (filter === "all") {
    return "Catalog";
  }
  return "Pull candidates";
}

function roleRuntimeLabel(item: DiscoveryReport["recommended_models"][number]) {
  return `${useCaseLabel(item.use_case)} · ${item.runtime}`;
}

function useCaseLabel(value: DiscoveryReport["recommended_models"][number]["use_case"]) {
  if (value === "chat") {
    return "Chat";
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

function fitRank(fit: DiscoveryReport["recommended_models"][number]["fit"]) {
  if (fit === "good") {
    return 0;
  }
  if (fit === "tight") {
    return 1;
  }
  if (fit === "cpu-only") {
    return 2;
  }
  if (fit === "too-large") {
    return 3;
  }
  return 4;
}

function shortGpuName(name: string) {
  return name.replace(/^NVIDIA\s+/i, "").replace(/\s+Laptop GPU$/i, "");
}
