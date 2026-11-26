"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  GitBranch,
  History,
  Plus,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "../../../../components/ui/badge";
import { Button } from "../../../../components/ui/button";
import { Card } from "../../../../components/ui/card";
import { Input } from "../../../../components/ui/input";
import { CardGridSkeleton } from "../../../../components/ui/skeleton";
import { api, type MemoryItem, type MemoryTier } from "../../../../lib/api/client";

const TIERS: {
  id: MemoryTier;
  label: string;
  desc: string;
  accent: string;
  icon: typeof Sparkles;
}[] = [
  {
    id: "semantic",
    label: "Semantic Facts",
    desc: "Durable workspace facts with automatic conflict superseding.",
    accent: "from-sky-500/15 to-transparent border-sky-500/25",
    icon: Sparkles,
  },
  {
    id: "episodic",
    label: "Episodic Summaries",
    desc: "Turn and session summaries captured after completed chats.",
    accent: "from-violet-500/15 to-transparent border-violet-500/25",
    icon: History,
  },
  {
    id: "procedural",
    label: "Procedural Rules",
    desc: "Workspace directives injected into the isolated <memory> block.",
    accent: "from-emerald-500/15 to-transparent border-emerald-500/25",
    icon: ShieldCheck,
  },
];

export default function MemoryPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();

  const [activeTier, setActiveTier] = useState<MemoryTier>("semantic");
  const [includeSuperseded, setIncludeSuperseded] = useState(true);
  const [newContent, setNewContent] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");

  const memoriesQuery = useQuery({
    queryKey: ["workspace-memories", workspaceId, activeTier, includeSuperseded],
    queryFn: () =>
      api.listMemories(workspaceId, {
        tier: activeTier,
        includeSuperseded,
      }),
  });

  const createMemory = useMutation({
    mutationFn: () =>
      api.createMemory(workspaceId, {
        tier: activeTier,
        content: newContent.trim(),
      }),
    onSuccess: () => {
      setNewContent("");
      toast.success("Memory saved");
      void queryClient.invalidateQueries({
        queryKey: ["workspace-memories", workspaceId],
      });
    },
    onError: () => toast.error("Failed to save memory"),
  });

  const updateMemory = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      api.updateMemory(workspaceId, id, { content }),
    onSuccess: () => {
      setEditingId(null);
      setEditContent("");
      toast.success("Memory updated");
      void queryClient.invalidateQueries({
        queryKey: ["workspace-memories", workspaceId],
      });
    },
    onError: () => toast.error("Failed to update memory"),
  });

  const deleteMemory = useMutation({
    mutationFn: (id: string) => api.deleteMemory(workspaceId, id),
    onSuccess: () => {
      toast.success("Memory deleted");
      void queryClient.invalidateQueries({
        queryKey: ["workspace-memories", workspaceId],
      });
    },
    onError: () => toast.error("Failed to delete memory"),
  });

  const items: MemoryItem[] = memoriesQuery.data ?? [];
  const activeCount = items.filter((m) => m.status === "active").length;
  const supersededCount = items.filter((m) => m.status === "superseded").length;
  const currentMeta = TIERS.find((t) => t.id === activeTier)!;

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-violet-500/10 via-surface to-background p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-2xl border border-violet-500/30 bg-violet-500/15 text-violet-600 dark:text-violet-300">
              <Brain size={20} />
            </span>
            <div>
              <h1 className="text-xl font-semibold tracking-tight">
                4-Tier Cognitive Memory
              </h1>
              <p className="text-sm text-muted-foreground">
                Strictly isolated from untrusted document context so prompt injections cannot poison rules.
              </p>
            </div>
          </div>
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-border bg-background/80 px-3 py-1.5 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={includeSuperseded}
              onChange={(e) => setIncludeSuperseded(e.target.checked)}
            />
            Show superseded lineage
          </label>
        </div>
      </header>

      {/* Tier selector cards */}
      <div className="grid gap-3 sm:grid-cols-3">
        {TIERS.map((tab) => {
          const Icon = tab.icon;
          const selected = activeTier === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTier(tab.id)}
              className={`rounded-2xl border p-4 text-left transition-all ${
                selected
                  ? `bg-gradient-to-br ${tab.accent} shadow-sm ring-1 ring-accent/30`
                  : "border-border bg-surface/60 hover:bg-muted/40"
              }`}
            >
              <div className="flex items-center gap-2">
                <Icon size={15} className={selected ? "text-accent" : "text-muted-foreground"} />
                <span className="text-sm font-semibold">{tab.label}</span>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                {tab.desc}
              </p>
            </button>
          );
        })}
      </div>

      <Card className="space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-medium text-muted-foreground">
            {currentMeta.label}:{" "}
            <strong className="text-foreground">{activeCount} active</strong>
            {supersededCount > 0 ? ` · ${supersededCount} superseded` : ""}
          </p>
        </div>

        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (newContent.trim()) createMemory.mutate();
          }}
        >
          <Input
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            placeholder={
              activeTier === "procedural"
                ? "Add a procedural rule (e.g. Always cite RFC section numbers)..."
                : `Add a ${activeTier} memory entry...`
            }
          />
          <Button type="submit" size="sm" disabled={createMemory.isPending}>
            <Plus size={14} className="mr-1" /> Add
          </Button>
        </form>

        {memoriesQuery.isLoading ? <CardGridSkeleton cards={3} rows={3} /> : null}
        <div className="space-y-2.5">
          {items.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
              No {activeTier} memories recorded yet.
            </p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className={`flex items-start justify-between gap-3 rounded-xl border border-border bg-surface/50 p-4 text-sm transition-colors hover:border-accent/35 ${
                  item.status === "superseded" ? "opacity-65" : ""
                }`}
              >
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={item.status === "active" ? "accent" : "neutral"}>
                      {item.status}
                    </Badge>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      conf {Math.round(item.confidence * 100)}%
                    </span>
                    {item.superseded_by_id ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 font-mono text-[10.5px] text-muted-foreground">
                        <GitBranch size={10} /> replaced by{" "}
                        {item.superseded_by_id.slice(0, 8)}
                      </span>
                    ) : null}
                  </div>

                  {editingId === item.id ? (
                    <div className="mt-2 flex gap-2">
                      <Input
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                      />
                      <Button
                        size="sm"
                        onClick={() =>
                          updateMemory.mutate({
                            id: item.id,
                            content: editContent,
                          })
                        }
                      >
                        Save
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setEditingId(null)}
                      >
                        Cancel
                      </Button>
                    </div>
                  ) : (
                    <p
                      className={
                        item.status === "superseded"
                          ? "line-through text-muted-foreground"
                          : "leading-relaxed text-foreground"
                      }
                    >
                      {item.content}
                    </p>
                  )}
                </div>

                <div className="flex shrink-0 items-center gap-1">
                  {editingId !== item.id && item.status === "active" ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setEditingId(item.id);
                        setEditContent(item.content);
                      }}
                    >
                      Edit
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label="Delete memory"
                    onClick={() => deleteMemory.mutate(item.id)}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}
