import * as React from "react";
import { cn } from "../../lib/utils";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-9 w-full rounded-[8px] border border-border bg-surface px-3 text-[13px] placeholder:text-muted-foreground focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25 disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
