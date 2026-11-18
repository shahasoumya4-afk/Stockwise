import { createFileRoute, Link } from "@tanstack/react-router";
import { useQueries, useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/irm/PageHeader";
import { Empty, QueryView } from "@/components/irm/states";
import { StatusBadge } from "@/components/irm/StatusBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { tableWrap } from "@/components/irm/Kpi";
import { asList, endpoints, pick } from "@/lib/api";
import { formatDate, formatNum, humanize } from "@/lib/format";

export const Route = createFileRoute("/_app/projects/$projectId")({
  head: () => ({
    meta: [
      { title: "Project details — Inventory Risk Monitor" },
      { name: "description", content: "Project plan, material requirements, stock and shortage risk." },
    ],
  }),
  component: ProjectDetails,
});

function ProjectDetails() {
  const { projectId: rawId } = Route.useParams();
  const projectId = Number(rawId);
  const validId = Number.isInteger(projectId) && projectId > 0;
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => endpoints.project(projectId),
    enabled: validId,
  });
  const requirements = useQuery({
    queryKey: ["project-requirements", projectId],
    queryFn: () => endpoints.projectRequirements(projectId),
    enabled: validId,
  });
  const risk = useQuery({
    queryKey: ["project-risk", projectId],
    queryFn: () => endpoints.projectRisk(projectId),
    enabled: validId,
  });

  if (!validId) return <Empty>Invalid project ID.</Empty>;

  return (
    <QueryView q={project}>
      {(p) => (
        <>
          <PageHeader
            title={String(pick(p, "name", "project_code") ?? "Project details")}
            description={String(pick(p, "project_code") ?? "")}
          >
            <Link to="/overview" className="rounded-md border px-3 py-2 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              Back to overview
            </Link>
          </PageHeader>

          <section className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Project summary">
            <Info label="Status" value={humanize(p.status)} />
            <Info label="Category" value={p.category ?? "—"} />
            <Info label="Project lead" value={p.project_head ?? "—"} />
            <Info label="Department" value={p.department ?? "—"} />
            <Info label="Start date" value={formatDate(p.start_date)} />
            <Info label="Target end" value={formatDate(p.end_date)} />
            <Info label="Scale" value={scaleOf(p)} />
            <Info label="Plan versions" value={formatNum(asList(p.requirement_versions).length)} />
          </section>

          <section className="mb-8 rounded-lg border bg-card p-4">
            <h2 className="mb-2 text-base font-semibold">Project plan</h2>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
              {p.idea_description || "No project description has been recorded."}
            </p>
          </section>

          <section aria-labelledby="materials-heading">
            <div className="mb-3">
              <h2 id="materials-heading" className="text-lg font-semibold">Material plan, stock and risk</h2>
              <p className="text-sm text-muted-foreground">Requirement quantities come from the latest approved plan. Stock shows current on-hand, reserved and available quantities across warehouses.</p>
            </div>
            <QueryView q={requirements}>
              {(requirementData) => (
                <QueryView q={risk}>
                  {(riskData) => (
                    <RequirementTable
                      lines={asList(pick(requirementData, "lines"))}
                      riskRows={asList(pick(riskData, "items"))}
                    />
                  )}
                </QueryView>
              )}
            </QueryView>
          </section>
        </>
      )}
    </QueryView>
  );
}

