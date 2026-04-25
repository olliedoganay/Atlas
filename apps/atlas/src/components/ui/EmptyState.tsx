import { type ReactNode } from "react";

export function EmptyState({
  icon,
  title,
  description,
  actions,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="atlas-empty">
      {icon ? <div className="atlas-empty-icon" aria-hidden="true">{icon}</div> : null}
      <h4>{title}</h4>
      {description ? <p>{description}</p> : null}
      {actions ? <div className="atlas-empty-actions">{actions}</div> : null}
    </div>
  );
}
