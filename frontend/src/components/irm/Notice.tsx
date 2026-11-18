import { FlaskConical } from "lucide-react";

export function SyntheticNotice() {
  return (
    <div role="note" className="flex items-center justify-center gap-2 bg-notice px-4 py-1.5 text-center text-xs font-medium text-notice-foreground">
      <FlaskConical className="h-3.5 w-3.5 shrink-0" aria-hidden />
      Synthetic prototype data. Not an approved bill of materials or engineering recommendation.
    </div>
  );
}
