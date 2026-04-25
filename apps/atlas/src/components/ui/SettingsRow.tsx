import { type ReactNode } from "react";

export function SettingsRow({
  label,
  description,
  children,
  block = false,
  danger = false,
}: {
  label: string;
  description?: string;
  children?: ReactNode;
  block?: boolean;
  danger?: boolean;
}) {
  const className = `atlas-row${block ? " atlas-row-block" : ""}${danger ? " atlas-row-danger" : ""}`;
  return (
    <div className={className}>
      <div className="atlas-row-copy">
        <strong>{label}</strong>
        {description ? <p>{description}</p> : null}
      </div>
      {children ? <div className="atlas-row-control">{children}</div> : null}
    </div>
  );
}
