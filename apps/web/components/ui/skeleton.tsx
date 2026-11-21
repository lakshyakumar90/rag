import { cn } from "../../lib/utils";

/** Skeletons keep the real row's pitch: one line per real line. */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse rounded bg-muted", className)} {...props} />;
}

export function RowSkeleton({ lines = 2 }: { lines?: number }) {
  return (
    <div className="flex flex-col gap-2 border-b border-border px-3 py-3">
      <div className="flex items-center gap-3">
        <Skeleton className="h-3.5 w-44" />
        <Skeleton className="ml-auto h-3 w-12" />
      </div>
      {lines > 1 ? <Skeleton className="h-2.5 w-28" /> : null}
    </div>
  );
}
