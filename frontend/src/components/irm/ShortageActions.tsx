import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ArrowRightLeft, CheckCircle2, PackageCheck, ShoppingCart, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { asList, endpoints, getSession, hasPermission, pick } from "@/lib/api";
import { formatDate, formatNum } from "@/lib/format";

export function ShortageActions({ row }: { row: any }) {
  const lineId = Number(pick(row, "requirement_line_id"));
  const projectId = Number(pick(row, "project_id"));
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState("");
  const user = getSession()?.user;
  const roleCode = String(pick(user, "role_code", "role.code", "role") ?? "").toUpperCase();
  const canManage = hasPermission(user, "manage_inventory") || ["ADMIN", "INVENTORY_MANAGER"].includes(roleCode);
  const options = useQuery({
    queryKey: ["fulfillment-options", lineId],
    queryFn: () => endpoints.fulfillmentOptions(lineId),
    enabled: Number.isFinite(lineId) && lineId > 0,
  });
  const history = useQuery({
    queryKey: ["allocation-transfers", projectId],
    queryFn: () => endpoints.transferHistory(projectId),
    enabled: Number.isFinite(projectId) && projectId > 0,
  });

  const refreshAfterAction = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["shortages"] }),
      queryClient.invalidateQueries({ queryKey: ["risk-summary"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] }),
      queryClient.invalidateQueries({ queryKey: ["inventory"] }),
      queryClient.invalidateQueries({ queryKey: ["fulfillment-options", lineId] }),
      queryClient.invalidateQueries({ queryKey: ["allocation-transfers"] }),
      queryClient.invalidateQueries({ queryKey: ["project-requirements"] }),
      queryClient.invalidateQueries({ queryKey: ["project-risk"] }),
    ]);
  };
  const allocate = useMutation({
    mutationFn: (option: any) => endpoints.allocateFreeStock(lineId, {
      warehouse_id: option.warehouse_id,
      quantity: option.recommended_quantity,
      notes: "Allocated from free stock to cover a project shortage.",
    }),
    onSuccess: async (result: any) => {
      setNotice(result?.message ?? "Warehouse stock allocated.");
      await refreshAfterAction();
    },
  });
  const transfer = useMutation({
    mutationFn: (option: any) => endpoints.transferAllocation({
      source_allocation_id: option.source_allocation_id,
      target_requirement_line_id: lineId,
      quantity: option.recommended_quantity,
      temporary_borrow: Boolean(option.temporary_borrow),
      notes: option.temporary_borrow
        ? "Temporary borrow; replenish the donor project before its material need-by date."
        : "Transferred safe surplus to cover a project shortage.",
    }),
    onSuccess: async (result: any) => {
      setNotice(result?.message ?? "Project allocation transferred.");
      await refreshAfterAction();
    },
  });

  const data = options.data ?? {};
  const free = asList(pick(data, "free_stock_options"));
  const donors = asList(pick(data, "transfer_options"));
  const borrowers = asList(pick(data, "scheduled_borrow_options"));
  const orders = asList(pick(data, "open_order_options"));
  const historyRows = asList(pick(history.data, "items"));
  const busy = allocate.isPending || transfer.isPending;
  const errors = [options.error, allocate.error, transfer.error, history.error].filter(Boolean) as Error[];

  return (
    <section className="mt-4 space-y-4 border-t pt-4" aria-label="Shortage fulfillment">
      <div>
        <h3 className="mb-1 font-medium">Fulfill this shortage</h3>
        <p className="text-xs text-muted-foreground">
          Use free stock first, then safe surplus. A temporary borrow is offered separately when another project's material need date is later, and it must be replenished by that date.
        </p>
      </div>
      {options.isLoading && <p className="text-sm text-muted-foreground">Checking stock, orders, and project allocations…</p>}
      {errors.map((error, i) => <p key={i} role="alert" className="rounded border border-destructive/40 p-2 text-sm text-destructive">{error.message}</p>)}
      {notice && <p role="status" className="flex items-center gap-2 rounded border border-emerald-600/30 bg-emerald-600/5 p-2 text-sm"><CheckCircle2 className="h-4 w-4" />{notice}</p>}
      {!canManage && <p className="rounded border bg-muted/40 p-2 text-xs text-muted-foreground">Only an administrator or inventory manager can make allocations or transfers.</p>}

      {!options.isLoading && (
        <>
          <div>
            <h4 className="mb-2 flex items-center gap-2 text-sm font-medium"><PackageCheck className="h-4 w-4" />Available warehouse stock</h4>
            {free.length ? <div className="space-y-2">{free.map((item: any) => (
              <div key={String(item.warehouse_id)} className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-background p-3">
                <p className="text-sm">{item.warehouse}: {formatNum(item.recommended_quantity)} {item.uom_code} available to allocate</p>
                <Button size="sm" variant="outline" disabled={!canManage || busy} onClick={() => allocate.mutate(item)}>
                  {allocate.isPending ? "Allocating…" : "Allocate stock"}
                </Button>
              </div>
            ))}</div> : <p className="text-sm text-muted-foreground">No free warehouse stock is available for this material.</p>}
          </div>

          <div>
            <h4 className="mb-2 flex items-center gap-2 text-sm font-medium"><ArrowRightLeft className="h-4 w-4" />Safe surplus from another active project</h4>
            {donors.length ? <div className="space-y-2">{donors.map((item: any) => (
              <div key={String(item.source_allocation_id)} className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-background p-3">
                <div className="text-sm">
                  <p><strong>{item.donor_project_code} — {item.donor_project_name}</strong> at {item.warehouse}</p>
                  <p className="text-muted-foreground">{formatNum(item.recommended_quantity)} {item.uom_code} safe surplus · donor need by {formatDate(item.donor_need_by)}</p>
                </div>
                <Button size="sm" variant="outline" disabled={!canManage || busy} onClick={() => {
                  const ok = window.confirm("Transfer " + formatNum(item.recommended_quantity) + " " + item.uom_code + " from " + item.donor_project_code + " to " + String(pick(data, "project_code")) + "? This reduces the donor allocation and increases the receiving project's allocation.");
                  if (ok) transfer.mutate(item);
                }}>
                  {transfer.isPending ? "Transferring…" : "Transfer safe surplus"}
                </Button>
              </div>
            ))}</div> : <p className="text-sm text-muted-foreground">No surplus is available above another project's remaining approved need.</p>}
          </div>

          <div className="rounded-md border border-amber-600/40 bg-amber-600/5 p-3">
            <h4 className="mb-1 flex items-center gap-2 text-sm font-medium"><TriangleAlert className="h-4 w-4 text-amber-600" />Temporary borrow from a later-scheduled project</h4>
            <p className="mb-2 text-xs text-muted-foreground">Borrowing reduces the donor's reservation and can create a shortage there. The recipient's requirement is prioritized; replenish the donor before its material need-by date.</p>
            {borrowers.length ? <div className="space-y-2">{borrowers.map((item: any) => (
              <div key={String(item.source_allocation_id)} className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-background p-3">
                <div className="text-sm">
                  <p><strong>{item.donor_project_code} — {item.donor_project_name}</strong> at {item.warehouse}</p>
                  <p className="text-muted-foreground">{formatNum(item.recommended_quantity)} {item.uom_code} · donor material needed {formatDate(item.donor_need_by)} ({formatNum(item.days_after_recipient_need)} days after recipient need)</p>
                  <p className="text-xs text-amber-700">Donor project end: {formatDate(item.donor_project_end_date)}. Replenishment is required before its material need date.</p>
                </div>
                <Button size="sm" variant="outline" disabled={!canManage || busy} onClick={() => {
                  const ok = window.confirm("Temporarily transfer " + formatNum(item.recommended_quantity) + " " + item.uom_code + " from " + item.donor_project_code + " to " + String(pick(data, "project_code")) + "? This will reduce the donor project's reservation and may make its requirement short. You must replenish the donor before " + formatDate(item.donor_need_by) + ".");
                  if (ok) transfer.mutate(item);
                }}>
                  {transfer.isPending ? "Transferring…" : "Confirm temporary borrow"}
                </Button>
              </div>
            ))}</div> : <p className="text-sm text-muted-foreground">No active project has an allocated requirement for this material with a later material need-by date.</p>}
          </div>

          <div>
            <h4 className="mb-2 flex items-center gap-2 text-sm font-medium"><ShoppingCart className="h-4 w-4" />Open supplier orders</h4>
            {orders.length ? <ul className="space-y-1 text-sm">{orders.map((item: any, i: number) => (
              <li key={String(item.po_number) + i} className="text-muted-foreground">
                {item.po_number}: {formatNum(item.outstanding_quantity)} on order from {item.supplier_name}, expected {formatDate(item.expected_delivery_date)} — {item.on_time ? "before need date" : "after need date"}.
              </li>
            ))}</ul> : <p className="text-sm text-muted-foreground">No open supplier order is recorded for this material.</p>}
          </div>
        </>
      )}

      <div>
        <h4 className="mb-2 text-sm font-medium">Project transfer history</h4>
        {history.isLoading ? <p className="text-sm text-muted-foreground">Loading transfer history…</p> :
          historyRows.length ? <ul className="space-y-1 text-sm">{historyRows.slice(0, 5).map((item: any) => {
            const incoming = Number(item.target_project_id) === projectId;
            return <li key={String(item.transfer_id)} className="text-muted-foreground">
              {incoming ? "Received from " + item.source_project_code : "Transferred to " + item.target_project_code}: {formatNum(item.quantity)} {item.uom_code} {item.material_code} ({formatDate(item.transferred_at)}){item.notes?.startsWith("Temporary borrow") ? " · temporary borrow" : ""}.
            </li>;
          })}</ul> : <p className="text-sm text-muted-foreground">No project allocation transfers recorded for this project.</p>}
      </div>
    </section>
  );
}