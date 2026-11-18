import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Progress } from "@/components/ui/progress";
import { PageHeader } from "@/components/irm/PageHeader";
import { Kpi } from "@/components/irm/Kpi";
import { Empty, QueryView } from "@/components/irm/states";
import { RISK_STATUSES, StatusBadge } from "@/components/irm/StatusBadge";
import { asList, endpoints, pick } from "@/lib/api";
import { formatDate, formatNum, humanize } from "@/lib/format";

export const Route = createFileRoute("/_app/overview")({
  head: () => ({
    meta: [
      { title: "Overview — Inventory Risk Monitor" },
      { name: "description", content: "Active projects, risk counts and open purchase orders at a glance." },
      { property: "og:title", content: "Overview — Inventory Risk Monitor" },
      { property: "og:description", content: "Active projects, risk counts and open purchase orders at a glance." },
    ],
  }),
  component: Overview,
});

const ACCENT: Record<string, string> = { OK: "text-ok", WATCH: "text-watch", AT_RISK: "text-atrisk", SHORT: "text-short" };

function countsOf(risk: any): Record<string, number> {
  const c = pick(risk, "totals", "counts", "by_status", "status_counts") ?? risk ?? {};
  if (Array.isArray(c))
    return Object.fromEntries(c.map((r: any) => [String(pick(r, "status")).toUpperCase(), Number(pick(r, "count", "n")) || 0]));
  const out: Record<string, number> = {};
  for (const s of RISK_STATUSES) {
    const v = c[s] ?? c[s.toLowerCase()];
    if (typeof v === "number") out[s] = v;
  }
  return out;
}

function Overview() {
  const dash = useQuery({ queryKey: ["dashboard-summary"], queryFn: endpoints.dashboardSummary });
  const risk = useQuery({ queryKey: ["risk-summary"], queryFn: endpoints.riskSummary });
  const riskByProject = new Map(
    asList(pick(risk.data, "projects") ?? []).map((p: any) => [String(pick(p, "project_id", "id")), p]),
  );

  return (
    <>
      <PageHeader title="Overview" description="Plant-wide material risk snapshot." />
      <section aria-label="Risk counts" className="mb-8">
        <QueryView q={risk}>
          {(r) => {
            const counts = countsOf(r);
            return (
              <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                {RISK_STATUSES.map((s) => (
                  <Kpi key={s} label={humanize(s)} value={formatNum(counts[s] ?? 0)} accent={ACCENT[s]} className="border-2 border-[oklch(0.74_0.12_205)]" />
                ))}
                <Kpi
                  label="Open purchase orders"
                  value={formatNum(pick(dash.data, "open_purchase_orders", "open_po_count", "open_orders") ?? pick(r, "open_purchase_orders", "open_po_count"))}
                  className="border-2 border-[oklch(0.74_0.12_205)]"
                />
              </div>
            );
          }}
        </QueryView>
      </section>

      <section aria-labelledby="active-projects-heading">
        <QueryView q={dash}>
          {(d) => {
            const projects = asList(pick(d, "active_projects", "projects") ?? []);
            return (
              <>
                <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3">
                  <Kpi label="Active projects" value={formatNum(pick(d, "active_project_count") ?? projects.length)} className="border-2 border-[oklch(0.74_0.12_205)]" />
                  <Kpi label="Stock rows at or below reorder point" value={formatNum(pick(d, "stock_rows_available_at_or_below_reorder_point"))} className="border-2 border-[oklch(0.74_0.12_205)]" />
                  <Kpi label="As of" value={formatDate(pick(d, "as_of"))} className="border-2 border-[oklch(0.74_0.12_205)]" />
                </div>
                <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
                  <div>
                    <h2 id="active-projects-heading" className="text-lg font-semibold">Active projects</h2>
                    <p className="text-sm text-muted-foreground">Select a project to view its plan, material requirements, stock and risk.</p>
                  </div>
                  <span className="text-sm text-muted-foreground">{projects.length} project{projects.length === 1 ? "" : "s"}</span>
                </div>
                {projects.length === 0 ? (
                  <Empty>No active projects.</Empty>
                ) : (
                  <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                    {projects.map((p: any, i: number) => {
                      const id = pick(p, "project_id", "id");
                      const code = String(pick(p, "project_code", "code") ?? "");
                      const name = String(pick(p, "name", "project_name", "code") ?? "Project");
                      const riskProject = riskByProject.get(String(id));
                      let progress = Number(pick(p, "schedule_progress_pct", "schedule_progress", "progress_pct", "progress", "percent_complete"));
                      if (Number.isFinite(progress) && progress <= 1 && progress > 0) progress *= 100;
                      const card = (
                        <>
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{code || "Active project"}</p>
                              <h3 className="mt-1 text-base font-semibold leading-snug">{name}</h3>
                              <p className="mt-1 text-sm text-muted-foreground">{humanize(pick(p, "category", "category_code", "project_category"))}</p>
                            </div>
                            <StatusBadge status={pick(riskProject, "worst_status", "worst_risk_status", "risk_status") ?? (risk.isSuccess ? "OK" : undefined)} />
                          </div>
                          <div className="mt-5">
                            <div className="mb-1 flex justify-between text-xs text-muted-foreground">
                              <span>Schedule progress</span>
                              <span>{Number.isFinite(progress) ? String(Math.round(progress)) + "%" : "—"}</span>
                            </div>
                            {Number.isFinite(progress) ? <Progress value={progress} aria-label={name + " schedule progress"} className="h-2" /> : <div className="h-2 rounded bg-muted" />}
                          </div>
                          <div className="mt-4 grid grid-cols-2 gap-3 border-t pt-3 text-sm">
                            <div><p className="text-xs text-muted-foreground">Start</p><p>{formatDate(pick(p, "start_date", "planned_start"))}</p></div>
                            <div><p className="text-xs text-muted-foreground">Target end</p><p>{formatDate(pick(p, "end_date", "planned_end", "finish_date"))}</p></div>
                          </div>
                          <div className="mt-3 flex items-center justify-between border-t pt-3 text-xs text-muted-foreground">
                            <span>{formatNum(pick(p, "requirement_lines"))} material lines</span>
                            <span>View project details <span aria-hidden>→</span></span>
                          </div>
                        </>
                      );
                      const classes = "group rounded-lg border border-sky-400/50 bg-card p-4 shadow-[0_0_12px_rgba(59,130,246,0.18)] transition duration-200 hover:border-sky-300 hover:shadow-[0_0_22px_rgba(59,130,246,0.38)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400";
                      return id !== undefined && id !== null ? (
                        <Link key={id} to="/projects/$projectId" params={{ projectId: String(id) }} className={classes}>
                          {card}
                        </Link>
                      ) : <article key={i} className={classes}>{card}</article>;
                    })}
                  </div>
                )}
              </>
            );
          }}
        </QueryView>
      </section>
    </>
  );
}
