"use client";

import { useState } from "react";
import { BookOpen, ExternalLink, FileCode2, FileText, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { RowSkeleton } from "./ui/skeleton";

export type CitationSource = {
  number: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  page_number?: number | null;
  heading_path?: string[] | null;
  excerpt?: string | null;
  char_start?: number | null;
  char_end?: number | null;
  dense_rank?: number | null;
  lexical_rank?: number | null;
  rrf_score?: number | null;
  rerank_score?: number | null;
};

type SnippetData = {
  text: string;
  page_number?: number | null;
  heading_path?: string[] | null;
};

type Props = {
  source: CitationSource | null;
  snippet?: SnippetData;
  isPending: boolean;
  isError: boolean;
  downloadUrl?: string | null;
  onRetry: () => void;
  onClose: () => void;
};

export function CitationSplitViewer({
  source,
  snippet,
  isPending,
  isError,
  downloadUrl,
  onRetry,
  onClose,
}: Props) {
  const [viewMode, setViewMode] = useState<"excerpt" | "pdf">("excerpt");
  if (!source) return null;

  const isPdf = source.filename.toLowerCase().endsWith(".pdf");
  const isCode = /\.(py|ts|tsx|js|jsx|json|yml|yaml|sql|sh|go|rs)$/i.test(
    source.filename,
  );
  const pageNum = snippet?.page_number ?? source.page_number ?? null;
  const headings = snippet?.heading_path ?? source.heading_path ?? [];
  const passage = snippet?.text ?? source.excerpt ?? "";
  const pdfSrc =
    isPdf && downloadUrl
      ? `${downloadUrl}${pageNum ? `#page=${pageNum}` : ""}`
      : null;

  return (
    <aside
      aria-label="Interactive document citation viewer"
      className="flex h-full min-h-0 flex-col border-l border-border bg-background"
    >
      <header className="flex shrink-0 items-start justify-between gap-3 border-b border-border px-4 py-3.5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent">[{source.number}]</Badge>
            <h2 className="truncate text-sm font-semibold text-foreground">
              {source.filename}
            </h2>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {pageNum ? (
              <span className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                <BookOpen size={11} /> Page {pageNum}
              </span>
            ) : null}
            {headings.length > 0 ? (
              <span className="truncate">{headings.join(" › ")}</span>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {isPdf && pdfSrc ? (
            <div className="mr-1 inline-flex rounded-lg border border-border p-0.5 text-[11px]">
              <button
                type="button"
                onClick={() => setViewMode("excerpt")}
                className={`rounded-md px-2 py-0.5 ${
                  viewMode === "excerpt"
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Excerpt
              </button>
              <button
                type="button"
                onClick={() => setViewMode("pdf")}
                className={`rounded-md px-2 py-0.5 ${
                  viewMode === "pdf"
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                PDF Page
              </button>
            </div>
          ) : null}
          {downloadUrl ? (
            <a
              href={pdfSrc || downloadUrl}
              target="_blank"
              rel="noreferrer"
              title="Open original document"
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <ExternalLink size={14} />
            </a>
          ) : null}
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            aria-label="Close citation viewer"
            onClick={onClose}
          >
            <X size={15} />
          </Button>
        </div>
      </header>

      {/* Per-chunk retrieval diagnostic bar */}
      {(source.rerank_score != null ||
        source.rrf_score != null ||
        source.dense_rank != null ||
        source.lexical_rank != null) && (
        <div className="flex flex-wrap items-center gap-3 border-b border-border bg-muted/40 px-4 py-2 text-[11px] text-muted-foreground">
          {source.rerank_score != null && (
            <span>
              Rerank:{" "}
              <strong className="font-mono text-foreground">
                {source.rerank_score.toFixed(3)}
              </strong>
            </span>
          )}
          {source.rrf_score != null && (
            <span>
              RRF:{" "}
              <strong className="font-mono text-foreground">
                {source.rrf_score.toFixed(4)}
              </strong>
            </span>
          )}
          {source.dense_rank != null && (
            <span>
              Dense{" "}
              <strong className="font-mono text-foreground">
                #{source.dense_rank}
              </strong>
            </span>
          )}
          {source.lexical_rank != null && (
            <span>
              Lexical{" "}
              <strong className="font-mono text-foreground">
                #{source.lexical_rank}
              </strong>
            </span>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {isPending ? (
          <RowSkeleton lines={5} />
        ) : isError ? (
          <div className="space-y-3 rounded-xl border border-border p-4">
            <p className="text-sm text-muted-foreground">
              This source passage could not be loaded. The document may have been
              re-indexed or your permissions may have changed.
            </p>
            <Button size="sm" variant="outline" onClick={onRetry}>
              Retry
            </Button>
          </div>
        ) : viewMode === "pdf" && pdfSrc ? (
          <iframe
            title={`${source.filename} page ${pageNum ?? 1}`}
            src={pdfSrc}
            className="h-full min-h-[520px] w-full rounded-xl border border-border bg-white"
          />
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              {isCode ? <FileCode2 size={14} /> : <FileText size={14} />}
              <span>Matched Source Passage</span>
              {source.char_start != null && source.char_end != null ? (
                <span className="ml-auto font-mono text-[11px]">
                  chars {source.char_start}–{source.char_end}
                </span>
              ) : null}
            </div>
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-[13.5px] leading-7 text-foreground">
              {isCode ? (
                <pre className="overflow-x-auto font-mono text-xs leading-6">
                  <code>{passage}</code>
                </pre>
              ) : (
                <div className="prose prose-sm max-w-none dark:prose-invert">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {passage}
                  </ReactMarkdown>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
