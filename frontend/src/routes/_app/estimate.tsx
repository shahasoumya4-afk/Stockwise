import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { AlertTriangle, FlaskConical } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/irm/PageHeader";
import { Kpi, selectCls, tableWrap } from "@/components/irm/Kpi";
import { Empty, ErrorState, Loading, QueryView } from "@/components/irm/states";
import { asList, endpoints, pick } from "@/lib/api";
import { formatINR, formatNum, humanize } from "@/lib/format";

export const Route = createFileRoute("/_app/estimate")({
  head: () => ({
    meta: [
      { title: "Estimate — Inventory Risk Monitor" },
      { name: "description", content: "Synthetic indicative material estimates by project category and scale." },
      { property: "og:title", content: "Estimate — Inventory Risk Monitor" },
      { property: "og:description", content: "Synthetic indicative material estimates by project category and scale." },
    ],
  }),
  component: Estimate,
});

const BF = "BLAST_FURNACE_UPGRADE";
const BF_LEVELS = ["Small", "Medium", "Large"];
const catCode = (c: any) => String(typeof c === "string" ? c : pick(c, "code", "category_code", "category", "id"));

function Estimate() {
  const model = useQuery({ queryKey: ["estimate-model"], queryFn: endpoints.estimateModel });
  const [category, setCategory] = useState("");
  const [scale, setScale] = useState("");
  const preview = useMutation({ mutationFn: endpoints.estimatePreview });

  return (
    <>
      <PageHeader title="Material estimate" description="Indicative requirements from a synthetic statistical model." />
      <div className="mb-6 flex items-start gap-2 rounded-md border border-watch/40 bg-watch/10 p-3 text-sm">
        <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-watch" aria-hidden />
        Synthetic estimate for prototype use only. Not an approved bill of materials or engineering recommendation.
      </div>
      <QueryView q={model}>
        {(m) => {
          const cats = asList(pick(m, "categories") ?? m);
          const cur = cats.find((c: any) => catCode(c) === category);
          const isBF = category === BF;
          const levels = asList(pick(cur, "allowed_scale_levels", "scale_levels", "levels", "supported_scales") ?? []);
          const bfOptions = levels.length ? levels : BF_LEVELS;
          const scaleRange = asList(pick(cur, "training_scale_range") ?? []);
          const min = pick(cur, "scale_min", "min_scale", "scale.min") ?? scaleRange[0];
          const max = pick(cur, "scale_max", "max_scale", "scale.max") ?? scaleRange[1];
          const unit = pick(cur, "scale_unit", "unit", "scale.unit");

          const submit = (e: FormEvent) => {
            e.preventDefault();
            preview.mutate({
              category_code: category,
              scale_level: isBF ? scale : undefined,
              scale_value: isBF ? undefined : Number(scale),
            });
          };
          return (
            <form onSubmit={submit} className="mb-8 grid gap-4 rounded-lg border bg-card p-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
              <div className="space-y-1.5">
                <Label htmlFor="cat">Project category</Label>
                <select id="cat" required className={`${selectCls} w-full`} value={category} onChange={(e) => { setCategory(e.target.value); setScale(""); preview.reset(); }}>
                  <option value="">Select category</option>
                  {cats.map((c: any) => <option key={catCode(c)} value={catCode(c)}>{typeof c === "string" ? humanize(c) : (pick(c, "name", "label") ?? humanize(catCode(c)))}</option>)}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="scale">Scale{unit ? ` (${unit})` : ""}</Label>
                {isBF ? (
                  <select id="scale" required className={`${selectCls} w-full`} value={scale} onChange={(e) => setScale(e.target.value)}>
                    <option value="">Select level</option>
                    {bfOptions.map((l: any) => {
                      const v = typeof l === "object" ? String(pick(l, "code", "value", "name")) : String(l);
                      return <option key={v} value={v}>{typeof l === "object" ? (pick(l, "label", "name") ?? v) : humanize(v)}</option>;
                    })}
                  </select>
                ) : (
                  <Input id="scale" type="number" step="any" required disabled={!category} min={min} max={max} value={scale} onChange={(e) => setScale(e.target.value)}
                    placeholder={min !== undefined && max !== undefined ? `${min} – ${max}` : "Enter scale"} />
                )}
              </div>
              <Button type="submit" disabled={!category || !scale || preview.isPending}>{preview.isPending ? "Estimating…" : "Preview estimate"}</Button>
            </form>
          );
        }}
      </QueryView>

      {preview.isPending && <Loading label="Computing estimate…" />}
      {preview.isError && <ErrorState error={preview.error} onRetry={() => preview.variables && preview.mutate(preview.variables)} />}
      {preview.data && <EstimateResult r={preview.data} />}
    </>
  );
}

function EstimateResult({ r }: { r: any }) {
  const lines = asList(pick(r, "lines", "items", "estimate_lines") ?? []);
  const extrapolated = Boolean(pick(r, "extrapolated", "is_extrapolated"));
  return (
    <section aria-label="Estimate result">
      {extrapolated && (
        <div role="alert" className="mb-4 flex items-start gap-2 rounded-md border border-short/50 bg-short/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-short" aria-hidden />
          <span><strong>Extrapolated.</strong> This scale is outside the range of historical data; treat the estimate with extra caution.</span>
        </div>
      )}
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Kpi label="Indicative total value (synthetic)" value={formatINR(pick(r, "indicative_total_value", "indicative_value", "indicative_total", "total_value", "estimated_value"))} />
        <Kpi label="Estimated material lines" value={formatNum(pick(r, "line_count"))} />
        <Kpi label="Model version" value={pick(r, "model.version") ?? "—"} />
      </div>
      {lines.length === 0 ? <Empty>No estimate lines returned.</Empty> : (
        <div className={tableWrap}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Material</TableHead><TableHead className="text-right">P10 qty</TableHead><TableHead className="text-right">Estimate qty</TableHead>
                <TableHead className="text-right">P90 qty</TableHead><TableHead>Unit</TableHead><TableHead className="text-right">Indicative value</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.map((l: any, i: number) => (
                <TableRow key={i}>
                  <TableCell>{[pick(l, "material_code", "material.code"), pick(l, "material_name", "material.name", "description")].filter(Boolean).join(" · ") || "—"}</TableCell>
                  <TableCell className="num text-right">{formatNum(pick(l, "range_p10", "p10", "p10_qty", "qty_p10"))}</TableCell>
                  <TableCell className="num text-right">{formatNum(pick(l, "estimated_quantity", "estimate", "estimated_qty", "quantity", "p50", "qty"))}</TableCell>
                  <TableCell className="num text-right">{formatNum(pick(l, "range_p90", "p90", "p90_qty", "qty_p90"))}</TableCell>
                  <TableCell>{pick(l, "uom_code", "unit", "uom") ?? "—"}</TableCell>
                  <TableCell className="num text-right">{formatINR(pick(l, "indicative_value", "value", "estimated_value"))}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <p className="mt-3 text-xs text-muted-foreground">Synthetic estimate. Values are illustrative only.</p>
    </section>
  );
}
