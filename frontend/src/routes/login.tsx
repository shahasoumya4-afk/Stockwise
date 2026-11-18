import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthFrame } from "@/components/irm/AuthFrame";
import { useSlow } from "@/components/irm/states";
import { ApiError, endpoints, pick } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/login")({
  validateSearch: (s: Record<string, unknown>): { expired?: number } => (s["expired"] ? { expired: 1 } : {}),
  head: () => ({
    meta: [
      { title: "Sign in — Inventory Risk Monitor" },
      { name: "description", content: "Sign in to monitor plant inventory and shortage risk." },
      { property: "og:title", content: "Sign in — Inventory Risk Monitor" },
      { property: "og:description", content: "Sign in to monitor plant inventory and shortage risk." },
    ],
  }),
  component: Login,
});

function Login() {
  const { expired } = Route.useSearch();
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const slow = useSlow(busy);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await endpoints.login(email.trim(), password);
      const token = pick(res, "access_token", "token");
      if (!token) throw new Error("Login response did not include an access token.");
      signIn({ token, user: pick(res, "user") ?? {} });
      navigate({ to: "/overview" });
    } catch (err) {
      const prefix = err instanceof ApiError && err.status === 429 ? "Too many attempts: " : "";
      setError(prefix + (err instanceof Error ? err.message : "Login failed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthFrame title="Sign in">
      {expired && !error && (
        <p className="mb-4 rounded-md border border-watch/40 bg-watch/10 p-3 text-sm">Your session ended. Please sign in again.</p>
      )}
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        {slow && <p role="status" className="text-sm text-muted-foreground">Waking up the server…</p>}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-muted-foreground">
        No account? <Link to="/signup" className="text-primary underline-offset-4 hover:underline">Request access</Link>
      </p>
    </AuthFrame>
  );
}
