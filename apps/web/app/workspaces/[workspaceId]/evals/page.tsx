"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  FlaskConical,
  Play,
  Plus,
  TrendingUp,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "../../../../components/ui/badge";
import { Button } from "../../../../components/ui/button";
import { Card } from "../../../../components/ui/card";
import { Input } from "../../../../components/ui/input";
import { CardGridSkeleton } from "../../../../components/ui/skeleton";
import { api, type EvalRun, type EvalRunDetail } from "../../../../lib/api/client";

function fmtPct(val: number | null | undefined): string {
  if (val === null || val === undefined) return "—";
  return `${Math.round(val * 100)}%`;
}

function AccuracyTrendChart({ runs }: { runs: EvalRun[] }) {
  const ordered = [...runs].reverse().slice(-10);
  if (ordered.length === 0) return null;

  const width = 640;
  const height = 180;
  const padX = 34;
  const padY = 18;
  const plotW = width - padX * 2;
  const plotH = height - padY * 2;

  const series: {
    key: keyof EvalRun;
    label: string;
    color: string;
  }[] = [
    { key: "recall_at_k", label: "Recall@5", color: "#0ea5e9" },
    { key: "faithfulness", label: "Faithfulness", color: "#10b981" },
    { key: "answer_relevancy", label: "Relevancy", color: "#8b5cf6" },
    { key: "citation_accuracy", label: "Citation Acc", color: "#f59e0b" },
  ];

  const xFor = (idx: number) =>
    ordered.length === 1
      ? padX + plotW / 2
      : padX + (idx / (ordered.length - 1)) * plotW;
  const yFor = (val: number) => padY + (1 - Math.max(0, Math.min(1, val))) * plotH;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-4 text-xs">
        {series.map((s) => (
          <span key={s.label} className="inline-flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: s.color }}
            />
            <span className="text-muted-foreground">{s.label}</span>
          </span>
        ))}
      </div>
      <div className="overflow-x-auto rounded-xl border border-border bg-surface/60 p-3">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-44 w-full min-w-[420px]"
          role="img"
          aria-label="Evaluation accuracy trend chart"
        >
          {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
            const y = yFor(tick);
            return (
              <g key={tick}>
                <line
                  x1={padX}
                  x2={width - padX}
                  y1={y}
                  y2={y}
                  stroke="currentColor"
                  strokeOpacity={0.1}
                  strokeDasharray="3 3"
                />
                <text
                  x={4}
                  y={y + 3}
                  fontSize="9"
                  fill="currentColor"
                  opacity={0.5}
                  fontFamily="monospace"
                >
                  {Math.round(tick * 100)}%
                </text>
              </g>
            );
          })}

          {series.map((s) => {
            const pts = ordered
              .map((run, idx) => {
                const raw = run[s.key];
                if (typeof raw !== "number") return null;
                return { x: xFor(idx), y: yFor(raw), val: raw };
              })
              .filter(Boolean) as { x: number; y: number; val: number }[];
            if (pts.length === 0) return null;
            const d = pts
              .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
              .join(" ");
            return (
              <g key={s.label}>
                {pts.length > 1 ? (
                  <path
                    d={d}
                    fill="none"
                    stroke={s.color}
                    strokeWidth={2.2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                ) : null}
                {pts.map((p, idx) => (
                  <circle
                    key={idx}
                    cx={p.x}
                    cy={p.y}
                    r={3.5}
                    fill={s.color}
                    stroke="var(--background)"
                    strokeWidth={1.5}
                  />
                ))}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
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

  const kpis = [
    {
      label: "Recall@5",
      val: latest?.recall_at_k,
      accent: "from-sky-500/15 to-transparent border-sky-500/25",
      bar: "bg-sky-500",
    },
    {
      label: "Faithfulness",
      val: latest?.faithfulness,
      accent: "from-emerald-500/15 to-transparent border-emerald-500/25",
      bar: "bg-emerald-500",
    },
    {
      label: "Answer Relevancy",
      val: latest?.answer_relevancy,
      accent: "from-violet-500/15 to-transparent border-violet-500/25",
      bar: "bg-violet-500",
    },
    {
      label: "Citation Accuracy",
      val: latest?.citation_accuracy,
      accent: "from-amber-500/15 to-transparent border-amber-500/25",
      bar: "bg-amber-500",
    },
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-accent/10 via-surface to-background p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-2xl border border-accent/30 bg-accent/15 text-accent">
              <FlaskConical size={20} />
            </span>
            <div>
              <h1 className="text-xl font-semibold tracking-tight">
                RAG Evaluation Studio
              </h1>
              <p className="text-sm text-muted-foreground">
                Measure retrieval precision and LLM-as-a-Judge faithfulness before shipping changes.
              </p>
            </div>
          </div>
          <Badge tone="accent">{runs.length} recorded runs</Badge>
        </div>
      </header>

      {datasetsQuery.isLoading || runsQuery.isLoading ? (
        <CardGridSkeleton cards={4} rows={4} />
      ) : null}

      {/* Vibrant KPI Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {kpis.map((kpi) => {
          const pctNum =
            typeof kpi.val === "number" ? Math.round(kpi.val * 100) : 0;
          return (
            <Card
              key={kpi.label}
              className={`bg-gradient-to-br ${kpi.accent} p-4 transition-transform hover:-translate-y-0.5`}
            >
              <p className="text-xs font-medium text-muted-foreground">
                {kpi.label}
              </p>
              <p className="mt-1.5 font-mono text-2xl font-semibold text-foreground">
                {fmtPct(kpi.val)}
              </p>
              <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${kpi.bar}`}
                  style={{ width: `${pctNum}%` }}
                />
              </div>
            </Card>
          );
        })}
      </div>

      {/* Multi-Metric Accuracy Trend Chart */}
      {runs.length > 0 ? (
        <Card className="space-y-3 p-5">
          <div className="flex items-center gap-2">
            <TrendingUp size={16} className="text-accent" />
            <h2 className="text-sm font-semibold">Accuracy Trends Across Runs</h2>
          </div>
          <AccuracyTrendChart runs={runs} />
        </Card>
      ) : null}

      {/* Dataset Manager & Case Builder */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="space-y-4 p-5">
          <h2 className="text-sm font-semibold">Golden Datasets</h2>
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
              placeholder="New dataset name (e.g. Golden QA v2)"
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
                  className={`flex items-center justify-between gap-3 px-3.5 py-3 text-sm transition-colors ${
                    selectedDatasetId === ds.id ? "bg-accent/5" : ""
                  }`}
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
              placeholder={
                selectedDatasetId
                  ? "Question to evaluate..."
                  : "Select a dataset on the left first..."
              }
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

      {/* Run History Table */}
      <Card className="space-y-4 p-5">
        <h2 className="text-sm font-semibold">Run History</h2>
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
                    className={`cursor-pointer transition-colors hover:bg-muted/40 ${
                      selectedRunId === run.id ? "bg-accent/5" : ""
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
              <div key={res.id} className="space-y-1.5 p-4 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium text-foreground">{res.question}</p>
                  {res.passed ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 font-medium text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 size={12} /> Pass
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/10 px-2 py-0.5 font-medium text-rose-600 dark:text-rose-400">
                      <AlertTriangle size={12} /> Fail
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
