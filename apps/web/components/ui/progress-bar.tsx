/** Accessible progress bar: text always accompanies the visual indicator. */
export function ProgressBar({
  percent,
  label,
  className = "",
}: {
  percent: number | null | undefined;
  label: string;
  className?: string;
}) {
  const known = typeof percent === "number" && Number.isFinite(percent);
  const value = known ? Math.max(0, Math.min(100, percent as number)) : null;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value === null ? undefined : Math.round(value)}
      aria-valuetext={value === null ? `${label} — total not known yet` : `${Math.round(value)}% — ${label}`}
      className={`h-1.5 w-full overflow-hidden rounded-full bg-muted ${className}`}
    >
      <div
        className={
          value === null
            ? "progress-indeterminate h-full w-1/3 rounded-full bg-accent"
            : "h-full rounded-full bg-accent transition-[width] duration-200"
        }
        style={value === null ? undefined : { width: `${value}%` }}
      />
    </div>
  );
}
