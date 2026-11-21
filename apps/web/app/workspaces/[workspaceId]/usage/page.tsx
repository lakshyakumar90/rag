"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../../../../lib/auth-client";
import { api, type Usage } from "../../../../lib/api/client";
import { RowSkeleton } from "../../../../components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../../../components/ui/tabs";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatNumber(value: number): string {
  return value.toLocaleString();
}

function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border py-3 last:border-0">
      <span className="text-[13px] text-muted-foreground">{label}</span>
      <span className="font-mono text-[14px] tabular-nums">{value}</span>
    </div>
  );
}

function Summary({ usage }: { usage: Usage }) {
  return (
    <div className="max-w-xl">
      <StatRow label="Queries" value={formatNumber(usage.queries)} />
      <StatRow label="Answers" value={formatNumber(usage.answers)} />
      <StatRow
        label="Tokens"
        value={`${formatNumber(usage.output_tokens)}${usage.estimated_token_answers ? " (estimated)" : ""}`}
      />
      <StatRow label="Documents" value={formatNumber(usage.documents)} />
      <StatRow label="Storage" value={formatBytes(usage.storage_bytes)} />
      <StatRow
        label="Feedback"
        value={`${usage.feedback_up} up / ${usage.feedback_down} down`}
      />
    </div>
  );
}

export default function UsagePage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [tab, setTab] = useState("overview");

  const usageQuery = useQuery({
    queryKey: ["usage", workspaceId],
    queryFn: () => api.usage(workspaceId),
    enabled: tab === "overview",
  });
  const analyticsQuery = useQuery({
    queryKey: ["analytics", workspaceId],
    queryFn: () => api.analytics(workspaceId),
    enabled: tab === "analytics",
    retry: false,
  });
  const auditQuery = useQuery({
    queryKey: ["audit", workspaceId],
    queryFn: () => api.auditLog(workspaceId),
    enabled: tab === "audit",
    retry: false,
  });

  return (
    <Tabs value={tab} onValueChange={setTab}>
      <TabsList className="mb-6">
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="analytics">Analytics</TabsTrigger>
        <TabsTrigger value="audit">Audit log</TabsTrigger>
      </TabsList>

      <TabsContent value="overview">
        {usageQuery.isLoading ? <RowSkeleton lines={6} /> : null}
        {usageQuery.data ? <Summary usage={usageQuery.data} /> : null}
        {usageQuery.isError ? (
          <p className="text-[13px] text-muted-foreground">Could not load usage.</p>
        ) : null}
      </TabsContent>

      <TabsContent value="analytics">
        {isForbidden(analyticsQuery.error) ? (
          <p className="text-[13px] text-muted-foreground">
            Analytics is available to workspace owners and admins.
          </p>
        ) : null}
        {analyticsQuery.isLoading ? <RowSkeleton lines={5} /> : null}
        {analyticsQuery.data ? (
          <div className="grid gap-8 lg:grid-cols-2">
            <section>
              <h2 className="mb-2 text-[13px] font-medium">Most asked</h2>
              {analyticsQuery.data.most_asked.length ? (
                <ul className="border-t border-border">
                  {analyticsQuery.data.most_asked.map((item) => (
                    <li
                      key={item.question}
                      className="flex items-baseline justify-between gap-4 border-b border-border py-2.5"
                    >
                      <span className="min-w-0 truncate text-[13px]">{item.question}</span>
                      <span className="font-mono text-[12px] text-muted-foreground">
                        {item.count}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-muted-foreground">No questions yet.</p>
              )}
            </section>
            <section className="space-y-8">
              <div>
                <h2 className="mb-2 text-[13px] font-medium">Low-confidence answers</h2>
                <p className="font-mono text-[22px]">
                  {analyticsQuery.data.low_confidence_count}
                </p>
                {analyticsQuery.data.low_confidence_questions.length ? (
                  <ul className="mt-3 border-t border-border">
                    {analyticsQuery.data.low_confidence_questions.map((item) => (
                      <li
                        key={item.question}
                        className="flex items-baseline justify-between gap-4 border-b border-border py-2.5"
                      >
                        <span className="min-w-0 truncate text-[13px]">{item.question}</span>
                        <span className="font-mono text-[12px] text-muted-foreground">
                          {item.count}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <div>
                <h2 className="mb-2 text-[13px] font-medium">Most cited documents</h2>
                {analyticsQuery.data.most_cited.length ? (
                  <ul className="border-t border-border">
                    {analyticsQuery.data.most_cited.map((item, index) => (
                      <li
                        key={`${item.document_id ?? item.filename}-${index}`}
                        className="flex items-baseline justify-between gap-4 border-b border-border py-2.5"
                      >
                        <span className="min-w-0 truncate text-[13px]">{item.filename}</span>
                        <span className="font-mono text-[12px] text-muted-foreground">
                          {item.citations}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[13px] text-muted-foreground">No citations yet.</p>
                )}
              </div>
            </section>
          </div>
        ) : null}
      </TabsContent>

      <TabsContent value="audit">
        {isForbidden(auditQuery.error) ? (
          <p className="text-[13px] text-muted-foreground">
            The audit log is available to workspace owners and admins.
          </p>
        ) : null}
        {auditQuery.isLoading ? <RowSkeleton lines={5} /> : null}
        {auditQuery.data?.length ? (
          <ul className="border-t border-border">
            {auditQuery.data.map((entry) => (
              <li key={entry.id} className="border-b border-border py-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-mono text-[12px]">{entry.action}</span>
                  <span className="text-[11px] text-muted-foreground">
                    {new Date(entry.created_at).toLocaleString()}
                  </span>
                </div>
                <p className="mt-1 text-[12px] text-muted-foreground">
                  {entry.actor_email}
                  {entry.target_type ? ` · ${entry.target_type}` : ""}
                  {entry.target_id ? ` · ${entry.target_id}` : ""}
                </p>
              </li>
            ))}
          </ul>
        ) : auditQuery.data ? (
          <p className="text-[13px] text-muted-foreground">No activity recorded yet.</p>
        ) : null}
      </TabsContent>
    </Tabs>
  );
}
