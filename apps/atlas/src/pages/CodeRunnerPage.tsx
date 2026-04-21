import { getCurrentWindow } from "@tauri-apps/api/window";
import { Play, Square, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import {
  execCode,
  getRunnerStatus,
  stopRunnerRun,
  streamRunnerRun,
  type RunnerEvent,
  type RunnerStatus,
} from "../lib/api";
import { consumePendingRun, isClientLanguage } from "../lib/runner";

type OutputLine = {
  stream: "stdout" | "stderr";
  text: string;
};

type Phase = "loading" | "docker-down" | "running" | "finished" | "error" | "idle";

export function CodeRunnerPage() {
  const { token = "" } = useParams();
  const [phase, setPhase] = useState<Phase>("loading");
  const [language, setLanguage] = useState<string>("");
  const [code, setCode] = useState<string>("");
  const [runId, setRunId] = useState<string | null>(null);
  const [output, setOutput] = useState<OutputLine[]>([]);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const [durationMs, setDurationMs] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [dockerReason, setDockerReason] = useState<string>("");
  const [vncUrl, setVncUrl] = useState<string | null>(null);
  const streamDisposer = useRef<(() => void) | null>(null);
  const outputRef = useRef<HTMLDivElement | null>(null);
  const currentRunId = useRef<string | null>(null);

  const clientLang = useMemo(() => (language ? isClientLanguage(language) : false), [language]);

  useEffect(() => {
    if (!token) {
      setPhase("error");
      setErrorMessage("Runner token missing from URL.");
      return;
    }
    const payload = consumePendingRun(token);
    if (!payload) {
      setPhase("error");
      setErrorMessage("This run window lost its payload. Close and try again.");
      return;
    }
    setLanguage(payload.language);
    setCode(payload.code);
  }, [token]);

  useEffect(() => {
    if (!language) {
      return;
    }
    void getCurrentWindow()
      .setTitle(`Atlas Run · ${language}`)
      .catch(() => undefined);
  }, [language]);

  const scrollToEnd = useCallback(() => {
    requestAnimationFrame(() => {
      const node = outputRef.current;
      if (node) {
        node.scrollTop = node.scrollHeight;
      }
    });
  }, []);

  const handleEvent = useCallback(
    (event: RunnerEvent) => {
      if (event.type === "output") {
        setOutput((prev) => [...prev, { stream: event.stream, text: event.chunk }]);
        scrollToEnd();
      } else if (event.type === "exit") {
        setExitCode(event.code);
        setDurationMs(event.duration_ms);
        setPhase("finished");
      }
    },
    [scrollToEnd],
  );

  const beginServerRun = useCallback(async () => {
    if (!language || !code) {
      return;
    }
    setPhase("loading");
    setOutput([]);
    setExitCode(null);
    setDurationMs(null);
    setErrorMessage(null);
    setVncUrl(null);

    let status: RunnerStatus;
    try {
      status = await getRunnerStatus();
    } catch (error) {
      setPhase("error");
      setErrorMessage(error instanceof Error ? error.message : "Failed to contact backend.");
      return;
    }

    if (!status.available) {
      setPhase("docker-down");
      setDockerReason(status.reason ?? "Docker Desktop is not running.");
      return;
    }

    try {
      const started = await execCode(language, code);
      currentRunId.current = started.run_id;
      setRunId(started.run_id);
      setVncUrl(started.vnc_url ?? null);
      setPhase("running");
      streamDisposer.current?.();
      streamDisposer.current = streamRunnerRun(started.run_id, handleEvent, (message) => {
        setErrorMessage(message);
      });
    } catch (error) {
      setPhase("error");
      setErrorMessage(error instanceof Error ? error.message : "Failed to start run.");
    }
  }, [language, code, handleEvent]);

  useEffect(() => {
    if (!language) {
      return;
    }
    if (clientLang) {
      setPhase("idle");
      return;
    }
    void beginServerRun();
  }, [language, clientLang, beginServerRun]);

  useEffect(() => {
    return () => {
      streamDisposer.current?.();
      streamDisposer.current = null;
      const id = currentRunId.current;
      if (id) {
        void stopRunnerRun(id).catch(() => undefined);
      }
    };
  }, []);

  useEffect(() => {
    let unlisten: (() => void) | null = null;
    void getCurrentWindow()
      .onCloseRequested(() => {
        streamDisposer.current?.();
        streamDisposer.current = null;
        const id = currentRunId.current;
        if (id) {
          void stopRunnerRun(id).catch(() => undefined);
        }
      })
      .then((fn) => {
        unlisten = fn;
      })
      .catch(() => undefined);
    return () => {
      unlisten?.();
    };
  }, []);

  const stopRun = useCallback(async () => {
    const id = currentRunId.current;
    if (!id) {
      return;
    }
    try {
      await stopRunnerRun(id);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to stop run.");
    }
  }, []);

  const rerun = useCallback(() => {
    currentRunId.current = null;
    setRunId(null);
    void beginServerRun();
  }, [beginServerRun]);

  if (!language) {
    return (
      <div className="runner-shell">
        <div className="runner-center">
          <p>{errorMessage ?? "Preparing run…"}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="runner-shell">
      <header className="runner-header">
        <div className="runner-title">
          <span className="runner-lang-pill">{language}</span>
          <RunnerStatusBadge phase={phase} exitCode={exitCode} />
        </div>
        <div className="runner-actions">
          {phase === "running" ? (
            <button className="ghost-button compact-button runner-stop" onClick={() => void stopRun()} type="button">
              <Square size={14} /> Stop
            </button>
          ) : null}
          {clientLang || phase === "finished" || phase === "error" || phase === "docker-down" ? (
            <button className="ghost-button compact-button" onClick={() => rerun()} type="button">
              {clientLang ? <Play size={14} /> : <RotateCcw size={14} />}
              {clientLang ? "Reload" : "Rerun"}
            </button>
          ) : null}
        </div>
      </header>

      <main className={`runner-body${vncUrl ? " with-vnc" : ""}`}>
        {clientLang ? (
          <ClientPreview code={code} />
        ) : phase === "docker-down" ? (
          <DockerDownPanel reason={dockerReason} onRetry={rerun} />
        ) : vncUrl ? (
          <>
            <VncPane url={vncUrl} />
            <ServerOutputPanel
              errorMessage={errorMessage}
              output={output}
              outputRef={outputRef}
              phase={phase}
            />
          </>
        ) : (
          <ServerOutputPanel
            errorMessage={errorMessage}
            output={output}
            outputRef={outputRef}
            phase={phase}
          />
        )}
      </main>

      <footer className="runner-footer">
        <span className="runner-meta">
          {runId ? `Run ${runId.slice(0, 8)}` : clientLang ? "Client sandbox" : "Awaiting Docker"}
        </span>
        {durationMs != null ? <span className="runner-meta">{(durationMs / 1000).toFixed(2)}s</span> : null}
        {exitCode != null ? <span className="runner-meta">exit {exitCode}</span> : null}
      </footer>
    </div>
  );
}

function RunnerStatusBadge({ phase, exitCode }: { phase: Phase; exitCode: number | null }) {
  if (phase === "running") {
    return <span className="runner-status running">Running</span>;
  }
  if (phase === "loading") {
    return <span className="runner-status pending">Starting…</span>;
  }
  if (phase === "finished") {
    const ok = exitCode === 0;
    return <span className={`runner-status ${ok ? "ok" : "fail"}`}>{ok ? "Done" : `Exit ${exitCode}`}</span>;
  }
  if (phase === "error") {
    return <span className="runner-status fail">Error</span>;
  }
  if (phase === "docker-down") {
    return <span className="runner-status fail">Docker down</span>;
  }
  return <span className="runner-status pending">Ready</span>;
}

function ServerOutputPanel({
  errorMessage,
  output,
  outputRef,
  phase,
}: {
  errorMessage: string | null;
  output: OutputLine[];
  outputRef: React.MutableRefObject<HTMLDivElement | null>;
  phase: Phase;
}) {
  return (
    <div className="runner-output" ref={outputRef}>
      {errorMessage ? <div className="runner-line stderr">{errorMessage}</div> : null}
      {output.length === 0 && phase !== "error" ? (
        <div className="runner-placeholder">{phase === "running" ? "Waiting for output…" : "No output."}</div>
      ) : null}
      {output.map((line, idx) => (
        <div className={`runner-line ${line.stream}`} key={idx}>
          {line.text.replace(/\r$/, "")}
        </div>
      ))}
    </div>
  );
}

function DockerDownPanel({ reason, onRetry }: { reason: string; onRetry: () => void }) {
  return (
    <div className="runner-center">
      <h2>Docker Desktop isn't running</h2>
      <p>{reason}</p>
      <button className="primary-button" onClick={() => onRetry()} type="button">
        Retry
      </button>
    </div>
  );
}

function ClientPreview({ code }: { code: string }) {
  return (
    <iframe
      className="runner-iframe"
      sandbox="allow-scripts allow-forms allow-modals allow-popups allow-pointer-lock"
      srcDoc={code}
      title="Atlas runner preview"
    />
  );
}

function VncPane({ url }: { url: string }) {
  const [ready, setReady] = useState(false);
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    setReady(false);
    setSrc(null);
    let cancelled = false;
    const start = Date.now();
    const deadlineMs = 45_000;
    const attempt = async () => {
      try {
        await fetch(url, { method: "GET", mode: "no-cors" });
        if (!cancelled) {
          setSrc(url);
          setReady(true);
        }
      } catch {
        if (!cancelled && Date.now() - start < deadlineMs) {
          setTimeout(attempt, 500);
        } else if (!cancelled) {
          setSrc(url);
          setReady(true);
        }
      }
    };
    void attempt();
    return () => {
      cancelled = true;
    };
  }, [url]);

  return (
    <div className="runner-vnc">
      {ready && src ? (
        <iframe className="runner-vnc-frame" src={src} title="Atlas GUI preview" />
      ) : (
        <div className="runner-vnc-placeholder">Starting GUI…</div>
      )}
    </div>
  );
}
