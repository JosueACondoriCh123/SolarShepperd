import { Lightbulb } from "lucide-react";
import type { ReactNode } from "react";

export function EvidenceNote({ children }: { children: ReactNode }) {
  return (
    <aside className="evidence-note">
      <Lightbulb size={18} aria-hidden="true" />
      <div><strong>What this tells us</strong><p>{children}</p></div>
    </aside>
  );
}
