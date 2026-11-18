import type { ReactNode } from "react";

export function Kpi({ label, value, hint, accent, className }: { label: string; value: ReactNode; hint?: ReactNode; accent?: string | undefined; className?: string }) {
  return (
    <div className={`rounded-lg border bg-card p-4 ${className ?? ""}`}>
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`num mt-2 text-2xl font-semibold ${accent ?? ""}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export const tableWrap = "overflow-x-auto rounded-lg border bg-card";
export const selectCls =
  "h-9 rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
