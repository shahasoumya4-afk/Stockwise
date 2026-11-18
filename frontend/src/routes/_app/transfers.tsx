import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/irm/PageHeader";
import { tableWrap } from "@/components/irm/Kpi";
import { Empty, QueryView } from "@/components/irm/states";
import { asList, endpoints } from "@/lib/api";
import { formatDate, formatNum } from "@/lib/format";

export const Route = createFileRoute("/_app/transfers")({
  head: () => ({
    meta: [
      { title: "Project transfers — Inventory Risk Monitor" },
      { name: "description", content: "Audit history for material allocations transferred between projects." },
    ],
  }),
  component: Transfers,
});

function Transfers() {
  const q = useQuery({ queryKey: ["allocation-transfers"], queryFn: () => endpoints.transferHistory() });
  return (
    <>
      <PageHeader
        title="Project transfers"
        description="Audit trail of material allocation moved between projects. Transfers change project reservations; physical on-hand stock stays the same."
      />
      <QueryView q={q}>
        {(data) => {
          const rows = asList(data?.items);
          return rows.length === 0 ? (
            <Empty>No project allocation transfers have been recorded.</Empty>
          ) : (
            <div className={tableWrap}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Transfer</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>From project</TableHead>
                    <TableHead>To project</TableHead>
                    <TableHead>Material</TableHead>
                    <TableHead>Warehouse</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                    <TableHead>Recorded by</TableHead>
                    <TableHead>Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row: any) => (
                    <TableRow key={String(row.transfer_id)}>
                      <TableCell className="font-mono text-xs">{row.transfer_code}</TableCell>
                      <TableCell>{formatDate(row.transferred_at)}</TableCell>
                      <TableCell>{row.source_project_code} — {row.source_project_name}</TableCell>
                      <TableCell>{row.target_project_code} — {row.target_project_name}</TableCell>
                      <TableCell>{row.material_code} — {row.material_name}</TableCell>
                      <TableCell>{row.warehouse}</TableCell>
                      <TableCell className="num text-right">{formatNum(row.quantity)} {row.uom_code}</TableCell>
                      <TableCell>{row.transferred_by}</TableCell>
                      <TableCell className="max-w-64 whitespace-normal">{row.notes || "—"}</TableCell>
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