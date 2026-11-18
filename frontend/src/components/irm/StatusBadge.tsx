import { cn } from "@/lib/utils";

const MAP: Record<string, string> = {
  OK: "status-ok",
  WATCH: "status-watch",
  AT_RISK: "status-atrisk",
  SHORT: "status-short",
};
export const RISK_STATUSES = ["SHORT", "AT_RISK", "WATCH", "OK"] as const;
export const RISK_RANK: Record<string, number> = { OK: 0, WATCH: 1, AT_RISK: 2, SHORT: 3 };

export function StatusBadge({ status, className }: { status?: string | null; className?: string }) {
  const s = String(status ?? "").toUpperCase();
  return (
    <span className={cn("status-badge", MAP[s] ?? "status-neutral", className)}>
      {s ? s.replace("_", " ") : "—"}
    </span>
  );
}
