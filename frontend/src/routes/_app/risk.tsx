import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Fragment, useMemo, useState } from "react";
import { ShortageActions } from "@/components/irm/ShortageActions";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/irm/PageHeader";
import { selectCls, tableWrap } from "@/components/irm/Kpi";
import { Empty, QueryView } from "@/components/irm/states";
import { RISK_RANK, RISK_STATUSES, StatusBadge } from "@/components/irm/StatusBadge";
import { asList, endpoints, pick } from "@/lib/api";
import { formatDate, formatNum, humanize } from "@/lib/format";

export const Route = createFileRoute("/_app/risk")({
  head: () => ({
    meta: [
      { title: "Shortage risk — Inventory Risk Monitor" },
      { name: "description", content: "Material shortages by project with urgency and need-by dates." },
      { property: "og:title", content: "Shortage risk — Inventory Risk Monitor" },
      { property: "og:description", content: "Material shortages by project with urgency and need-by dates." },
    ],
  }),
  component: Risk,
});

const projectOf = (r: any) => String(pick(r, "project_name", "project.name", "project_code", "project_id") ?? "—");
const materialOf = (r: any) => {
  const code = pick(r, "material_code", "material.code");
  const name = pick(r, "material_name", "material.name", "material_description");
  return [code, name].filter(Boolean).join(" · ") || String(pick(r, "material_id") ?? "—");
};

function Risk() {
  const q = useQuery({ queryKey: ["shortages"], queryFn: endpoints.shortages });
  const [status, setStatus] = useState("");
  const [project, setProject] = useState("");
  const [open, setOpen] = useState<Set<number>>(new Set());

  return (
    <>
      <PageHeader title="Shortage risk" description="Requirements not fully covered by stock and open orders (OK excluded)." />
      <QueryView q={q}>
        {(data) => <RiskTable rows={asList(data)} {...{ status, setStatus, project, setProject, open, setOpen }} />}
      </QueryView>
    </>
  );
}

function RiskTable({ rows, status, setStatus, project, setProject, open, setOpen }: any) {
  const projects = useMemo(() => [...new Set(rows.map(projectOf))].sort() as string[], [rows]);
  const filtered = rows.filter(
    (r: any) => (!status || String(pick(r, "status")).toUpperCase() === status) && (!project || projectOf(r) === project),
  );
  const toggle = (i: number) => {
    const n = new Set(open);
    n.has(i) ? n.delete(i) : n.add(i);
    setOpen(n);
  };
  return (
    <>
      <div className="mb-4 flex flex-wrap gap-3">
        <label className="flex items-center gap-2 text-sm">
          Status
          <select className={selectCls} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {RISK_STATUSES.filter((s) => s !== "OK").map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          Project
          <select className={selectCls} value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="">All</option>
            {projects.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <span className="self-center text-sm text-muted-foreground">{filtered.length} of {rows.length}</span>
      </div>
      {filtered.length === 0 ? (
        <Empty>{rows.length === 0 ? "No shortages at risk. All requirements are covered." : "No rows match these filters."}</Empty>
      ) : (
        <div className={tableWrap}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8"><span className="sr-only">Expand</span></TableHead>
                <TableHead>Status</TableHead><TableHead>Urgency</TableHead><TableHead>Project</TableHead>
                <TableHead>Material</TableHead><TableHead>Need by</TableHead><TableHead className="text-right">Days until need</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...filtered]
                .sort((a: any, b: any) => (RISK_RANK[String(pick(b, "status")).toUpperCase()] ?? 0) - (RISK_RANK[String(pick(a, "status")).toUpperCase()] ?? 0))
                .map((r: any, i: number) => {
                  const isOpen = open.has(i);
                  const orders = pick(r, "orders_used", "purchase_orders_used", "covering_orders");
                  return (
                    <Fragment key={i}>
                      <TableRow className="cursor-pointer" onClick={() => toggle(i)}>
                        <TableCell>
                          <button
                            type="button"
                            aria-expanded={isOpen}
                            aria-label={isOpen ? "Collapse details" : "Expand details"}
                            onClick={(e) => { e.stopPropagation(); toggle(i); }}
                            className="rounded p-1 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                          </button>
                        </TableCell>
                        <TableCell><StatusBadge status={pick(r, "status")} /></TableCell>
                        <TableCell>{humanize(pick(r, "urgency", "urgency_level"))}</TableCell>
                        <TableCell>{projectOf(r)}</TableCell>
                        <TableCell>{materialOf(r)}</TableCell>
                        <TableCell>{formatDate(pick(r, "need_by_date", "need_by", "required_date"))}</TableCell>
                        <TableCell className="num text-right">{formatNum(pick(r, "days_until_need", "days_to_need"))}</TableCell>
                      </TableRow>
                      {isOpen && (
                        <TableRow className="bg-muted/40 hover:bg-muted/40">
                          <TableCell />
                          <TableCell colSpan={6} className="space-y-2 py-4 text-sm">
                            <p><span className="text-muted-foreground">Explanation: </span>{pick(r, "explanation", "reason", "message") ?? "—"}</p>
                            <p>
                              <span className="text-muted-foreground">Orders used: </span>
                              {Array.isArray(orders) ? (orders.length ? orders.map((o: any) => (typeof o === "object" ? pick(o, "po_number", "number", "id") : o)).join(", ") : "None") : (orders ?? "—")}
                            </p>
                            <p><span className="text-muted-foreground">Latest order date: </span>{formatDate(pick(r, "latest_order_date", "latest_po_date", "last_order_date"))}</p>
                            <ShortageActions row={r} />
                            </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  );
                })}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}
