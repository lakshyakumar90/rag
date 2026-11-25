"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "../../../../components/ui/badge";
import { Button } from "../../../../components/ui/button";
import { Card } from "../../../../components/ui/card";
import { Input } from "../../../../components/ui/input";
import { api, type MemoryItem, type MemoryTier } from "../../../../lib/api/client";

const TIERS: { id: MemoryTier; label: string; desc: string }[] = [
  {
    id: "semantic",
    label: "Semantic Facts",
    desc: "Durable facts extracted across conversations with conflict superseding.",
  },
  {
    id: "episodic",
    label: "Episodic Summaries",
    desc: "Turn and session summaries captured automatically after chat turns.",
  },
  {
    id: "procedural",
    label: "Procedural Rules",
    desc: "Explicit workspace rules injected into the isolated <memory> prompt block.",
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
  const currentMeta = TIERS.find((t) => t.id === activeTier)!;

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <Brain size={20} className="text-accent" />
          <div>
            <h1 className="text-xl font-semibold">Cognitive Memory Manager</h1>
            <p className="text-sm text-muted-foreground">
              Inspect and manage Semantic Facts, Episodic Summaries, and Procedural Rules.
            </p>
          </div>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={includeSuperseded}
            onChange={(e) => setIncludeSuperseded(e.target.checked)}
          />
          Show superseded history
        </label>
      </header>

      {/* Tier tabs */}
      <div className="flex flex-wrap gap-2 border-b border-border pb-3">
        {TIERS.map((tab) => (
          <Button
            key={tab.id}
            type="button"
            size="sm"
            variant={activeTier === tab.id ? "default" : "outline"}
            onClick={() => setActiveTier(tab.id)}
          >
            {tab.label}
          </Button>
        ))}
      </div>

      <Card className="space-y-4 p-5">
        <p className="text-xs text-muted-foreground">{currentMeta.desc}</p>

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

        <div className="divide-y divide-border rounded-xl border border-border">
          {items.length === 0 ? (
            <p className="p-4 text-xs text-muted-foreground">
              No {activeTier} memories recorded yet.
            </p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className={`flex items-start justify-between gap-3 p-3.5 text-sm ${
                  item.status === "superseded" ? "opacity-60" : ""
                }`}
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={item.status === "active" ? "accent" : "neutral"}>
                      {item.status}
                    </Badge>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      conf {Math.round(item.confidence * 100)}%
                    </span>
                    {item.superseded_by_id ? (
                      <span className="font-mono text-[11px] text-muted-foreground">
                        → replaced by {item.superseded_by_id.slice(0, 8)}
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
                          : "text-foreground"
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