function RequirementTable({ lines, riskRows }: { lines: any[]; riskRows: any[] }) {
  const materialIds = [...new Set(lines.map((line) => Number(pick(line, "material_id"))).filter((id) => Number.isInteger(id) && id > 0))];
  const inventoryQueries = useQueries({
    queries: materialIds.map((id) => ({
      queryKey: ["inventory", "material", id],
      queryFn: () => endpoints.inventoryByMaterial(id),
    })),
  });
  const stockByMaterial = new Map(materialIds.map((id, index) => [id, inventoryQueries[index]]));
  const riskByLine = new Map(riskRows.map((row) => [String(pick(row, "requirement_line_id")), row]));

  if (lines.length === 0) return <Empty>No approved material requirement plan is available for this project yet.</Empty>;

  return (
    <div className={tableWrap}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Material</TableHead>
            <TableHead>Predicted</TableHead>
            <TableHead>Proposed</TableHead>
            <TableHead>Approved</TableHead>
            <TableHead>Consumed</TableHead>
            <TableHead>Reserved</TableHead>
            <TableHead>Still to allocate</TableHead>
            <TableHead>Need by</TableHead>
            <TableHead>Risk</TableHead>
            <TableHead>Current stock by warehouse</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {lines.map((line) => {
            const materialId = Number(pick(line, "material_id"));
            const stockQuery = stockByMaterial.get(materialId);
            const stockRows = asList(pick(stockQuery?.data, "items"));
            const riskRow = riskByLine.get(String(pick(line, "requirement_line_id")));
            const approved = Number(pick(line, "approved_quantity")) || 0;
            const consumed = Number(pick(line, "consumed_quantity")) || 0;
            const reserved = Number(pick(line, "allocated_quantity")) || 0;
            const remaining = Math.max(0, approved - consumed - reserved);
            const code = pick(line, "material_code");
            const name = pick(line, "material_name");
            return (
              <TableRow key={String(pick(line, "requirement_line_id"))}>
                <TableCell className="min-w-48">
                  <p className="font-medium">{code ?? "Material"}{name ? " · " + name : ""}</p>
                  <p className="text-xs text-muted-foreground">{pick(line, "uom_code") ?? ""}</p>
                </TableCell>
                <TableCell className="num">{formatNum(pick(line, "predicted_quantity"))}</TableCell>
                <TableCell className="num">{formatNum(pick(line, "proposed_quantity"))}</TableCell>
                <TableCell className="num">{formatNum(approved)}</TableCell>
                <TableCell className="num">{formatNum(consumed)}</TableCell>
                <TableCell className="num">{formatNum(reserved)}</TableCell>
                <TableCell className="num">{formatNum(remaining)}</TableCell>
                <TableCell>{formatDate(pick(line, "need_by_date"))}</TableCell>
                <TableCell className="min-w-40"><StatusBadge status={pick(riskRow, "status") ?? (remaining === 0 ? "OK" : undefined)} />{riskRow?.explanation && <p className="mt-1 max-w-64 text-xs text-muted-foreground">{riskRow.explanation}</p>}{riskRow?.urgency && <p className="mt-1 text-xs text-muted-foreground">Urgency: {humanize(riskRow.urgency)}</p>}</TableCell>
                <TableCell className="min-w-56">
                  {stockQuery?.isPending ? <span className="text-xs text-muted-foreground">Loading stock…</span> :
                    stockQuery?.isError ? <span className="text-xs text-destructive">Stock unavailable</span> :
                    stockRows.length === 0 ? <span className="text-xs text-muted-foreground">No stock rows</span> :
                    <div className="space-y-1">
                      {stockRows.map((stock: any) => (
                        <p key={String(pick(stock, "warehouse_id", "inventory_id"))} className="text-xs">
                          <span className="font-medium">{pick(stock, "warehouse") ?? "Warehouse"}:</span>{" "}
                          on hand {formatNum(pick(stock, "on_hand_quantity"))}, reserved {formatNum(pick(stock, "reserved_quantity"))}, available {formatNum(pick(stock, "available_quantity"))}
                        </p>
                      ))}
                    </div>}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border-2 border-sky-400/60 bg-[oklch(0.74_0.12_205)] p-4 shadow-[0_0_12px_rgba(59,130,246,0.18)]">
      <p className="text-xs uppercase tracking-wide text-black/70">{label}</p>
      <p className="mt-2 font-medium text-black">{value || "—"}</p>
    </div>
  );
}

function scaleOf(project: any) {
  const level = pick(project, "scale_level");
  const value = pick(project, "scale_value");
  const count = pick(project, "equipment_count");
  if (level) return String(level);
  if (value !== undefined) return (formatNum(value) + " " + String(pick(project, "scale_unit") ?? "")).trim();
  if (count !== undefined) return formatNum(count) + " equipment units";
  return "—";
}
