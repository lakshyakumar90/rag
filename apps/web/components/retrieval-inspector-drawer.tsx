"use client";

import { Activity, Clock, Database, Sparkles, X } from "lucide-react";
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
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-xl flex-col border-l border-border bg-background shadow-2xl"
    >
      <header className="flex items-center justify-between border-b border-border px-5 py-4">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-accent" />
          <h2 className="text-sm font-semibold">Retrieval Inspector</h2>
        </div>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="h-7 w-7"
          aria-label="Close retrieval inspector"
          onClick={onClose}
        >
          <X size={15} />
        </Button>
      </header>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5 text-sm">
        {/* Stage summary badges */}
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={diagnostics.cache_hit ? "accent" : "neutral"}>
            <Database size={11} className="mr-1" />
            {diagnostics.cache_hit ? "Cache Hit" : "Cache Miss"}
          </Badge>
          <Badge tone={diagnostics.reranked ? "accent" : "neutral"}>
            <Sparkles size={11} className="mr-1" />
            {diagnostics.reranked ? "Cross-Encoder Reranked" : "RRF Fallback"}
          </Badge>
          {diagnostics.retrieval_ms != null ? (
            <Badge tone="neutral">
              <Clock size={11} className="mr-1" />
              {diagnostics.retrieval_ms.toFixed(1)} ms
            </Badge>
          ) : null}
        </div>

        {/* Rewritten query */}
        {diagnostics.rewritten_query ? (
          <div className="rounded-xl border border-border bg-muted/30 p-3.5">
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Effective / Rewritten Query
            </p>
            <p className="mt-1 font-mono text-xs text-foreground">
              {diagnostics.rewritten_query}
            </p>
          </div>
        ) : null}

        {/* Per-chunk score breakdown */}
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Candidate Chunks ({chunks.length})
          </h3>
          {chunks.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border p-4 text-xs text-muted-foreground">
              No chunks passed the retrieval threshold for this turn.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-border">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-border bg-muted/40 text-[11px] text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">#</th>
                    <th className="px-3 py-2 font-medium">Document</th>
                    <th className="px-3 py-2 text-right font-medium">Dense</th>
                    <th className="px-3 py-2 text-right font-medium">Lexical</th>
                    <th className="px-3 py-2 text-right font-medium">RRF</th>
                    <th className="px-3 py-2 text-right font-medium">Rerank</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border font-mono">
                  {chunks.map((chunk, idx) => (
                    <tr key={chunk.chunk_id} className="hover:bg-muted/30">
                      <td className="px-3 py-2 text-muted-foreground">{idx + 1}</td>
                      <td className="max-w-[180px] truncate px-3 py-2 font-sans">
                        <span className="font-medium text-foreground">
                          {chunk.filename}
                        </span>
                        {chunk.page_number ? (
                          <span className="ml-1 text-[11px] text-muted-foreground">
                            p.{chunk.page_number}
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {chunk.dense_rank != null ? `#${chunk.dense_rank}` : "—"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {chunk.lexical_rank != null ? `#${chunk.lexical_rank}` : "—"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {chunk.rrf_score != null ? chunk.rrf_score.toFixed(4) : "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-semibold text-foreground">
                        {chunk.rerank_score != null
                          ? chunk.rerank_score.toFixed(3)
                          : chunk.score.toFixed(3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
