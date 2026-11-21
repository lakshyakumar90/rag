import * as React from "react";
import { cn } from "../../lib/utils";

type Tone = "neutral" | "accent" | "success" | "warning" | "destructive";

const tones: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  accent: "bg-accent/12 text-accent",
  success: "bg-success/12 text-success",
  warning: "bg-warning/12 text-warning",
  destructive: "bg-destructive/12 text-destructive",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center rounded-full px-2 text-[11px] font-medium",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}
