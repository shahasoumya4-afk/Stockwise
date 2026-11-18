import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, Loader2, Inbox, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";

export function useSlow(active: boolean, ms = 5000) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!active) {
      setSlow(false);
      return;
    }
    const t = setTimeout(() => setSlow(true), ms);
    return () => clearTimeout(t);
  }, [active, ms]);
  return slow;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  const slow = useSlow(true);
  return (
    <div role="status" aria-live="polite" className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
      <Loader2 className="h-6 w-6 animate-spin text-primary" aria-hidden />
      <span>{slow ? "Waking up the server… this can take up to a minute." : label}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const status = error instanceof ApiError ? error.status : undefined;
  const msg = error instanceof Error ? error.message : "Something went wrong.";
  const title =
    status === 403 ? "Access denied" : status === 429 ? "Rate limited" : status === 0 ? "Server unreachable" : "Couldn't load data";
  return (
    <div role="alert" className="flex flex-col items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-6 text-center">
      <AlertTriangle className="h-6 w-6 text-destructive" aria-hidden />
      <div>
        <p className="font-semibold">{title}{status ? ` (${status})` : ""}</p>
        <p className="mt-1 text-sm text-muted-foreground">{msg}</p>
      </div>
      {onRetry && status !== 403 && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCw className="h-4 w-4" /> Retry
        </Button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
      <Inbox className="h-6 w-6" aria-hidden />
      <span>{children}</span>
    </div>
  );
}

export function QueryView<T>({
  q,
  children,
}: {
  q: { isPending: boolean; isError: boolean; error: unknown; data: T | undefined; refetch: () => unknown };
  children: (d: T) => ReactNode;
}) {
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  return <>{children(q.data as T)}</>;
}
