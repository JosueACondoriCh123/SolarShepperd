import type { ReactNode } from "react";

interface PageHeaderProps {
  kicker: string;
  title: string;
  description: string;
  actions?: ReactNode;
}
export function PageHeader({ kicker, title, description, actions }: PageHeaderProps) {
  return (
    <div className="page-header">
      <div>
        <span className="kicker">{kicker}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}
