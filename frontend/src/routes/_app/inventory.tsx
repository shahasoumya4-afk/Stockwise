import { createFileRoute } from "@tanstack/react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/irm/PageHeader";
import { selectCls, tableWrap } from "@/components/irm/Kpi";
import { Empty, QueryView, useSlow } from "@/components/irm/states";
import { asList, endpoints, pick, totalOf } from "@/lib/api";
import { formatNum } from "@/lib/format";

export const Route = createFileRoute("/_app/inventory")({
  head: () => ({
    meta: [
      { title: "Inventory — Inventory Risk Monitor" },
      { name: "description", content: "Stock on hand, reservations and reorder points by warehouse." },
      { property: "og:title", content: "Inventory — Inventory Risk Monitor" },
      { property: "og:description", content: "Stock on hand, reservations and reorder points by warehouse." },
    ],
  }),
  component: Inventory,
});

const LIMIT = 50;
const whOf = (r: any) => String(pick(r, "warehouse", "warehouse_code", "warehouse_name", "warehouse.name", "warehouse_id") ?? "—");
const n = (v: any) => (v === undefined || v === null ? NaN : Number(v));

function Inventory() {
  const [offset, setOffset] = useState(0);
  const [warehouse, setWarehouse] = useState("");
  const [below, setBelow] = useState(false);
  const warehouseQuery = useQuery({ queryKey: ["warehouses"], queryFn: endpoints.warehouses });
  const q = useQuery({
    queryKey: ["inventory", offset, warehouse, below],
    queryFn: () => endpoints.inventory({
      limit: LIMIT,
      offset,
      warehouse_id: warehouse || undefined,
      below_reorder: below ? true : undefined,
    }),
    placeholderData: keepPreviousData,
  });
  const slow = useSlow(q.isFetching && !q.isPending);
  const rows = useMemo(() => asList(q.data), [q.data]);
  const warehouses = asList(warehouseQuery.data);

  const total = totalOf(q.data);
  const hasNext = total !== undefined ? offset + LIMIT < total : rows.length === LIMIT;

  return (
    <>
      <PageHeader title="Inventory" description="Available = on hand − reserved, compared against reorder point." />
      <div className="mb-4 flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          Warehouse
          <select className={selectCls} value={warehouse} onChange={(e) => { setWarehouse(e.target.value); setOffset(0); }}>
            <option value="">All</option>
            {warehouses.map((w: any) => {
              const id = String(pick(w, "warehouse_id", "id"));
              return <option key={id} value={id}>{pick(w, "name", "warehouse_code") ?? id}</option>;
            })}
          </select>
        </label>
        <div className="flex items-center gap-2">
          <Switch id="below" checked={below} onCheckedChange={(v) => { setBelow(v); setOffset(0); }} />
          <Label htmlFor="below">Below reorder point only</Label>
        </div>
        {slow && <span role="status" className="text-sm text-muted-foreground">Waking up the server…</span>}
      </div>
      <QueryView q={q}>
        {() => {
          const filtered = rows;
          return (
            <>
              {filtered.length === 0 ? (
                <Empty>{rows.length === 0 ? "No inventory records." : "No items on this page match these filters."}</Empty>
              ) : (
                <div className={tableWrap}>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Warehouse</TableHead><TableHead>Material</TableHead>
                        <TableHead className="text-right">On hand</TableHead><TableHead className="text-right">Reserved</TableHead>
                        <TableHead className="text-right">Available</TableHead><TableHead className="text-right">Reorder point</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filtered.map((r: any, i: number) => {
                        const avail = availOf(r);
                        const rop = n(pick(r, "reorder_point_quantity", "reorder_point"));
                        const flag = Number.isFinite(avail) && Number.isFinite(rop) && avail <= rop;
                        return (
                          <TableRow key={pick(r, "id") ?? `${offset}-${i}`}>
                            <TableCell>{whOf(r)}</TableCell>
                            <TableCell>{[pick(r, "material_code", "material.code"), pick(r, "material_name", "material.name", "description")].filter(Boolean).join(" · ") || "—"}</TableCell>
                            <TableCell className="num text-right">{formatNum(pick(r, "on_hand_quantity", "on_hand", "on_hand_qty", "quantity_on_hand"))}</TableCell>
                            <TableCell className="num text-right">{formatNum(pick(r, "reserved_quantity", "reserved", "reserved_qty", "quantity_reserved"))}</TableCell>
                            <TableCell className={`num text-right ${flag ? "font-semibold text-short" : ""}`}>
                              <span className="inline-flex items-center gap-1">
                                {flag && <AlertTriangle className="h-3.5 w-3.5" aria-label="At or below reorder point" />}
                                {formatNum(avail)}
                              </span>
                            </TableCell>
                            <TableCell className="num text-right">{formatNum(rop)}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
              <div className="mt-4 flex items-center justify-between text-sm">
                <span className="text-muted-foreground">
                  {rows.length ? `Showing ${offset + 1}–${offset + rows.length}${total !== undefined ? ` of ${total}` : ""}` : ""}
                </span>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" disabled={offset === 0 || q.isFetching} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>Previous</Button>
                  <Button variant="outline" size="sm" disabled={!hasNext || q.isFetching} onClick={() => setOffset(offset + LIMIT)}>Next</Button>
                </div>
              </div>
            </>
          );
        }}
      </QueryView>
    </>
  );
}

function availOf(r: any) {
  const a = n(pick(r, "available_quantity", "available", "available_qty", "quantity_available"));
  if (Number.isFinite(a)) return a;
  return n(pick(r, "on_hand_quantity", "on_hand", "on_hand_qty")) - n(pick(r, "reserved_quantity", "reserved", "reserved_qty"));
}
