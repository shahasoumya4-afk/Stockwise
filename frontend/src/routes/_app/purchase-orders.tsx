import { createFileRoute, Link, Outlet, useMatch } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/irm/PageHeader";
import { tableWrap } from "@/components/irm/Kpi";
import { Empty, QueryView } from "@/components/irm/states";
import { asList, endpoints, pick } from "@/lib/api";
import { formatDate, humanize } from "@/lib/format";

export const Route = createFileRoute("/_app/purchase-orders")({
  head: () => ({
    meta: [
      { title: "Purchase orders — Inventory Risk Monitor" },
      { name: "description", content: "Open purchase orders with supplier, dates and value." },
      { property: "og:title", content: "Purchase orders — Inventory Risk Monitor" },
      { property: "og:description", content: "Open purchase orders with supplier, dates and value." },
    ],
  }),
  component: POList,
});

export const poId = (o: any) => String(pick(o, "id", "po_id", "purchase_order_id"));

function POList() {
  const detail = useMatch({ from: "/_app/purchase-orders/$id", shouldThrow: false });
  const q = useQuery({ queryKey: ["purchase-orders"], queryFn: endpoints.purchaseOrders, enabled: !detail });
  if (detail) return <Outlet />;
  return (
    <>
      <PageHeader title="Open purchase orders" description="Select an order to see its lines and outstanding quantities." />
      <QueryView q={q}>
        {(d) => {
          const rows = asList(d);
          if (!rows.length) return <Empty>No open purchase orders.</Empty>;
          return (
            <div className={tableWrap}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>PO</TableHead><TableHead>Supplier</TableHead><TableHead>Status</TableHead>
                    <TableHead>Warehouse</TableHead><TableHead>Order date</TableHead><TableHead>Expected delivery</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((o: any) => (
                    <TableRow key={poId(o)}>
                      <TableCell>
                        <Link to="/purchase-orders/$id" params={{ id: poId(o) }} className="font-medium text-primary underline-offset-4 hover:underline">
                          {pick(o, "po_number", "number", "code") ?? poId(o)}
                        </Link>
                      </TableCell>
                      <TableCell>{pick(o, "supplier_name", "supplier.name", "vendor_name", "supplier") ?? "—"}</TableCell>
                      <TableCell>{humanize(pick(o, "status"))}</TableCell>
                      <TableCell>{pick(o, "warehouse", "warehouse_name", "warehouse.name") ?? "—"}</TableCell>
                      <TableCell>{formatDate(pick(o, "order_date", "created_at", "issued_date"))}</TableCell>
                      <TableCell>{formatDate(pick(o, "expected_date", "expected_delivery_date", "promised_date", "due_date"))}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          );
        }}
      </QueryView>
    </>
  );
}
