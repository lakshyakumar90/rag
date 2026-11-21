"use client";

import { useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "../../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../../components/ui/card";
import { Skeleton } from "../../../../components/ui/skeleton";
import { api, type Document } from "../../../../lib/api/client";
import { uploadWithProgress } from "../../../../lib/auth-client";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-muted text-muted-foreground",
  processing: "bg-blue-500/15 text-blue-600",
  ready: "bg-emerald-500/15 text-emerald-600",
  failed: "bg-destructive/15 text-destructive",
};

export default function DocumentsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploads, setUploads] = useState<{ name: string; progress: number }[]>([]);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["documents", workspaceId],
    queryFn: () => api.documents(workspaceId),
    // Poll only while ingestion is in flight; stop once everything settles.
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some(
        (item) => item.status === "pending" || item.status === "processing",
      )
        ? 1500
        : false;
    },
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });
  const remove = useMutation({
    mutationFn: (documentId: string) => api.deleteDocument(workspaceId, documentId),
    onSuccess: () => { toast.success("Document deleted"); invalidate(); },
    onError: () => toast.error("Could not delete document"),
  });
  const retry = useMutation({
    mutationFn: (documentId: string) => api.reindexDocument(workspaceId, documentId),
    onSuccess: () => { toast.success("Re-indexing started"); invalidate(); },
    onError: () => toast.error("Could not retry ingestion"),
  });

  async function upload(files: FileList | null) {
    if (!files) return;
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

  return (
    <div className="flex flex-col gap-6">
      <div
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          upload(event.dataTransfer.files);
        }}
        className={`rounded-lg border-2 border-dashed p-10 text-center transition-colors ${
          dragging ? "border-primary bg-primary/5" : "border-border"
        }`}
      >
        <p className="mb-3 text-muted-foreground">Drop PDF, DOCX, TXT or MD files here</p>
        <Button onClick={() => inputRef.current?.click()}>Choose files</Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          className="hidden"
          onChange={(event) => upload(event.target.files)}
        />
      </div>

      {uploads.length ? (
        <div className="flex flex-col gap-2">
          {uploads.map((item) => (
            <div key={item.name} className="text-sm">
              {item.name}: {item.progress}%
              <div className="h-1 rounded bg-muted">
                <div className="h-1 rounded bg-primary" style={{ width: `${item.progress}%` }} />
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {!isLoading && isFetching ? (
        <p className="text-xs text-muted-foreground">Checking document status…</p>
      ) : null}

      {isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : data?.items.length ? (
        <div className="flex flex-col gap-3">
          {data.items.map((document) => (
            <Card key={document.id}>
              <CardHeader className="flex-row items-center justify-between gap-4">
                <div>
                  <CardTitle className="text-base">{document.filename}</CardTitle>
                  <p className="text-xs text-muted-foreground">
                    {(document.size / 1024).toFixed(1)} KB · {document.page_count ?? "—"} pages ·{" "}
                    {document.chunks_done}/{document.chunks_total} chunks
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`rounded-full px-2 py-1 text-xs ${STATUS_COLORS[document.status] ?? ""}`}>
                    {document.status}
                  </span>
                  <Button variant="outline" size="sm" onClick={() => retry.mutate(document.id)}>
                    Retry
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => remove.mutate(document.id)}
                  >
                    Delete
                  </Button>
                </div>
              </CardHeader>
              {(document.status === "pending" || document.status === "processing") &&
              document.chunks_total > 0 ? (
                <CardContent>
                  <div className="h-1 rounded bg-muted">
                    <div
                      className="h-1 rounded bg-primary"
                      style={{
                        width: `${Math.round((document.chunks_done / document.chunks_total) * 100)}%`,
                      }}
                    />
                  </div>
                </CardContent>
              ) : null}
              {document.error ? (
                <CardContent className="text-sm text-destructive">{document.error}</CardContent>
              ) : null}
            </Card>
          ))}
        </div>
      ) : (
        <Card><CardContent className="py-10 text-center text-muted-foreground">
          No documents yet. Upload one to start asking questions.
        </CardContent></Card>
      )}
    </div>
  );
}
