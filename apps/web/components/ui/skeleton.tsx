import { cn } from "../../lib/utils";

/** Theme-aware shimmer block matching both light (#faf9f6) and dark (#000000) surfaces. */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("shimmer rounded-md", className)}
      aria-hidden="true"
      {...props}
    />
  );
}

export function RowSkeleton({ lines = 2 }: { lines?: number }) {
  return (
    <div className="flex flex-col gap-2.5 border-b border-border px-4 py-3.5">
      <div className="flex items-center gap-3">
        <Skeleton className="h-3.5 w-48" />
        <Skeleton className="ml-auto h-3 w-16" />
      </div>
      {lines > 1 ? <Skeleton className="h-2.5 w-32" /> : null}
    </div>
  );
}

/** Full-width card grid shimmer for dashboard, evals, and memory pages. */
export function CardGridSkeleton({
  cards = 4,
  rows = 4,
}: {
  cards?: number;
  rows?: number;
}) {
  return (
    <div className="w-full space-y-6" role="status" aria-label="Loading content">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: cards }).map((_, i) => (
          <div
            key={i}
            className="rounded-2xl border border-border bg-surface p-4 space-y-3"
          >
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-7 w-20" />
            <Skeleton className="h-1.5 w-full rounded-full" />
          </div>
        ))}
      </div>
      <div className="overflow-hidden rounded-2xl border border-border bg-surface">
        {Array.from({ length: rows }).map((_, i) => (
          <RowSkeleton key={i} lines={2} />
        ))}
      </div>
    </div>
  );
}

/** Full-height, full-width application shell shimmer used while authenticating or hydrating. */
export function WorkspacePageSkeleton() {
  return (
    <div
      className="flex min-h-screen w-full bg-background text-foreground"
      role="status"
      aria-label="Loading workspace"
    >
      {/* Desktop sidebar rail shimmer */}
      <aside className="hidden w-60 shrink-0 flex-col justify-between border-r border-border bg-surface p-4 md:flex">
        <div className="space-y-6">
          <div className="flex items-center gap-2.5 px-1">
            <Skeleton className="h-7 w-7 rounded-lg" />
            <Skeleton className="h-4 w-28" />
          </div>
          <Skeleton className="h-8 w-full rounded-lg" />
          <div className="space-y-2 pt-2">
            {Array.from({ length: 7 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full rounded-lg" />
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2.5 border-t border-border pt-4">
          <Skeleton className="h-7 w-7 rounded-full" />
          <Skeleton className="h-3.5 w-32" />
        </div>
      </aside>

      {/* Main full-height viewport shimmer */}
      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-border bg-surface/60 px-6">
          <Skeleton className="h-4 w-40" />
          <div className="flex items-center gap-2">
            <Skeleton className="h-8 w-24 rounded-lg" />
            <Skeleton className="h-8 w-8 rounded-lg" />
          </div>
        </header>
        <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 p-6">
          <div className="rounded-2xl border border-border bg-surface p-6 space-y-3">
            <Skeleton className="h-6 w-56" />
            <Skeleton className="h-4 w-96 max-w-full" />
          </div>
          <CardGridSkeleton cards={4} rows={5} />
        </main>
      </div>
    </div>
  );
}
