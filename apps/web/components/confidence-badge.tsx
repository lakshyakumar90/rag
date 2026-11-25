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

export function ConfidenceBadge({ level, score, breakdown }: Props) {
  const [open, setOpen] = useState(false);
  if (!level && score === undefined) return null;

  const norm = (level || "medium").toLowerCase();
  const styles =
    norm === "high"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : norm === "low"
        ? "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300"
        : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300";

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
        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors ${styles}`}
      >
        <Icon size={12} />
        <span>
          {label}
          {typeof score === "number" ? ` · ${pct(score)}` : ""}
        </span>
      </button>

      {open && breakdown ? (
        <div
          role="tooltip"
          className="absolute bottom-full left-0 z-30 mb-1.5 w-60 rounded-xl border border-border bg-background p-3 text-xs shadow-lg"
        >
          <p className="font-semibold text-foreground">Confidence Breakdown</p>
          <dl className="mt-2 space-y-1 text-muted-foreground">
            <div className="flex justify-between">
              <dt>{breakdown.reranked ? "Top Rerank Score" : "Top Retrieval Score"}</dt>
              <dd className="font-mono text-foreground">
                {pct(breakdown.top_retrieval_score)}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt>Citation Coverage</dt>
              <dd className="font-mono text-foreground">
                {pct(breakdown.citation_coverage)}
              </dd>
            </div>
            {breakdown.faithfulness !== null &&
            breakdown.faithfulness !== undefined ? (
              <div className="flex justify-between">
                <dt>Faithfulness Judge</dt>
                <dd className="font-mono text-foreground">
                  {pct(breakdown.faithfulness)}
                </dd>
              </div>
            ) : null}
            {breakdown.abstained ? (
              <p className="pt-1 text-[11px] text-rose-600 dark:text-rose-400">
                Abstained: retrieval score fell below calibrated threshold.
              </p>
            ) : null}
          </dl>
        </div>
      ) : null}
    </div>
  );
}
