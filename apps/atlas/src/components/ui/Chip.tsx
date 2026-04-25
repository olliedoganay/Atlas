import { type ReactNode } from "react";

type ChipIntent = "default" | "accent" | "muted";

export function Chip({ children, intent = "default", title }: { children: ReactNode; intent?: ChipIntent; title?: string }) {
  const className = intent === "accent" ? "chip chip-accent" : intent === "muted" ? "chip chip-muted" : "chip";
  return (
    <span className={className} title={title}>
      {children}
    </span>
  );
}

export function ChipList({ children }: { children: ReactNode }) {
  return <div className="chip-list">{children}</div>;
}
