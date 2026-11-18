import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { PageHeader } from "@/components/irm/PageHeader";
import { selectCls, tableWrap } from "@/components/irm/Kpi";
import { Empty, ErrorState, QueryView } from "@/components/irm/states";
import { ApiError, asList, endpoints, pick } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";

export const Route = createFileRoute("/_app/admin")({
  head: () => ({
    meta: [
      { title: "User admin — Inventory Risk Monitor" },
      { name: "description", content: "Approve, reject, disable and assign roles to user accounts." },
      { property: "og:title", content: "User admin — Inventory Risk Monitor" },
      { property: "og:description", content: "Approve, reject, disable and assign roles to user accounts." },
    ],
  }),
  component: Admin,
});

type Action = "approve" | "reject" | "disable" | "enable";
const CONFIRM: Partial<Record<Action, string>> = {
  reject: "Reject this signup request? The user will not be able to sign in.",
  disable: "Disable this account? The user will lose access immediately.",
};

function Admin() {
  const { can } = useAuth();
  const [status, setStatus] = useState("Pending");
  const [confirm, setConfirm] = useState<{ user: any; action: Action } | null>(null);
  const qc = useQueryClient();
  const enabled = can("manage_users");
  const users = useQuery({ queryKey: ["admin-users", status], queryFn: () => endpoints.adminUsers(status), enabled });
  const roles = useQuery({ queryKey: ["auth-options"], queryFn: endpoints.authOptions, enabled });
  const roleList = asList(pick(roles.data, "roles", "all_roles", "requestable_roles") ?? []);

  const done = (msg: string) => {
    toast.success(msg);
    qc.invalidateQueries({ queryKey: ["admin-users"] });
  };
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? `${e.status}: ${e.detail}` : "Action failed");

  const act = useMutation({
    mutationFn: ({ id, action, role }: { id: any; action: Action; role?: string }) =>
      endpoints.adminAction(id, action, action === "approve" && role ? { role_code: role } : undefined),
    onSuccess: (_d, v) => done(`User account ${({ approve: "approved", reject: "rejected", disable: "disabled", enable: "enabled" } as const)[v.action]}.`),
    onError: fail,
  });
  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: any; role: string }) => endpoints.adminRole(id, { role_code: role }),
    onSuccess: () => done("Role updated."),
    onError: fail,
  });

  if (!enabled) return <ErrorState error={new ApiError(403, "You need the manage_users permission to view this page.")} />;

  return (
    <>
      <PageHeader title="User administration" description="Review signup requests and manage account access." />
      <Tabs value={status} onValueChange={setStatus} className="mb-4">
        <TabsList>
          {["Pending", "Active", "Disabled"].map((s) => <TabsTrigger key={s} value={s}>{s}</TabsTrigger>)}
        </TabsList>
      </Tabs>
      <QueryView q={users}>
        {(d) => {
          const rows = asList(d);
          if (!rows.length) return <Empty>No {status.toLowerCase()} users.</Empty>;
          return (
            <div className={tableWrap}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead><TableHead>Employee ID</TableHead><TableHead>Email</TableHead>
                    <TableHead>Department</TableHead><TableHead>Role</TableHead><TableHead>Created</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((u: any) => {
                    const id = pick(u, "id", "user_id");
                    const roleCode = String(pick(u, "assigned_role", "requested_role", "role_code", "role.code", "requested_role_code", "role") ?? "");
                    const busy = (act.isPending && act.variables?.id === id) || (setRole.isPending && setRole.variables?.id === id);
                    return (
                      <TableRow key={id}>
                        <TableCell className="font-medium">{pick(u, "full_name", "name") ?? "—"}</TableCell>
                        <TableCell className="num">{pick(u, "employee_id") ?? "—"}</TableCell>
                        <TableCell>{pick(u, "email") ?? "—"}</TableCell>
                        <TableCell>{pick(u, "department", "department_name", "department.name", "department_id") ?? "—"}</TableCell>
                        <TableCell>
                          {roleList.length && status === "Active" ? (
                            <select aria-label={`Role for ${pick(u, "email")}`} className={selectCls} value={roleCode} disabled={busy}
                              onChange={(e) => setRole.mutate({ id, role: e.target.value })}>
                              {roleList.map((r: any) => {
                                const c = typeof r === "string" ? r : String(pick(r, "code", "role_code"));
                                return <option key={c} value={c}>{typeof r === "string" ? r : (pick(r, "display_name", "name") ?? c)}</option>;
                              })}
                              {roleCode === "ADMIN" && <option value="ADMIN">Administrator</option>}
                            </select>
                          ) : (roleCode || "—")}
                        </TableCell>
                        <TableCell>{formatDate(pick(u, "created_at", "requested_at"))}</TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-2">
                            {status === "Pending" && (
                              <>
                                <Button size="sm" disabled={busy} onClick={() => act.mutate({ id, action: "approve" })}>Approve</Button>
                                <Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirm({ user: u, action: "reject" })}>Reject</Button>
                              </>
                            )}
                            {status === "Active" && (
                              <Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirm({ user: u, action: "disable" })}>Disable</Button>
                            )}
                            {status === "Disabled" && (
                              <Button size="sm" disabled={busy} onClick={() => act.mutate({ id, action: "enable" })}>Enable</Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          );
        }}
      </QueryView>

      <AlertDialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="capitalize">{confirm?.action} {pick(confirm?.user, "full_name", "email")}?</AlertDialogTitle>
            <AlertDialogDescription>{confirm ? CONFIRM[confirm.action] : ""}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => confirm && act.mutate({ id: pick(confirm.user, "id", "user_id"), action: confirm.action })}
            >
              Confirm {confirm?.action}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
