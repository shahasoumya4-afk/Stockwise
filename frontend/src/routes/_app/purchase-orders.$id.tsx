import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/irm/PageHeader";
import { Kpi, tableWrap } from "@/components/irm/Kpi";
import { Empty, QueryView } from "@/components/irm/states";
import { asList, endpoints, pick } from "@/lib/api";
import { formatDate, formatINR, formatNum, humanize } from "@/lib/format";

export const Route = createFileRoute("/_app/purchase-orders/$id")({
  head: () => ({
    meta: [
      { title: "Purchase order detail — Inventory Risk Monitor" },
      { name: "description", content: "Purchase order lines and outstanding quantities." },
      { property: "og:title", content: "Purchase order detail — Inventory Risk Monitor" },
      { property: "og:description", content: "Purchase order lines and outstanding quantities." },
    ],
  }),
  component: PODetail,
});

const num = (v: any) => (v === undefined || v === null ? NaN : Number(v));

function PODetail() {
  const { id } = Route.useParams();
  const q = useQuery({ queryKey: ["purchase-order", id], queryFn: () => endpoints.purchaseOrder(id) });
  return (
    <>
      <Link to="/purchase-orders" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> All open orders
      </Link>
      <QueryView q={q}>
        {(o) => {
          const lines = asList(pick(o, "lines", "items", "order_lines") ?? []);
          return (
            <>
              <PageHeader title={`PO ${pick(o, "po_number", "number", "code") ?? id}`} description={pick(o, "supplier_name", "supplier.name", "vendor_name")} />
              <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
                <Kpi label="Status" value={humanize(pick(o, "status"))} />
                <Kpi label="Order date" value={formatDate(pick(o, "order_date", "created_at", "issued_date"))} />
                <Kpi label="Expected" value={formatDate(pick(o, "expected_date", "expected_delivery_date", "promised_date", "due_date"))} />
                <Kpi label="Warehouse" value={pick(o, "warehouse", "warehouse_name", "warehouse.name") ?? "—"} />
              </div>
              <h2 className="mb-3 text-lg font-semibold">Lines</h2>
              {lines.length === 0 ? <Empty>This order has no lines.</Empty> : (
                <div className={tableWrap}>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Material</TableHead><TableHead className="text-right">Ordered</TableHead>
                        <TableHead className="text-right">Received</TableHead><TableHead className="text-right">Outstanding</TableHead>
                        <TableHead className="text-right">Unit price</TableHead><TableHead>Expected</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {lines.map((l: any, i: number) => {
                        const ordered = num(pick(l, "ordered_quantity", "quantity_ordered", "ordered_qty", "quantity", "qty"));
                        const received = num(pick(l, "received_quantity", "quantity_received", "received_qty", "received"));
                        let out = num(pick(l, "outstanding_quantity", "outstanding_qty", "outstanding", "quantity_outstanding"));
                        if (!Number.isFinite(out) && Number.isFinite(ordered) && Number.isFinite(received)) out = ordered - received;
                        return (
                          <TableRow key={pick(l, "id", "line_no") ?? i}>
                            <TableCell>{[pick(l, "material_code", "material.code"), pick(l, "material_name", "material.name", "description")].filter(Boolean).join(" · ") || "—"}</TableCell>
                            <TableCell className="num text-right">{formatNum(ordered)}</TableCell>
                            <TableCell className="num text-right">{formatNum(received)}</TableCell>
                            <TableCell className={`num text-right ${out > 0 ? "font-semibold text-watch" : ""}`}>{formatNum(out)}</TableCell>
                            <TableCell className="num text-right">{formatINR(pick(l, "unit_price", "price", "unit_cost"))}</TableCell>
                          <TableCell>{formatDate(pick(l, "expected_delivery_date", "expected_date", "due_date", "promised_date"))}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </>
          );
        }}
      </QueryView>
    </>
  );
}
