"use client";

import { useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudUpload, RotateCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../../../../components/ui/button";
import { Input } from "../../../../components/ui/input";
import { RowSkeleton } from "../../../../components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../../../components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "../../../../components/ui/tooltip";
import { api, type Document } from "../../../../lib/api/client";
import { uploadWithProgress } from "../../../../lib/auth-client";

// Status is text, not color. One neutral family; the blue signal stays for
// active/focus/primary actions only.
const STATUS: Record<string, string> = {
  pending: "queued",
  processing: "indexing",
  ready: "ready",
  failed: "failed",
};

export default function DocumentsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [filter, setFilter] = useState("all");
  const [uploads, setUploads] = useState<{ name: string; progress: number }[]>([]);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["documents", workspaceId, filter],
    queryFn: () => api.documents(workspaceId, filter === "all" ? undefined : filter),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((item) => item.status === "pending" || item.status === "processing")
        ? 1500
        : false;
    },
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteDocument(workspaceId, id),
    onSuccess: () => {
      toast.success("Document removed");
      invalidate();
    },
    onError: () => toast.error("Could not remove the document"),
  });
  const retry = useMutation({
    mutationFn: (id: string) => api.reindexDocument(workspaceId, id),
    onSuccess: () => {
      toast.success("Re-indexing started");
      invalidate();
    },
    onError: () => toast.error("Could not start re-indexing"),
  });

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    for (const file of Array.from(files)) {
      const entry = { name: file.name, progress: 0 };
      setUploads((current) => [...current, entry]);
      try {
        await uploadWithProgress<Document>(
          `/workspaces/${workspaceId}/documents`,
          file,
          (progress) =>
            setUploads((current) =>
              current.map((item) => (item === entry ? { ...item, progress } : item)),
            ),
        );
        toast.success(`${file.name} uploaded`);
        invalidate();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : `Upload failed: ${file.name}`);
      } finally {
        setUploads((current) => current.filter((item) => item !== entry));
      }
    }
  }

  const active = data?.items.some(
    (item) => item.status === "pending" || item.status === "processing",
  );

  return (
    <div className="flex flex-col gap-6">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void upload(event.dataTransfer.files);
        }}
        className={`flex flex-col items-center justify-center gap-3 rounded-[10px] border border-dashed px-4 py-10 text-center transition-colors sm:py-14 ${
          dragging ? "border-accent bg-accent/5" : "border-border"
        }`}
      >
        <CloudUpload size={20} className="text-muted-foreground" />
        <p className="text-[13px]">Drop PDF, DOCX, TXT or MD files here</p>
        <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()}>
          Choose files
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          className="hidden"
          onChange={(event) => void upload(event.target.files)}
        />
      </div>

      {uploads.length ? (
        <div className="result-in flex flex-col gap-2">
          {uploads.map((item) => (
            <div key={item.name} className="flex items-center gap-3 text-[12px]">
              <span className="w-40 truncate sm:w-64">{item.name}</span>
              <div className="h-1 flex-1 rounded-full bg-muted">
                <div
                  className="h-1 rounded-full bg-accent transition-[width] duration-200"
                  style={{ width: `${item.progress}%` }}
                />
              </div>
              <span data-numeric className="w-9 text-right text-muted-foreground">
                {item.progress}%
              </span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="flex items-center gap-3 border-b border-border pb-2">
        <span className="text-[12px] text-muted-foreground">
          {data?.total ?? 0} files
        </span>
        {active ? (
          <span className="text-[11px] text-muted-foreground">Updating status…</span>
        ) : null}
        <div className="ml-auto w-36">
          <Select value={filter} onValueChange={setFilter}>
            <SelectTrigger className="h-8" aria-label="Filter by status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="pending">Queued</SelectItem>
              <SelectItem value="processing">Indexing</SelectItem>
              <SelectItem value="ready">Ready</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {isLoading ? (
        <div>
          <RowSkeleton lines={1} />
          <RowSkeleton lines={1} />
          <RowSkeleton lines={1} />
        </div>
      ) : data?.items.length ? (
        <div className="result-in">
          {data.items.map((document) => {
            const status = STATUS[document.status] ?? document.status;
            return (
              <div
                key={document.id}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-2 py-3.5"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium">{document.filename}</p>
                  <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                    {(document.size / 1024).toFixed(1)} KB · {document.page_count ?? "—"} pages ·{" "}
                    {document.chunks_done}/{document.chunks_total} chunks
                  </p>
                  {(document.status === "pending" || document.status === "processing") &&
                  document.chunks_total > 0 ? (
                    <div className="mt-2 h-0.5 w-full max-w-xs rounded-full bg-muted">
                      <div
                        className="h-0.5 rounded-full bg-foreground"
                        style={{
                          width: `${Math.round((document.chunks_done / document.chunks_total) * 100)}%`,
                        }}
                      />
                    </div>
                  ) : null}
                  {document.error ? (
                    <p className="mt-1 text-[11px] font-medium text-foreground">
                      Error — {document.error}
                    </p>
                  ) : null}
                </div>
                <span
                  data-numeric
                  className={`flex items-center gap-1.5 text-[10px] uppercase tracking-wide ${
                    document.status === "failed"
                      ? "font-semibold text-foreground"
                      : "text-muted-foreground"
                  }`}
                >
                  <span
                    aria-hidden
                    className={`h-1.5 w-1.5 rounded-full ${
                      document.status === "failed"
                        ? "bg-foreground"
                        : "bg-muted-foreground"
                    }`}
                  />
                  {status}
                </span>
                <div className="flex items-center gap-1">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Re-index ${document.filename}`}
                        onClick={() => retry.mutate(document.id)}
                      >
                        <RotateCw size={15} />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Re-index</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete ${document.filename}`}
                        onClick={() => remove.mutate(document.id)}
                      >
                        <Trash2 size={15} />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Delete</TooltipContent>
                  </Tooltip>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="py-16 text-center">
          <p className="text-[14px]">Nothing uploaded yet.</p>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Add a file above, then ask a question in Chat.
          </p>
        </div>
      )}
    </div>
  );
}
