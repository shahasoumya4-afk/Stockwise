import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthFrame } from "@/components/irm/AuthFrame";
import { QueryView, useSlow } from "@/components/irm/states";
import { asList, endpoints, pick } from "@/lib/api";

export const Route = createFileRoute("/signup")({
  head: () => ({
    meta: [
      { title: "Request access — Inventory Risk Monitor" },
      { name: "description", content: "Request an Inventory Risk Monitor account for administrator approval." },
      { property: "og:title", content: "Request access — Inventory Risk Monitor" },
      { property: "og:description", content: "Request an Inventory Risk Monitor account for administrator approval." },
    ],
  }),
  component: Signup,
});

const selectCls =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

function Signup() {
  const options = useQuery({ queryKey: ["auth-options"], queryFn: endpoints.authOptions });
  const [form, setForm] = useState({ full_name: "", employee_id: "", email: "", department_id: "", requested_role_code: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const slow = useSlow(busy);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const dep = Number(form.department_id);
      const res = await endpoints.signup({ ...form, department_id: Number.isFinite(dep) && form.department_id !== "" ? dep : form.department_id });
      setDone(pick(res, "message", "detail") ?? "Your account has been created and is pending administrator approval.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed.");
    } finally {
      setBusy(false);
    }
  }

  if (done)
    return (
      <AuthFrame title="Request submitted">
        <div className="flex flex-col items-center gap-3 text-center">
          <CheckCircle2 className="h-8 w-8 text-ok" aria-hidden />
          <p>{done}</p>
          <p className="text-sm text-muted-foreground">You can sign in once an administrator approves your account.</p>
          <Button asChild variant="outline"><Link to="/login">Back to sign in</Link></Button>
        </div>
      </AuthFrame>
    );

  return (
    <AuthFrame title="Request access" subtitle="New accounts require administrator approval before sign-in.">
      <QueryView q={options}>
        {(opts) => {
          const departments = asList(pick(opts, "departments") ?? []);
          const roles = asList(pick(opts, "roles", "requestable_roles") ?? []);
          return (
            <form onSubmit={submit} className="space-y-3">
              <Field id="full_name" label="Full name"><Input id="full_name" required value={form.full_name} onChange={set("full_name")} /></Field>
              <Field id="employee_id" label="Employee ID"><Input id="employee_id" required value={form.employee_id} onChange={set("employee_id")} /></Field>
              <Field id="email" label="Email"><Input id="email" type="email" autoComplete="email" required value={form.email} onChange={set("email")} /></Field>
              <Field id="department_id" label="Department">
                <select id="department_id" required className={selectCls} value={form.department_id} onChange={set("department_id")}>
                  <option value="">Select department</option>
                  {departments.map((d: any) => {
                    const id = pick(d, "id", "department_id", "code");
                    return <option key={id} value={id}>{pick(d, "name", "label", "code") ?? id}</option>;
                  })}
                </select>
              </Field>
              <Field id="requested_role_code" label="Requested role">
                <select id="requested_role_code" required className={selectCls} value={form.requested_role_code} onChange={set("requested_role_code")}>
                  <option value="">Select role</option>
                  {roles.map((r: any) => {
                    const code = typeof r === "string" ? r : pick(r, "code", "role_code", "id");
                    return <option key={code} value={code}>{typeof r === "string" ? r : (pick(r, "display_name", "name", "label") ?? code)}</option>;
                  })}
                </select>
              </Field>
              <Field id="password" label="Password"><Input id="password" type="password" autoComplete="new-password" required value={form.password} onChange={set("password")} /></Field>
              {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
              {slow && <p role="status" className="text-sm text-muted-foreground">Waking up the server…</p>}
              <Button type="submit" className="w-full" disabled={busy}>{busy ? "Submitting…" : "Submit request"}</Button>
            </form>
          );
        }}
      </QueryView>
      <p className="mt-4 text-center text-sm text-muted-foreground">
        Have an account? <Link to="/login" className="text-primary underline-offset-4 hover:underline">Sign in</Link>
      </p>
    </AuthFrame>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}
