"use client";

import { Activity, Clock, Database, Layers, Sparkles, X } from "lucide-react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

export type RetrievalChunkDiagnostic = {
  chunk_id: string;
  filename: string;
  page_number?: number | null;
  dense_rank?: number | null;
  lexical_rank?: number | null;
  rrf_score?: number | null;
  rerank_score?: number | null;
  score: number;
};

export type RetrievalDiagnostics = {
  rewritten_query?: string | null;
  retrieval_ms?: number | null;
  reranked?: boolean;
  cache_hit?: boolean;
  chunks?: RetrievalChunkDiagnostic[];
};

type Props = {
  open: boolean;
  diagnostics: RetrievalDiagnostics | null;
  onClose: () => void;
};

export function RetrievalInspectorDrawer({ open, diagnostics, onClose }: Props) {
  if (!open || !diagnostics) return null;

  const chunks = diagnostics.chunks ?? [];

  return (
    <div
      role="dialog"
      aria-label="Retrieval Inspector"
      className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l border-border bg-background/98 shadow-2xl backdrop-blur-md"
    >
      <header className="flex items-center justify-between border-b border-border bg-gradient-to-r from-accent/5 via-transparent to-transparent px-5 py-4">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 text-accent">
            <Activity size={16} />
          </span>
          <div>
            <h2 className="text-sm font-semibold tracking-tight">
              Retrieval Inspector
            </h2>
            <p className="text-[11px] text-muted-foreground">
              Hybrid RRF, cross-encoder scores & stage telemetry
            </p>
          </div>
        </div>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="h-8 w-8 rounded-lg"
          aria-label="Close retrieval inspector"
          onClick={onClose}
        >
          <X size={15} />
        </Button>
      </header>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5 text-sm">
        {/* Telemetry summary grid */}
        <div className="grid grid-cols-3 gap-2.5">
          <div className="rounded-xl border border-border bg-surface p-3">
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Database size={12} /> Cache
            </div>
            <p className="mt-1 text-xs font-semibold text-foreground">
              {diagnostics.cache_hit ? "Redis Hit" : "Live Query"}
            </p>
          </div>
          <div className="rounded-xl border border-border bg-surface p-3">
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Sparkles size={12} /> Scorer
            </div>
            <p className="mt-1 text-xs font-semibold text-foreground">
              {diagnostics.reranked ? "Cross-Encoder" : "Calibrated RRF"}
            </p>
          </div>
          <div className="rounded-xl border border-border bg-surface p-3">
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Clock size={12} /> Latency
            </div>
            <p className="mt-1 font-mono text-xs font-semibold text-foreground">
              {diagnostics.retrieval_ms != null
                ? `${diagnostics.retrieval_ms.toFixed(1)} ms`
                : "—"}
            </p>
          </div>
        </div>

        {/* Rewritten query */}
        {diagnostics.rewritten_query ? (
          <div className="rounded-xl border border-border bg-muted/35 p-3.5">
            <p className="text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
              Effective / Rewritten Query
            </p>
            <p className="mt-1.5 font-mono text-xs leading-relaxed text-foreground">
              {diagnostics.rewritten_query}
            </p>
          </div>
        ) : null}

        {/* Per-chunk score breakdown with visual meters */}
        <div>
          <div className="mb-2.5 flex items-center justify-between">
            <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <Layers size={13} /> Ranked Chunks ({chunks.length})
            </h3>
            <Badge tone="neutral">Top-K Evidence</Badge>
          </div>
          {chunks.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border p-5 text-center text-xs text-muted-foreground">
              No chunks passed the calibrated retrieval gate for this turn.
            </p>
          ) : (
            <div className="space-y-2.5">
              {chunks.map((chunk, idx) => {
                const finalScore =
                  chunk.rerank_score != null ? chunk.rerank_score : chunk.score;
                const barPct = Math.max(
                  4,
                  Math.min(100, Math.round(finalScore * 100)),
                );
                return (
                  <div
                    key={chunk.chunk_id}
                    className="rounded-xl border border-border bg-surface p-3.5 transition-colors hover:border-accent/40"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-accent/15 font-mono text-[11px] font-semibold text-accent">
                          {idx + 1}
                        </span>
                        <span className="truncate text-xs font-semibold text-foreground">
                          {chunk.filename}
                        </span>
                        {chunk.page_number ? (
                          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                            p.{chunk.page_number}
                          </span>
                        ) : null}
                      </div>
                      <span className="font-mono text-xs font-semibold text-foreground">
                        {finalScore.toFixed(3)}
                      </span>
                    </div>

                    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-sky-500 to-emerald-500"
                        style={{ width: `${barPct}%` }}
                      />
                    </div>

                    <div className="mt-2.5 flex flex-wrap gap-3 font-mono text-[11px] text-muted-foreground">
                      <span>
                        Dense:{" "}
                        <strong className="text-foreground">
                          {chunk.dense_rank != null ? `#${chunk.dense_rank}` : "—"}
                        </strong>
                      </span>
                      <span>
                        Lexical:{" "}
                        <strong className="text-foreground">
                          {chunk.lexical_rank != null
                            ? `#${chunk.lexical_rank}`
                            : "—"}
                        </strong>
                      </span>
                      <span>
                        RRF:{" "}
                        <strong className="text-foreground">
                          {chunk.rrf_score != null
                            ? chunk.rrf_score.toFixed(4)
                            : "—"}
                        </strong>
                      </span>
                      {chunk.rerank_score != null ? (
                        <span>
                          Rerank:{" "}
                          <strong className="text-emerald-600 dark:text-emerald-400">
                            {chunk.rerank_score.toFixed(3)}
                          </strong>
                        </span>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
