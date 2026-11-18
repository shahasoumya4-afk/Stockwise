import type { ReactNode } from "react";
import { Gauge } from "lucide-react";

export function AuthFrame({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-md">
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Gauge className="h-5 w-5" aria-hidden />
            </div>
            <div>
              <p className="text-xs uppercase tracking-widest text-muted-foreground">Inventory Risk Monitor</p>
              <h1 className="text-xl font-semibold">{title}</h1>
            </div>
          </div>
          {subtitle && <p className="mb-4 text-sm text-muted-foreground">{subtitle}</p>}
          <div className="rounded-lg border bg-card p-6">{children}</div>
        </div>
      </main>
    </div>
  );
}
