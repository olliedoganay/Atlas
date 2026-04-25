import { type ReactNode } from "react";

type Intent = "ok" | "warn" | "error" | "info" | "neutral";

export function StatusPill({ intent = "neutral", children, dot = true }: { intent?: Intent; children: ReactNode; dot?: boolean }) {
  return (
    <span className={`atlas-pill intent-${intent}`}>
      {dot ? <span className="atlas-pill-dot" aria-hidden="true" /> : null}
      <span>{children}</span>
    </span>
  );
}
