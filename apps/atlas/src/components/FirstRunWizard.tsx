import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Check, ExternalLink } from "lucide-react";

import { createUser } from "../lib/api";

type StepState = "active" | "pending" | "done";

export function FirstRunWizard({
  ollamaOnline,
  hasLocalModels,
  onProfileCreated,
  onDismiss,
}: {
  ollamaOnline: boolean;
  hasLocalModels: boolean;
  onProfileCreated: (userId: string) => Promise<void> | void;
  onDismiss: () => void;
}) {
  const [profileName, setProfileName] = useState("");
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileCreated, setProfileCreated] = useState(false);
  const navigate = useNavigate();

  const createMutation = useMutation({
    mutationFn: async () => createUser(profileName.trim()),
    onSuccess: async (user) => {
      setProfileCreated(true);
      setProfileError(null);
      await onProfileCreated(user.user_id);
    },
    onError: (error) => {
      setProfileError(error instanceof Error && error.message ? error.message : "Could not create profile.");
    },
  });

  const step1: StepState = profileCreated ? "done" : "active";
  const step2: StepState = !profileCreated ? "pending" : ollamaOnline ? "done" : "active";
  const step3: StepState = !profileCreated || !ollamaOnline ? "pending" : hasLocalModels ? "done" : "active";

  const allDone = profileCreated && ollamaOnline && hasLocalModels;

  return (
    <div className="wizard-overlay" role="dialog" aria-modal="true" aria-labelledby="wizard-title">
      <div className="wizard-card">
        <div className="wizard-header">
          <h2 id="wizard-title">Welcome to Atlas Chat</h2>
          <p>Three quick steps and you're chatting with a local model.</p>
        </div>

        <div className={`wizard-step ${step1}`}>
          <div className="wizard-step-head">
            <span className="wizard-step-num">{step1 === "done" ? <Check size={14} /> : "1"}</span>
            <h3>Create a profile</h3>
          </div>
          <div className="wizard-step-body">
            <span>Profiles separate your chats and memories. You can have several.</span>
            {!profileCreated ? (
              <div className="wizard-form">
                <input
                  aria-label="Profile name"
                  className="text-input"
                  onChange={(event) => setProfileName(event.currentTarget.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && profileName.trim() && !createMutation.isPending) {
                      createMutation.mutate();
                    }
                  }}
                  placeholder="my_profile"
                  value={profileName}
                />
                <button
                  className="primary-button compact-button"
                  disabled={!profileName.trim() || createMutation.isPending}
                  onClick={() => createMutation.mutate()}
                  type="button"
                >
                  {createMutation.isPending ? "Creating..." : "Create"}
                </button>
              </div>
            ) : (
              <span style={{ color: "var(--success)" }}>Profile "{profileName.trim()}" created.</span>
            )}
            {profileError ? <span style={{ color: "var(--danger)" }}>{profileError}</span> : null}
          </div>
        </div>

        <div className={`wizard-step ${step2}`}>
          <div className="wizard-step-head">
            <span className="wizard-step-num">{step2 === "done" ? <Check size={14} /> : "2"}</span>
            <h3>Connect Ollama</h3>
          </div>
          <div className="wizard-step-body">
            <span>
              Atlas Chat needs Ollama running on this machine.{" "}
              <strong style={{ color: ollamaOnline ? "var(--success)" : "var(--danger)" }}>
                {ollamaOnline ? "Connected" : "Not running"}
              </strong>
            </span>
            {!ollamaOnline ? (
              <div className="wizard-form">
                <a
                  className="ghost-button compact-button"
                  href="https://ollama.com/download"
                  rel="noreferrer"
                  target="_blank"
                >
                  <ExternalLink size={14} />
                  Download Ollama
                </a>
              </div>
            ) : null}
          </div>
        </div>

        <div className={`wizard-step ${step3}`}>
          <div className="wizard-step-head">
            <span className="wizard-step-num">{step3 === "done" ? <Check size={14} /> : "3"}</span>
            <h3>Install a model</h3>
          </div>
          <div className="wizard-step-body">
            <span>Pick a model that fits your machine. Discovery shows recommendations.</span>
            <div className="wizard-form">
              <button
                className="primary-button compact-button"
                disabled={!profileCreated || !ollamaOnline}
                onClick={() => {
                  navigate("/discovery");
                  onDismiss();
                }}
                type="button"
              >
                Open Discovery
              </button>
            </div>
          </div>
        </div>

        <div className="wizard-footer">
          <button className="ghost-button compact-button" onClick={onDismiss} type="button">
            Skip for now
          </button>
          {allDone ? (
            <button
              className="primary-button compact-button"
              onClick={onDismiss}
              type="button"
            >
              Start chatting
            </button>
          ) : (
            <span style={{ color: "var(--muted)", fontSize: "var(--text-sm)" }}>
              Complete the steps above to begin.
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
