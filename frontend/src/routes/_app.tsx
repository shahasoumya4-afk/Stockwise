import { createFileRoute, Link, Outlet, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Boxes, ClipboardList, Calculator, Gauge, LayoutDashboard, LogOut, Menu, ShieldAlert, Users, X, MessageCircle, ArrowRightLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/irm/states";
import { useAuth } from "@/lib/auth";
import { pick } from "@/lib/api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_app")({
  ssr: false,
  component: AppLayout,
});

const NAV = [
  { to: "/overview", label: "Overview", icon: LayoutDashboard },
  { to: "/risk", label: "Risk", icon: ShieldAlert },
  { to: "/inventory", label: "Inventory", icon: Boxes },
  { to: "/purchase-orders", label: "Purchase Orders", icon: ClipboardList },
  { to: "/estimate", label: "Estimate", icon: Calculator },
  { to: "/assistant", label: "Inventory assistant", icon: MessageCircle },
  { to: "/transfers", label: "Project transfers", icon: ArrowRightLeft },
] as const;

function AppLayout() {
  const { session, ready, signOut, can } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (ready && !session) navigate({ to: "/login", replace: true });
  }, [ready, session, navigate]);

  if (!ready || !session) return <Loading label="Checking session…" />;

  const user = session.user;
  const role = pick(user, "role.name", "role.code", "role_code", "role");
  const items = [...NAV, ...(can("manage_users") ? [{ to: "/admin", label: "User admin", icon: Users } as const] : [])];

  const nav = (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {items.map((n) => (
        <Link
          key={n.to}
          to={n.to}
          onClick={() => setOpen(false)}
          className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
          activeProps={{ className: "bg-sidebar-accent text-sidebar-primary font-medium" }}
        >
          <n.icon className="h-4 w-4" aria-hidden />
          {n.label}
        </Link>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-screen flex-col">
      <div className="flex flex-1">
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-40 w-60 flex-col border-r border-sidebar-border bg-sidebar p-4 md:static md:flex",
            open ? "flex" : "hidden",
          )}
        >
          <div className="mb-6 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded bg-primary text-primary-foreground">
                <Gauge className="h-4 w-4" aria-hidden />
              </div>
              <span className="bg-gradient-to-r from-sky-400 via-blue-500 to-indigo-500 bg-clip-text text-4xl font-black leading-tight tracking-tight text-transparent">Stockwise</span>
            </div>
            <Button variant="ghost" size="icon" className="md:hidden" aria-label="Close menu" onClick={() => setOpen(false)}>
              <X className="h-4 w-4" />
            </Button>
          </div>
          {nav}
          <div className="mt-auto border-t border-sidebar-border pt-4 text-sm">
            <p className="truncate font-medium">{pick(user, "full_name", "name", "email") ?? "Signed in"}</p>
            {role && typeof role !== "object" && <p className="truncate text-xs text-muted-foreground">{String(role)}</p>}
            <Button variant="outline" size="sm" className="mt-3 w-full" onClick={() => { signOut(); navigate({ to: "/login" }); }}>
              <LogOut className="h-4 w-4" /> Log out
            </Button>
          </div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center gap-2 border-b px-4 py-2 md:hidden">
            <Button variant="ghost" size="icon" aria-label="Open menu" onClick={() => setOpen(true)}>
              <Menu className="h-5 w-5" />
            </Button>
            <span className="bg-gradient-to-r from-sky-400 via-blue-500 to-indigo-500 bg-clip-text text-5xl font-black tracking-tight text-transparent">Stockwise</span>
          </header>
          <main className="flex-1 p-4 md:p-8">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}

