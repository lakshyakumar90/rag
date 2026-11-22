"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CloudUpload, FileText, Link2, RotateCw, ShieldCheck, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../../../../components/ui/button";
import { Input } from "../../../../components/ui/input";
import { RowSkeleton } from "../../../../components/ui/skeleton";
import { ProgressBar } from "../../../../components/ui/progress-bar";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "../../../../components/ui/dialog";
import { api, type Document } from "../../../../lib/api/client";
import { formatBytes, progressInfo } from "../../../../lib/progress";
import { uploadWithProgress } from "../../../../lib/auth-client";

// Status is text, not color. The blue signal stays for active/focus/primary actions.
const STATUS: Record<string, string> = {
  pending: "queued",
  processing: "indexing",
  ready: "ready",
  failed: "failed",
};

type UploadItem = { id: number; name: string; progress: number; size: number };

export default function DocumentsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const nextUploadId = useRef(0);
  const [dragging, setDragging] = useState(false);
  const [filter, setFilter] = useState("all");
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [grantTarget, setGrantTarget] = useState<Document | null>(null);
  const [sourceType, setSourceType] = useState<"url" | "github">("url");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceOwner, setSourceOwner] = useState("");
  const [sourceRepo, setSourceRepo] = useState("");
  const [sourceRef, setSourceRef] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["documents", workspaceId, filter],
    queryFn: () => api.documents(workspaceId, filter === "all" ? undefined : filter),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      if (items.some((item) => item.status === "processing")) return 700;
      return items.some((item) => item.status === "pending") ? 1500 : false;
    },
    refetchIntervalInBackground: true,
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
  const importSource = useMutation({
    mutationFn: () =>
      sourceType === "url"
        ? api.createSource(workspaceId, { type: "url", url: sourceUrl.trim(), max_depth: 1 })
        : api.createSource(workspaceId, {
            type: "github",
            owner: sourceOwner.trim(),
            repo: sourceRepo.trim(),
            ref: sourceRef.trim() || undefined,
            max_depth: 1,
          }),
    onSuccess: () => {
      toast.success("Source import started");
      setSourceUrl("");
      invalidate();
    },
    onError: () => toast.error("Could not import that source"),
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
      const entry: UploadItem = {
        id: nextUploadId.current++,
        name: file.name,
        progress: 0,
        size: file.size,
      };
      setUploads((current) => [...current, entry]);
      try {
        await uploadWithProgress<Document>(
          `/workspaces/${workspaceId}/documents`,
          file,
          (progress) =>
            setUploads((current) =>
              current.map((item) => (item.id === entry.id ? { ...item, progress } : item)),
            ),
        );
        toast.success(`${file.name} uploaded`);
        invalidate();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : `Upload failed: ${file.name}`);
      } finally {
        setUploads((current) => current.filter((item) => item.id !== entry.id));
      }
    }
  }

  const active = data?.items.some(
    (item) => item.status === "pending" || item.status === "processing",
  );

  return (
    <div className="mx-auto flex w-full max-w-[76rem] flex-col gap-6">
      <div className="grid items-stretch gap-3 xl:grid-cols-[minmax(16rem,0.85fr)_minmax(0,1.5fr)]">
      <section
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
        className={`flex flex-col justify-between gap-4 rounded-xl border border-dashed bg-surface/60 p-4 transition-colors sm:p-5 ${
          dragging ? "border-accent bg-accent/5" : "border-border"
        }`}
      >
        <div className="flex items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent"><CloudUpload size={17} /></span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">Upload files</h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">Drop files here or choose PDF, DOCX, TXT, Markdown, or a Notion ZIP.</p>
          </div>
        </div>
        <Button variant="outline" size="sm" className="self-start px-3" onClick={() => inputRef.current?.click()}>
          Choose files
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md,.zip"
          className="hidden"
          onChange={(event) => void upload(event.target.files)}
        />
      </section>

      <section className="min-w-0 rounded-xl border border-border bg-surface/60 p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent"><Link2 size={17} /></span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">Import a source</h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">Add a public webpage or GitHub repository.</p>
          </div>
        </div>
        <form className="mt-4 grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 sm:flex"
          onSubmit={(event) => {
            event.preventDefault();
            if (!importSource.isPending && (sourceType === "url" ? sourceUrl.trim() : sourceOwner.trim() && sourceRepo.trim())) importSource.mutate();
          }}>
          <Select value={sourceType} onValueChange={(value) => setSourceType(value as "url" | "github")}>
            <SelectTrigger aria-label="Source type" className="col-span-2 h-9 w-full min-w-0 sm:w-28 sm:shrink-0">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="url">URL</SelectItem>
              <SelectItem value="github">GitHub</SelectItem>
            </SelectContent>
          </Select>
          {sourceType === "url" ? (
            <Input
              aria-label="Source URL"
              type="url"
              placeholder="https://example.com/guide"
              className="h-9 w-full min-w-0 flex-1"
              value={sourceUrl}
              onChange={(event) => setSourceUrl(event.target.value)}
            />
          ) : (
            <div className="col-span-2 grid min-w-0 flex-1 grid-cols-2 gap-2 lg:grid-cols-3">
              <Input aria-label="Repository owner" placeholder="owner" className="h-9 min-w-0" value={sourceOwner} onChange={(event) => setSourceOwner(event.target.value)} />
              <Input aria-label="Repository name" placeholder="repo" className="h-9 min-w-0" value={sourceRepo} onChange={(event) => setSourceRepo(event.target.value)} />
              <Input aria-label="Repository ref" placeholder="main (optional)" className="col-span-2 h-9 min-w-0 lg:col-span-1" value={sourceRef} onChange={(event) => setSourceRef(event.target.value)} />
            </div>
          )}
          <Button
            type="submit" size="sm" className="h-9 shrink-0 gap-1.5 px-3"
            disabled={
              importSource.isPending ||
              (sourceType === "url" ? !sourceUrl.trim() : !sourceOwner.trim() || !sourceRepo.trim())
            }
          >
            {importSource.isPending ? "Importing…" : "Import"} <ArrowRight size={13} />
          </Button>
        </form>
      </section>
      </div>

      {uploads.length ? (
        <section aria-label="Upload progress" className="result-in flex flex-col gap-2">
          {uploads.map((item) => {
            const uploaded = Math.round((item.progress / 100) * item.size);
            const text = `${item.name}: uploaded ${formatBytes(uploaded)} of ${formatBytes(item.size)} (${item.progress}%)`;
            return (
              <div key={item.id} className="flex flex-col gap-1.5 text-[12px]">
                <span className="truncate">{text}</span>
                <ProgressBar percent={item.progress} label={text} />
              </div>
            );
          })}
        </section>
      ) : null}

      <div className="flex items-center gap-3 border-b border-border pb-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold tracking-tight">Library</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{data?.total ?? 0} {(data?.total ?? 0) === 1 ? "file" : "files"}</p>
        </div>
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
          {data.items.map((document) => (
            <DocumentRow
              key={document.id}
              document={document}
              retrying={retry.isPending}
              onRetry={() => retry.mutate(document.id)}
              onDelete={() => remove.mutate(document.id)}
              onPermissions={() => setGrantTarget(document)}
            />
          ))}
        </div>
      ) : (
        <div className="py-16 text-center">
          <p className="text-[14px]">Nothing uploaded yet.</p>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Add a file above, then ask a question in Chat.
          </p>
        </div>
      )}
      {grantTarget ? (
        <GrantsDialog
          workspaceId={workspaceId}
          document={grantTarget}
          onClose={() => setGrantTarget(null)}
          onSaved={invalidate}
        />
      ) : null}
    </div>
  );
}

