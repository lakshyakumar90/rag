"use client";

import { useState } from "react";
import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";

export type ConfidenceBreakdown = {
  top_retrieval_score?: number | null;
  reranked?: boolean;
  citation_coverage?: number | null;
  faithfulness?: number | null;
  abstained?: boolean;
};

type Props = {
  level?: string | null;
  score?: number | null;
  breakdown?: ConfidenceBreakdown | null;
};

function pct(val: number | null | undefined): string {
  if (val === null || val === undefined || Number.isNaN(val)) return "—";
  return `${Math.round(val * 100)}%`;
}

function Meter({ value, tone }: { value?: number | null; tone: string }) {
  const width =
    value === null || value === undefined || Number.isNaN(value)
      ? 0
      : Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
      <div
        className={`h-full rounded-full transition-all duration-300 ${tone}`}
        style={{ width: `${width}%` }}
      />
    </div>
  );
}

export function ConfidenceBadge({ level, score, breakdown }: Props) {
  const [open, setOpen] = useState(false);
  if (!level && score === undefined) return null;

  const norm = (level || "medium").toLowerCase();
  const styles =
    norm === "high"
      ? "border-emerald-500/35 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/15 dark:text-emerald-300"
      : norm === "low"
        ? "border-rose-500/35 bg-rose-500/10 text-rose-700 hover:bg-rose-500/15 dark:text-rose-300"
        : "border-amber-500/35 bg-amber-500/10 text-amber-700 hover:bg-amber-500/15 dark:text-amber-300";

  const barTone =
    norm === "high"
      ? "bg-emerald-500"
      : norm === "low"
        ? "bg-rose-500"
        : "bg-amber-500";

  const Icon =
    norm === "high"
      ? ShieldCheck
      : norm === "low"
        ? ShieldAlert
        : ShieldQuestion;

  const label = norm === "high" ? "High" : norm === "low" ? "Low" : "Medium";

  return (
    <div
      className="relative inline-block"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Answer confidence: ${label}`}
        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium tracking-tight transition-all ${styles}`}
      >
        <Icon size={12} />
        <span>{label}</span>
        {typeof score === "number" ? (
          <span className="font-mono text-[10.5px] opacity-85">
            {pct(score)}
          </span>
        ) : null}
      </button>

      {open && breakdown ? (
        <div
          role="tooltip"
          className="absolute bottom-full left-0 z-40 mb-2 w-64 rounded-2xl border border-border/80 bg-background/95 p-3.5 text-xs shadow-xl backdrop-blur-md"
        >
          <div className="flex items-center justify-between">
            <p className="font-semibold text-foreground">Answer Confidence</p>
            <span className="font-mono text-[11px] font-semibold text-foreground">
              {pct(score)}
            </span>
          </div>

          <div className="mt-3 space-y-2.5 text-muted-foreground">
            <div>
              <div className="flex justify-between text-[11px]">
                <span>
                  {breakdown.reranked ? "Cross-Encoder Rerank" : "Top Retrieval"}
                </span>
                <span className="font-mono text-foreground">
                  {pct(breakdown.top_retrieval_score)}
                </span>
              </div>
              <Meter value={breakdown.top_retrieval_score} tone={barTone} />
            </div>

            <div>
              <div className="flex justify-between text-[11px]">
                <span>Citation Coverage</span>
                <span className="font-mono text-foreground">
                  {pct(breakdown.citation_coverage)}
                </span>
              </div>
              <Meter value={breakdown.citation_coverage} tone="bg-sky-500" />
            </div>

            {breakdown.faithfulness !== null &&
            breakdown.faithfulness !== undefined ? (
              <div>
                <div className="flex justify-between text-[11px]">
                  <span>Faithfulness Judge</span>
                  <span className="font-mono text-foreground">
                    {pct(breakdown.faithfulness)}
                  </span>
                </div>
                <Meter value={breakdown.faithfulness} tone="bg-violet-500" />
              </div>
            ) : null}

            {breakdown.abstained ? (
              <p className="rounded-lg border border-rose-500/20 bg-rose-500/5 px-2.5 py-1.5 text-[11px] text-rose-600 dark:text-rose-400">
                Abstained: top retrieval score fell below calibrated threshold.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
