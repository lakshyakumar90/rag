/** Human-readable, honest progress text shared by the Documents UI. */
import type { Document } from "./api/client";

export type ProgressPhase =
  | "uploading"
  | "queued"
  | "reading"
  | "ocr"
  | "chunking"
  | "embedding"
  | "indexing"
  | "ready"
  | "failed";

export type ProgressInfo = {
  label: string;
  detail: string;
  current: number | null;
  total: number | null;
};

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** The phase label and a factual sentence; no color or animation is required. */
export function progressInfo(document: Document): ProgressInfo {
  const stage = document.ingestion_stage;
  if (document.status === "failed") {
    return { label: "Failed", detail: document.error ?? "Indexing failed.", current: null, total: null };
  }
  if (document.status === "ready") {
    const pages = number(document.page_count);
    return {
      label: "Ready",
      detail: `Searchable — ${pages === null ? "unknown" : pages} pages, ${document.chunks_done} chunks indexed`,
      current: document.chunks_done,
      total: document.chunks_total,
    };
  }

  switch (stage) {
    case "uploading": {
      const total = number(document.upload_total);
      const current = number(document.upload_bytes);
      return {
        label: "Uploading",
        detail:
          total !== null && current !== null
            ? `${formatBytes(current)} of ${formatBytes(total)} uploaded`
            : "Uploading file",
        current,
        total,
      };
    }
    case "reading": {
      const total = number(document.pages_total);
      const current = number(document.pages_done);
      return {
        label: "Reading",
        detail:
          total !== null
            ? `Reading page ${Math.min(Math.max(current ?? 1, 1), total)} of ${total}`
            : `Reading pages (${current ?? 0} so far)`,
        current,
        total,
      };
    }
    case "ocr": {
      const total = number(document.ocr_pages_total);
      const current = number(document.ocr_pages_done);
      return {
        label: "OCR",
        detail:
          total !== null
            ? `OCR complete for ${current ?? 0} of ${total} pages`
            : `Running OCR on ${current ?? 0} pages`,
        current,
        total,
      };
    }
    case "chunking": {
      const sections = number(document.sections_total);
      const pages = number(document.pages_total);
      const total = sections ?? pages ?? number(document.chunks_total);
      const current = sections
        ? number(document.sections_done)
        : pages
          ? number(document.pages_done)
          : number(document.chunks_done);
      return {
        label: "Chunking",
        detail:
          total !== null
            ? `Processed ${current ?? 0} of ${total} ${sections ? "sections" : "pages"}, ${document.chunks_done} chunks created`
            : `Created ${document.chunks_done} chunks so far`,
        current,
        total,
      };
    }
    case "embedding": {
      const total = number(document.chunks_total);
      const current = number(document.chunks_embedded);
      return {
        label: "Embedding",
        detail:
          total !== null
            ? `Embedded ${current ?? 0} of ${total} chunks`
            : `Embedded ${current ?? 0} chunks`,
        current,
        total,
      };
    }
    case "indexing": {
      const total = number(document.chunks_total);
      const current = number(document.chunks_indexed);
      return {
        label: "Indexing",
        detail:
          total !== null
            ? `Confirmed ${current ?? 0} of ${total} chunks in the search index`
            : `Confirmed ${current ?? 0} chunks in the search index`,
        current,
        total,
      };
    }
    case "extracting": // legacy v1 rows
      return { label: "Reading", detail: "Reading file", current: null, total: null };
    default:
      return {
        label: "Queued",
        detail: "Waiting for an indexing worker",
        current: null,
        total: null,
      };
  }
}

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
