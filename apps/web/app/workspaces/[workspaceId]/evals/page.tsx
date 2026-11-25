"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Play, Plus } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "../../../../components/ui/badge";
import { Button } from "../../../../components/ui/button";
import { Card } from "../../../../components/ui/card";
import { Input } from "../../../../components/ui/input";
import { api, type EvalRun, type EvalRunDetail } from "../../../../lib/api/client";

function fmtPct(val: number | null | undefined): string {
  if (val === null || val === undefined) return "—";
  return `${Math.round(val * 100)}%`;
}

export default function EvalsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();

  const [datasetName, setDatasetName] = useState("");
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>("");
  const [newQuestion, setNewQuestion] = useState("");
  const [newExpected, setNewExpected] = useState("");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const datasetsQuery = useQuery({
    queryKey: ["eval-datasets", workspaceId],
    queryFn: () => api.listEvalDatasets(workspaceId),
  });

  const runsQuery = useQuery({
    queryKey: ["eval-runs", workspaceId],
    queryFn: () => api.listEvalRuns(workspaceId),
  });

  const runDetailQuery = useQuery({
    queryKey: ["eval-run-detail", workspaceId, selectedRunId],
    queryFn: () => api.getEvalRunDetail(workspaceId, selectedRunId!),
    enabled: Boolean(selectedRunId),
  });

  const createDataset = useMutation({
    mutationFn: () =>
      api.createEvalDataset(workspaceId, {
        name: datasetName.trim(),
        description: "Workspace evaluation dataset",
      }),
    onSuccess: (ds) => {
      setDatasetName("");
      setSelectedDatasetId(ds.id);
      toast.success(`Dataset "${ds.name}" created`);
      void queryClient.invalidateQueries({ queryKey: ["eval-datasets", workspaceId] });
    },
    onError: () => toast.error("Failed to create dataset"),
  });

  const addCase = useMutation({
    mutationFn: () =>
      api.addEvalCase(workspaceId, selectedDatasetId, {
        question: newQuestion.trim(),
        expected_answer: newExpected.trim() || undefined,
      }),
    onSuccess: () => {
      setNewQuestion("");
      setNewExpected("");
      toast.success("Eval case added");
      void queryClient.invalidateQueries({ queryKey: ["eval-datasets", workspaceId] });
    },
    onError: () => toast.error("Failed to add eval case"),
  });

  const triggerRun = useMutation({
    mutationFn: (datasetId: string) =>
      api.triggerEvalRun(workspaceId, datasetId, { top_k: 5, run_async: false }),
    onSuccess: (run) => {
      setSelectedRunId(run.id);
      toast.success("Evaluation run completed");
      void queryClient.invalidateQueries({ queryKey: ["eval-runs", workspaceId] });
    },
    onError: () => toast.error("Failed to run evaluation"),
  });

  const runs: EvalRun[] = runsQuery.data ?? [];
  const latest = runs[0];
  const detail: EvalRunDetail | undefined = runDetailQuery.data;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Evaluation Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Track Recall@5, Faithfulness, Answer Relevancy, and Citation Accuracy across runs.
          </p>
        </div>
      </header>

      {/* Top KPI Summary Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Recall@5", value: fmtPct(latest?.recall_at_k) },
          { label: "Faithfulness", value: fmtPct(latest?.faithfulness) },
          { label: "Answer Relevancy", value: fmtPct(latest?.answer_relevancy) },
          { label: "Citation Accuracy", value: fmtPct(latest?.citation_accuracy) },
        ].map((kpi) => (
          <Card key={kpi.label} className="p-4">
            <p className="text-xs font-medium text-muted-foreground">{kpi.label}</p>
            <p className="mt-1 font-mono text-2xl font-semibold text-foreground">
              {kpi.value}
            </p>
          </Card>
        ))}
      </div>

      {/* Dataset Manager & Trigger */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="space-y-4 p-5">
          <h2 className="text-sm font-semibold">Datasets</h2>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (datasetName.trim()) createDataset.mutate();
            }}
          >
            <Input
              value={datasetName}
              onChange={(e) => setDatasetName(e.target.value)}
              placeholder="New dataset name (e.g. Golden QA v1)"
            />
            <Button type="submit" size="sm" disabled={createDataset.isPending}>
              <Plus size={14} className="mr-1" /> Create
            </Button>
          </form>

          <div className="divide-y divide-border rounded-xl border border-border">
            {(datasetsQuery.data ?? []).length === 0 ? (
              <p className="p-4 text-xs text-muted-foreground">
                No evaluation datasets yet. Create one above or promote a chat answer.
              </p>
            ) : (
              (datasetsQuery.data ?? []).map((ds) => (
                <div
                  key={ds.id}
                  className="flex items-center justify-between gap-3 px-3.5 py-2.5 text-sm"
                >
                  <button
                    type="button"
                    onClick={() => setSelectedDatasetId(ds.id)}
                    className={`min-w-0 flex-1 text-left ${
                      selectedDatasetId === ds.id ? "font-semibold text-accent" : ""
                    }`}
                  >
                    <p className="truncate">{ds.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {ds.case_count} {ds.case_count === 1 ? "case" : "cases"}
                    </p>
                  </button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={triggerRun.isPending || ds.case_count === 0}
                    onClick={() => triggerRun.mutate(ds.id)}
                  >
                    <Play size={12} className="mr-1" /> Run Eval
                  </Button>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card className="space-y-4 p-5">
          <h2 className="text-sm font-semibold">Add Eval Case</h2>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (selectedDatasetId && newQuestion.trim()) addCase.mutate();
            }}
          >
            <Input
              value={newQuestion}
              onChange={(e) => setNewQuestion(e.target.value)}
              placeholder="Question to evaluate..."
              disabled={!selectedDatasetId}
            />
            <Input
              value={newExpected}
              onChange={(e) => setNewExpected(e.target.value)}
              placeholder="Expected answer (optional)"
              disabled={!selectedDatasetId}
            />
            <Button
              type="submit"
              size="sm"
              disabled={!selectedDatasetId || !newQuestion.trim() || addCase.isPending}
            >
              Add Case to Selected Dataset
            </Button>
          </form>
        </Card>
      </div>

      {/* Run History & Trend Bars */}
      <Card className="space-y-4 p-5">
        <h2 className="text-sm font-semibold">Run History & Accuracy Trends</h2>
        {runs.length === 0 ? (
          <p className="text-xs text-muted-foreground">No evaluation runs yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border text-muted-foreground">
                <tr>
                  <th className="py-2 pr-3">Run</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3 text-right">Recall@5</th>
                  <th className="py-2 pr-3 text-right">MRR</th>
                  <th className="py-2 pr-3 text-right">Faithfulness</th>
                  <th className="py-2 pr-3 text-right">Relevancy</th>
                  <th className="py-2 text-right">Citation Acc</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border font-mono">
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    onClick={() => setSelectedRunId(run.id)}
                    className={`cursor-pointer hover:bg-muted/40 ${
                      selectedRunId === run.id ? "bg-muted/50" : ""
                    }`}
                  >
                    <td className="py-2.5 pr-3 text-foreground">
                      {run.id.slice(0, 8)}
                    </td>
                    <td className="py-2.5 pr-3 font-sans">
                      <Badge tone={run.status === "completed" ? "accent" : "neutral"}>
                        {run.status}
                      </Badge>
                    </td>
                    <td className="py-2.5 pr-3 text-right">{fmtPct(run.recall_at_k)}</td>
                    <td className="py-2.5 pr-3 text-right">{fmtPct(run.mrr)}</td>
                    <td className="py-2.5 pr-3 text-right">{fmtPct(run.faithfulness)}</td>
                    <td className="py-2.5 pr-3 text-right">
                      {fmtPct(run.answer_relevancy)}
                    </td>
                    <td className="py-2.5 text-right">{fmtPct(run.citation_accuracy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Per-Question Drilldown & Failures */}
      {detail ? (
        <Card className="space-y-3 p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">
              Run {detail.id.slice(0, 8)} — Case Breakdown ({detail.failures.length}{" "}
              failures)
            </h2>
          </div>
          <div className="divide-y divide-border rounded-xl border border-border">
            {detail.results.map((res) => (
              <div key={res.id} className="space-y-1.5 p-3.5 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium text-foreground">{res.question}</p>
                  {res.passed ? (
                    <span className="inline-flex items-center gap-1 text-emerald-600">
                      <CheckCircle2 size={13} /> Pass
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-rose-600">
                      <AlertTriangle size={13} /> Fail
                    </span>
                  )}
                </div>
                <p className="text-muted-foreground">
                  Answer: {res.generated_answer || "—"}
                </p>
                <div className="flex flex-wrap gap-3 font-mono text-[11px] text-muted-foreground">
                  <span>Recall: {fmtPct(res.recall_at_k)}</span>
                  <span>Faithfulness: {fmtPct(res.faithfulness)}</span>
                  <span>Relevancy: {fmtPct(res.answer_relevancy)}</span>
                  <span>Citation: {fmtPct(res.citation_accuracy)}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