function DocumentRow({
  document,
  retrying,
  onRetry,
  onDelete,
  onPermissions,
}: {
  document: Document;
  retrying: boolean;
  onRetry: () => void;
  onDelete: () => void;
  onPermissions: () => void;
}) {
  const status = STATUS[document.status] ?? document.status;
  const info = progressInfo(document);
  const active = document.status === "pending" || document.status === "processing";
  const unreadable = document.unreadable_pages ?? [];

  return (
    <div className="grid items-center gap-3 border-b border-border py-3 first:pt-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-4 sm:py-4">
      <div className="flex min-w-0 items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-border bg-surface text-muted-foreground"><FileText size={16} /></span>
        <div className="min-w-0 flex-1">
        <p className="text-sm font-medium leading-5 [overflow-wrap:anywhere]">{document.filename}</p>
        <p className="mt-1 text-xs tabular-nums text-muted-foreground">
          {[
            formatBytes(document.size),
            document.page_count == null ? null : `${document.page_count} ${document.page_count === 1 ? "page" : "pages"}`,
            document.status === "ready" ? `${document.chunks_done} ${document.chunks_done === 1 ? "chunk" : "chunks"} indexed` : null,
          ].filter(Boolean).join(" · ")}
        </p>
        {active ? (
          <div className="mt-2 grid max-w-md gap-1.5">
            <div className="flex flex-wrap justify-between gap-x-3 text-xs">
              <span className="font-medium">{info.label}</span>
              <span className="tabular-nums text-muted-foreground">
                {info.current !== null && info.total !== null
                  ? `${info.current} / ${info.total}`
                  : "total not known yet"}
              </span>
            </div>
            <p className="text-[11px] text-muted-foreground">{info.detail}</p>
            <ProgressBar
              percent={document.progress_percent}
              label={`${document.filename}: ${info.label}. ${info.detail}`}
            />
          </div>
        ) : null}
        {document.status === "failed" ? (
          <div className="mt-2">
            <p role="alert" className="text-[11px] font-medium text-foreground">
              Error — {document.error ?? "Indexing failed."}
            </p>
            <Button variant="outline" size="sm" className="mt-2" disabled={retrying} onClick={onRetry}>
              <RotateCw size={13} /> Retry indexing
            </Button>
          </div>
        ) : null}
        {unreadable.length ? (
          <div className="mt-1 text-[11px] text-muted-foreground">
            <p>Unreadable pages: {unreadable.join(", ")} (OCR could not recover text)</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              disabled={retrying}
              onClick={onRetry}
            >
              <RotateCw size={13} /> Retry OCR
            </Button>
          </div>
        ) : null}
        </div>
      </div>
      <div className="ml-12 flex min-w-0 items-center justify-between gap-2 sm:ml-0 sm:gap-3">
        <span className={`flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs capitalize ${document.status === "ready" ? "text-success" : "text-muted-foreground"}`}>
          <span aria-hidden className="size-1.5 rounded-full bg-current" />{status}
        </span>
        <div className="flex shrink-0 items-center gap-0.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Permissions for ${document.filename}`}
              onClick={onPermissions}
            >
              <ShieldCheck size={15} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Permissions</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Re-index ${document.filename}`}
              disabled={document.status === "processing" || retrying}
              onClick={onRetry}
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
              onClick={onDelete}
            >
              <Trash2 size={15} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Delete</TooltipContent>
        </Tooltip>
        </div>
      </div>
    </div>
  );
}

function GrantsDialog({
  workspaceId,
  document,
  onClose,
  onSaved,
}: {
  workspaceId: string;
  document: Document;
  onClose: () => void;
  onSaved: () => void;
}) {
  const members = useQuery({
    queryKey: ["members", workspaceId],
    queryFn: () => api.members(workspaceId),
  });
  const grants = useQuery({
    queryKey: ["grants", workspaceId, document.id],
    queryFn: () => api.documentGrants(workspaceId, document.id),
  });
  const [restricted, setRestricted] = useState(grants.data?.restricted ?? document.restricted);
  const [selected, setSelected] = useState<string[]>(grants.data?.user_ids ?? []);

  useEffect(() => {
    if (grants.data) {
      setRestricted(grants.data.restricted);
      setSelected(grants.data.user_ids);
    }
  }, [grants.data]);

  const save = useMutation({
    mutationFn: () =>
      api.updateDocumentGrants(workspaceId, document.id, restricted, selected),
    onSuccess: () => {
      toast.success("Permissions saved");
      onSaved();
      onClose();
    },
    onError: () => toast.error("Could not save permissions"),
  });

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="p-5">
        <DialogTitle className="text-[14px] font-semibold">
          Permissions for {document.filename}
        </DialogTitle>
        <DialogDescription className="mt-1 text-[12px] text-muted-foreground">
          Unrestricted documents follow workspace roles. Restricted documents are
          searchable only by owners, admins and the selected members.
        </DialogDescription>
        <label className="mt-4 flex items-center gap-2 text-[12px]">
          <input
            type="checkbox"
            checked={restricted}
            onChange={(event) => setRestricted(event.target.checked)}
          />
          Restrict to selected members
        </label>
        <div className="mt-3 max-h-56 overflow-y-auto rounded-[8px] border border-border">
          {(members.data ?? []).map((member) => (
            <label
              key={member.user_id}
              className="flex items-center gap-2 border-b border-border px-3 py-2 text-[12px] last:border-0"
            >
              <input
                type="checkbox"
                disabled={!restricted}
                checked={selected.includes(member.user_id)}
                onChange={(event) =>
                  setSelected((current) =>
                    event.target.checked
                      ? [...current, member.user_id]
                      : current.filter((id) => id !== member.user_id),
                  )
                }
              />
              <span className="truncate">{member.email}</span>
              <span className="ml-auto text-[10px] text-muted-foreground">
                {member.role}
              </span>
            </label>
          ))}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" disabled={save.isPending || grants.isLoading} onClick={() => save.mutate()}>
            Save permissions
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
