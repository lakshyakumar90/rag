"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  FileText,
  MessageSquare,
  Plus,
  Sparkles,
  Trash2,
  History,
  MessageSquarePlus,
  RotateCw,
  Square,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "../../../../components/ui/button";
import { Input } from "../../../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../../../components/ui/select";
import { RowSkeleton } from "../../../../components/ui/skeleton";
import { Badge } from "../../../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../../../../components/ui/dialog";
import { ConfidenceBadge, type ConfidenceBreakdown } from "../../../../components/confidence-badge";
import { CitationSplitViewer } from "../../../../components/citation-split-viewer";
import { RetrievalInspectorDrawer, type RetrievalDiagnostics } from "../../../../components/retrieval-inspector-drawer";
import {
  api,
  type Conversation,
} from "../../../../lib/api/client";
import { ApiError } from "../../../../lib/auth-client";
import type { ChatEvent } from "../../../../lib/chat-stream";
import { streamChat } from "../../../../lib/chat-stream";
import { streamAgent, type AgentCitation, type AgentEvent } from "../../../../lib/agent-stream";
import type { components } from "../../../../lib/api/schema";

type SourceRef = components["schemas"]["SourceRef"];
type ToolActivity = {
  tool: string;
  step: number;
  detail: string;
  status: "running" | "done";
  citations: AgentCitation[];
};
type DisplayMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: SourceRef[];
  agentCitations?: AgentCitation[];
  provider?: string | null;
  model?: string | null;
  streaming?: boolean;
  confidenceScore?: number | null;
  confidenceLevel?: string | null;
  confidenceBreakdown?: ConfidenceBreakdown | null;
  retrievalDiagnostics?: RetrievalDiagnostics | null;
};

function lastAssistantIndex(messages: DisplayMessage[]): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant") return index;
  }
  return -1;
}

// Streamed answers get a temporary client id until the thread is reloaded.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function ChatPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [selectionReady, setSelectionReady] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const busy = streaming || regenerating;
  const [agentMode, setAgentMode] = useState(false);
  const [toolActivity, setToolActivity] = useState<Record<string, ToolActivity[]>>({});
  const [editingModel, setEditingModel] = useState(false);
  const [activeSource, setActiveSource] = useState<SourceRef | null>(null);
  const [inspectorDiagnostics, setInspectorDiagnostics] = useState<RetrievalDiagnostics | null>(null);
  const [splitWidth, setSplitWidth] = useState(42);
  const promoteEval = useMutation({
    mutationFn: (messageId: string) => api.promoteMessageToEval(workspaceId, messageId),
    onSuccess: () => toast.success('Promoted to Feedback Regression Suite'),
    onError: () => toast.error('Could not promote message to eval'),
  });
  const snippet = useQuery({
    queryKey: ["citation-snippet", workspaceId, activeSource?.document_id, activeSource?.chunk_id],
    queryFn: () => api.documentSnippet(workspaceId, activeSource!.document_id, activeSource!.chunk_id),
    enabled: Boolean(activeSource),
    retry: false,
    gcTime: 0,
  });
  const [historyOpen, setHistoryOpen] = useState(false);
  const [votes, setVotes] = useState<Record<string, "up" | "down">>({});
  const [commentTarget, setCommentTarget] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [commentVote, setCommentVote] = useState<"up" | "down">("up");

  const ai = useQuery({ queryKey: ["ai-providers"], queryFn: api.aiProviders });
  const effectiveProvider = provider || ai.data?.defaults.provider || "";
  const models = useQuery({
    queryKey: ["ai-models", effectiveProvider],
    queryFn: () => api.aiModels(effectiveProvider),
    enabled: Boolean(effectiveProvider) && !effectiveProvider.startsWith("config:"),
    staleTime: 300_000,
    retry: false,
  });
  const { data: conversations, isLoading } = useQuery({
    queryKey: ["conversations", workspaceId],
    queryFn: () => api.conversations(workspaceId),
  });

  // New chats start from the saved Settings defaults.
  useEffect(() => {
    if (selectionReady || !ai.data?.defaults) return;
    if (!conversationId) {
      setProvider(ai.data.defaults.provider);
      setModel(ai.data.defaults.model ?? "");
    }
    setSelectionReady(true);
  }, [ai.data?.defaults, conversationId, selectionReady]);

  useEffect(() => {
    const firstId = conversations?.[0]?.id;
    if (!conversationId && firstId) void loadConversation(firstId);
    // Prefill from a workspace-search result (Ctrl+K).
    const query = searchParams.get("q");
    if (query) setInput(query);
  }, [conversations, conversationId, searchParams]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    if (atBottomRef.current) {
      node.scrollTop = node.scrollHeight;
      setShowJump(false);
    } else {
      setShowJump(true);
    }
  }, [messages]);

  function onScroll() {
    const node = scrollRef.current;
    if (!node) return;
    const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 64;
    atBottomRef.current = atBottom;
    if (atBottom) setShowJump(false);
  }

  function jumpToLatest() {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
    atBottomRef.current = true;
    setShowJump(false);
  }

  const refreshConversations = () =>
    queryClient.invalidateQueries({ queryKey: ["conversations", workspaceId] });

  const selection = useMutation({
    mutationFn: ({
      nextProvider,
      nextModel,
    }: {
      nextProvider: string;
      nextModel: string;
    }) => {
      if (!conversationId) return Promise.resolve(null);
      return api.setConversationSelection(
        workspaceId,
        conversationId,
        nextProvider || null,
        nextModel.trim() || null,
      );
    },
    onError: () => toast.error("Could not save this conversation's model choice"),
  });

  const createConversation = useMutation({
    mutationFn: () => api.createConversation(workspaceId),
    onSuccess: (conversation) => {
      setConversationId(conversation.id);
      setMessages([]);
      setHistoryOpen(false);
      refreshConversations();
    },
  });

  const removeConversation = useMutation({
    mutationFn: (id: string) => api.deleteConversation(workspaceId, id),
    onSuccess: () => {
      setConversationId(null);
      setMessages([]);
      refreshConversations();
      toast.success("Conversation deleted");
    },
  });

  const feedback = useMutation({
    mutationFn: ({
      messageId,
      vote,
      note,
    }: {
      messageId: string;
      vote: "up" | "down";
      note?: string;
    }) => api.setFeedback(workspaceId, messageId, vote, note),
    onSuccess: (result) => {
      setVotes((current) => ({ ...current, [result.message_id]: result.vote as "up" | "down" }));
      setCommentTarget(null);
      setComment("");
      toast.success("Thanks for the feedback");
    },
    retry: (attempt, error) =>
      attempt === 0 && error instanceof ApiError && error.status === 503,
    retryDelay: 1200,
    onError: (error) => toast.error(
      error instanceof ApiError ? error.message : "Could not save feedback",
    ),
  });

  async function loadConversation(id: string) {
    setConversationId(id);
    setHistoryOpen(false);
    try {
      const [history, conversation] = await Promise.all([
        api.messages(workspaceId, id),
        api.conversations(workspaceId).then((items) => items.find((item) => item.id === id)),
      ]);
      setMessages(
        history.map((message) => ({
          id: message.id,
          role: message.role as "user" | "assistant",
          content: message.content,
          citations: (message.citations ?? []) as SourceRef[],
          provider: message.provider,
          model: message.model,
        })),
      );
      if (conversation?.provider) {
        setProvider(conversation.provider);
        setModel(conversation.model ?? "");
      } else if (ai.data?.defaults) {
        setProvider(ai.data.defaults.provider);
        setModel(ai.data.defaults.model ?? "");
      }
      atBottomRef.current = true;
    } catch {
      toast.error("Could not load that conversation");
    }
  }

  function changeProvider(next: string) {
    setProvider(next);
    setModel("");
    if (conversationId) {
      selection.mutate({ nextProvider: next, nextModel: "" });
    }
  }

  function changeModel(next: string) {
    setModel(next);
    if (conversationId) {
      selection.mutate({ nextProvider: provider, nextModel: next });
    }
  }

  async function send() {
    const query = input.trim();
    if (!query || busy || abortRef.current) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming(true);
    atBottomRef.current = true;
    let conversation = conversationId;
    try {
      if (!conversation) {
        const created = await api.createConversation(workspaceId, undefined, provider || undefined, model.trim() || undefined);
        conversation = created.id;
        setConversationId(conversation);
        refreshConversations();
      }
      if (controller.signal.aborted) {
        setStreaming(false);
        abortRef.current = null;
        return;
      }
    } catch {
      setStreaming(false);
      abortRef.current = null;
      toast.error("Could not start a conversation");
      return;
    }
    setInput("");

    const userId = `user-${Date.now()}`;
    const assistantId = `assistant-${Date.now()}`;
    setMessages((current) => [
      ...current,
      { id: userId, role: "user", content: query, citations: [] },
      {
        id: assistantId,
        role: "assistant",
        content: "",
        citations: [],
        provider,
        model,
        streaming: true,
      },
    ]);

    const onEvent = (event: ChatEvent) => {
      if (event.type === "sources") {
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId ? { ...message, citations: event.sources } : message,
          ),
        );
      } else if (event.type === "token") {
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId
              ? { ...message, content: message.content + event.text }
              : message,
          ),
        );
      } else if (event.type === "confidence") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      confidenceScore: event.confidence_score,
                      confidenceLevel: event.confidence_level,
                      confidenceBreakdown: (event.confidence_breakdown ?? null) as ConfidenceBreakdown | null,
                      retrievalDiagnostics: (event.retrieval_diagnostics ?? null) as RetrievalDiagnostics | null,
                    }
                  : m,
              ),
            );
          } else if (event.type === "done") {
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId
              ? { ...message, provider: event.provider, model: event.model }
              : message,
          ),
        );
      } else if (event.type === "error") {
        toast.error(event.message);
      }
    };

    try {
      if (agentMode) {
        const onAgentEvent = (event: AgentEvent) => {
          if (event.type === "tool_start" || event.type === "tool_result") {
            setToolActivity((current) => {
              const existing = current[assistantId] ?? [];
              const next = existing.filter((item) => item.step !== event.step);
              next.push({
                tool: event.tool,
                step: event.step,
                detail: event.detail ?? "",
                status: event.type === "tool_result" ? "done" : "running",
                citations: event.citations ?? [],
              });
              return { ...current, [assistantId]: next.sort((a, b) => a.step - b.step) };
            });
          } else if (event.type === "done") {
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? {
                      ...message,
                      content: event.answer,
                      citations: [],
                      agentCitations: event.citations,
                      provider: event.provider,
                      model: event.model,
                    }
                  : message,
              ),
            );
          } else if (event.type === "error") {
            toast.error(event.message);
          }
        };
        await streamAgent(
          workspaceId,
          {
            query,
            provider: provider || undefined,
            model: provider && model.trim() ? model.trim() : undefined,
          },
          onAgentEvent,
          controller.signal,
        );
        return;
      }
      const completed = await streamChat(
        workspaceId,
        {
          query,
          conversation_id: conversation,
          provider: provider || undefined,
          model: provider && model.trim() ? model.trim() : undefined,
        },
        onEvent,
        controller.signal,
      );
      if (completed) {
        const saved = await api.messages(workspaceId, conversation).catch(() => null);
        const answer = saved?.at(-1);
        if (
          answer?.role === "assistant" &&
          answer.content === completed.answer &&
          saved?.at(-2)?.content === query
        ) {
          setMessages((current) => current.map((message) =>
            message.id === assistantId
              ? {
                  ...message,
                  id: answer.id,
                  content: answer.content,
                  citations: completed.citations,
                  provider: answer.provider,
                  model: answer.model,
                  streaming: false,
                }
              : message,
          ));
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        toast.error(error instanceof Error ? error.message : "Streaming failed");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId ? { ...message, streaming: false } : message,
        ),
      );
      refreshConversations();
    }
  }

  async function stop() {
    abortRef.current?.abort();
    if (conversationId) {
      try {
        await api.stopGeneration(workspaceId, conversationId);
      } catch {
        // Already stopped.
      }
    }
  }

  async function regenerate() {
    if (!conversationId || busy) return;
    setRegenerating(true);
    try {
      const response = await api.regenerate(workspaceId, conversationId);
      const stored = await api.messages(workspaceId, conversationId);
      const updated = stored.at(-1);
      setMessages((current) =>
        current.map((message, index) =>
          message.role === "assistant" && index === lastAssistantIndex(current)
            ? {
                ...message,
                id: updated?.role === "assistant" ? updated.id : message.id,
                content: response.answer,
                citations: response.citations,
                provider: response.provider,
                model: response.model,
              }
            : message,
        ),
      );
      toast.success("Answer regenerated");
    } catch {
      toast.error("Could not regenerate the answer");
    } finally {
      setRegenerating(false);
    }
  }

  const selectedOption = ai.data?.options.find((option) => option.id === effectiveProvider);
  const defaultProviderLabel = ai.data?.options.find((option) => option.id === ai.data?.defaults.provider)?.label;
  const defaultModelLabel = effectiveProvider === ai.data?.defaults.provider
    ? ai.data?.defaults.model ?? selectedOption?.default_model
    : selectedOption?.default_model;
  const modelIds = [...new Set([
    selectedOption?.default_model, ...(models.data?.models ?? []), model,
  ].filter((id): id is string => Boolean(id)))];
  const latestAnswer = lastAssistantIndex(messages);

  const conversationList = (
    <div className="flex min-h-0 flex-col gap-3">
      <Button variant="outline" className="h-10 w-full justify-start gap-2 bg-surface-raised px-3" disabled={busy || createConversation.isPending} onClick={() => createConversation.mutate()}>
        <Plus size={16} /> New conversation
      </Button>
      <div className="px-2 text-xs font-medium text-muted-foreground">Recent conversations</div>
      <div className="flex flex-col gap-1">
        {isLoading && <RowSkeleton lines={2} />}
        {conversations?.map((conversation: Conversation) => (
          <div key={conversation.id} className={`group flex min-w-0 items-center gap-0.5 rounded-lg border px-1 ${conversation.id === conversationId ? "border-border bg-muted" : "border-transparent hover:bg-surface-raised"}`}>
            <button
              type="button"
              disabled={busy}
              aria-current={conversation.id === conversationId ? "true" : undefined}
              className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md px-2 text-left text-[13px] focus-visible:outline-2 focus-visible:outline-accent"
              onClick={() => void loadConversation(conversation.id)}
            >
              <MessageSquare size={14} className="shrink-0 text-muted-foreground" />
              <span className="truncate">{conversation.title}</span>
            </button>
            <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0 text-muted-foreground lg:opacity-0 lg:group-hover:opacity-100 lg:focus-visible:opacity-100"
              aria-label="Delete conversation" title="Delete conversation" disabled={busy || removeConversation.isPending}
              onClick={() => removeConversation.mutate(conversation.id)}>
              <Trash2 size={14} />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <div className="flex h-full min-h-0">
      <aside aria-label="Conversation history" className="hidden w-[228px] shrink-0 overflow-y-auto border-r border-border bg-surface/75 px-3 py-4 lg:block">
        {conversationList}
      </aside>

      <section className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center border-b border-border px-4 py-2 lg:hidden">
          <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
            <Button variant="outline" size="sm" onClick={() => setHistoryOpen(true)}>
              <History size={14} /> Conversations
            </Button>
            <DialogContent side="bottom" className="overflow-y-auto overscroll-contain p-4">
              <DialogTitle>Conversations</DialogTitle>
              <DialogDescription className="mb-3 text-[12px] text-muted-foreground">
                Pick a thread or start a new one.
              </DialogDescription>
              {conversationList}
            </DialogContent>
          </Dialog>
        </div>

        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]"
        >
          <div className="mx-auto flex min-h-full w-full max-w-[52rem] flex-col gap-7 px-4 pb-5 pt-5 sm:px-7">
          {messages.length ? (
            messages.map((message, index) => (
              <article
                key={message.id}
                className={`min-w-0 text-[14px] leading-7 sm:text-[15px] ${
                  message.role === "user"
                    ? "max-w-[86%] self-end rounded-2xl rounded-br-md bg-muted px-4 py-2.5"
                    : "w-full self-start"
                }`}
              >
                <div className="break-words [&_a]:text-accent [&_li]:ml-5 [&_ol]:list-decimal [&_ul]:list-disc [&_p+p]:mt-3 [&_table]:block [&_table]:overflow-x-auto [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[12px] [&_pre]:overflow-x-auto [&_pre]:rounded-[8px] [&_pre]:border [&_pre]:border-border [&_pre]:bg-muted [&_pre]:p-3">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {message.content || (message.streaming ? "…" : "")}
                  </ReactMarkdown>
                </div>
                {message.role === "assistant" && (message.provider || message.model) ? (
                  <p className="mt-1.5 text-[11px] leading-normal text-muted-foreground">
                    {ai.data?.options.find((option) => option.id === message.provider)?.label ?? message.provider ?? "Assistant"}
                    {message.model ? ` · ${message.model}` : ""}
                  </p>
                ) : null}
                {message.role === "assistant" && toolActivity[message.id]?.length ? (
                  <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Tool activity">
                    {(toolActivity[message.id] ?? []).map((activity) => (
                      <details
                        key={activity.step}
                        className="max-w-full rounded-[6px] border border-border px-2 py-1 text-[10px]"
                      >
                        <summary className="cursor-pointer font-mono">
                          {activity.status === "running" ? "◌" : "✓"} step {activity.step}: {activity.tool}
                        </summary>
                        <pre className="mt-1 max-w-full whitespace-pre-wrap break-all text-muted-foreground">
                          {activity.detail}
                        </pre>
                      </details>
                    ))}
                  </div>
                ) : null}
                {message.agentCitations?.length ? (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {message.agentCitations.map((citation) =>
                      citation.source_type === "web" && citation.url ? (
                        <a
                          key={citation.url + citation.number}
                          href={citation.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 rounded-[6px] border border-border px-1.5 py-0.5 font-mono text-[10px] text-accent hover:bg-muted"
                          title={citation.text}
                        >
                          [web {citation.number ?? ""}] {citation.filename}
                        </a>
                      ) : citation.chunk_id && citation.document_id ? (
                        <Button key={citation.chunk_id} type="button" variant="outline" size="sm"
                          className="h-auto max-w-full whitespace-normal py-1.5 text-left"
                          onClick={() => setActiveSource({
                            chunk_id: citation.chunk_id!,
                            document_id: citation.document_id!,
                            filename: citation.filename ?? "Document",
                            number: citation.number ?? 1,
                            page_number: citation.page_number ?? null,
                            heading_path: null,
                            source_type: "workspace",
                          })}>
                          <FileText size={14} className="shrink-0 text-accent" />
                          <span className="min-w-0 [overflow-wrap:anywhere]">[{citation.number ?? 1}] {citation.filename}</span>
                        </Button>
                      ) : (
                        <span
                          key={citation.chunk_id ?? citation.document_id ?? citation.number}
                          className="inline-flex items-center gap-1 rounded-[6px] border border-border px-1.5 py-0.5 font-mono text-[10px] text-accent"
                          title={citation.text}
                        >
                          [{citation.number ?? ""}] {citation.filename}
                        </span>
                      ),
                    )}
                  </div>
                ) : null}
                {message.citations.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2" aria-label="Sources">
                    {message.citations.map((citation) => (
                      <Button key={`${citation.chunk_id}-${citation.number}`} type="button" variant="outline"
                        className="h-auto max-w-full justify-start gap-2 rounded-lg bg-surface px-2.5 py-1.5 text-left"
                        onClick={() => setActiveSource(citation)}>
                        <FileText size={14} className="shrink-0 text-accent" />
                        <span className="shrink-0 text-[11px] text-accent">[{citation.number}]</span>
                        <span className="min-w-0 [overflow-wrap:anywhere] whitespace-normal text-xs leading-5">{citation.filename}</span>
                        {citation.page_number && <span className="shrink-0 text-[11px] text-muted-foreground">p. {citation.page_number}</span>}
                      </Button>
                    ))}
                  </div>
                )}
                {message.role === "assistant" && !message.streaming && UUID.test(message.id) ? (
                  <div className="mt-2 flex items-center gap-1 text-muted-foreground">
                    {index === latestAnswer && (
                      <Button type="button" variant="ghost" size="icon" className="h-8 w-8"
                        aria-label="Regenerate answer" title="Regenerate answer" disabled={busy}
                        onClick={() => void regenerate()}>
                        <RotateCw size={15} className={regenerating ? "animate-spin" : undefined} />
                      </Button>
                    )}
                    <button
                      type="button"
                      aria-label="Good answer"
                      disabled={feedback.isPending}
                      title="Good answer"
                      onClick={() => feedback.mutate({ messageId: message.id, vote: "up" })}
                      className={`rounded-[6px] p-1 hover:bg-muted hover:text-foreground ${
                        votes[message.id] === "up" ? "text-accent" : ""
                      }`}
                    >
                      <ConfidenceBadge level={message.confidenceLevel} score={message.confidenceScore} breakdown={message.confidenceBreakdown} />{message.retrievalDiagnostics ? (<Button type="button" size="sm" variant="ghost" className="h-6 px-1.5 text-[11px]" onClick={() => setInspectorDiagnostics(message.retrievalDiagnostics ?? null)}>Inspect</Button>) : null}{UUID.test(message.id) ? (<Button type="button" size="sm" variant="ghost" className="h-6 px-1.5 text-[11px]" disabled={promoteEval.isPending} onClick={() => promoteEval.mutate(message.id)}>+ Eval</Button>) : null}<ThumbsUp size={13} />
                    </button>
                    <button
                      type="button"
                      aria-label="Bad answer"
                      disabled={feedback.isPending}
                      title="Bad answer"
                      onClick={() => feedback.mutate({ messageId: message.id, vote: "down" })}
                      className={`rounded-[6px] p-1 hover:bg-muted hover:text-foreground ${
                        votes[message.id] === "down" ? "text-accent" : ""
                      }`}
                    >
                      <ThumbsDown size={13} />
                    </button>
                    <button
                      type="button"
                      aria-label="Add feedback comment"
                      disabled={feedback.isPending}
                      title="Add a comment"
                      onClick={() => {
                        setCommentTarget(message.id);
                        setCommentVote(votes[message.id] ?? "up");
                        setComment("");
                      }}
                      className="rounded-[6px] p-1 hover:bg-muted hover:text-foreground"
                    >
                      <MessageSquarePlus size={13} />
                    </button>
                  </div>
                ) : null}
              </article>
            ))
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 px-4 py-4 text-center">
              <BookOpen size={23} className="mb-2 text-accent" />
              <h2 className="text-xl font-semibold tracking-tight">What would you like to find?</h2>
              <p className="max-w-sm text-[12px] text-muted-foreground">
                Ask about your workspace documents and open the cited passages.
              </p>
            </div>
          )}
          </div>
        </div>

        <div className="relative mx-auto w-full max-w-[52rem] shrink-0 px-3 pb-1 pt-2 sm:px-7">
          {showJump && (
            <Button type="button" variant="outline" size="sm" onClick={jumpToLatest}
              className="absolute -top-9 left-1/2 z-10 -translate-x-1/2 rounded-full">
              <ArrowDown size={14} /> Jump to latest
            </Button>
          )}
          <form className="rounded-2xl border border-border bg-surface-raised px-3 py-2.5 focus-within:border-muted-foreground/50 sm:px-4"
            onSubmit={(event) => { event.preventDefault(); void send(); }}>
            <textarea value={input} aria-label="Question" rows={2} placeholder="Ask a question…"
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  void send();
                }
              }}
              className="block min-h-12 max-h-36 w-full resize-none bg-transparent px-1 py-1 text-[15px] leading-6 outline-none placeholder:text-muted-foreground [field-sizing:content]"
            />
            <div className="mt-2 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-1.5 sm:flex sm:gap-2">
              <Button type="button" variant={agentMode ? "outline" : "ghost"} size="sm" aria-pressed={agentMode}
                aria-label="Toggle agent mode" disabled={busy} onClick={() => setAgentMode((value) => !value)}
                className="col-span-2 hidden h-8 justify-start gap-1.5 rounded-lg px-2 min-[420px]:inline-flex">
                <Sparkles size={14} /> Agent
              </Button>
              <Select value={provider || "__default"} disabled={busy}
                onValueChange={(value) => { setEditingModel(false); changeProvider(value === "__default" ? "" : value); }}>
                <SelectTrigger aria-label="Provider for next message" className="h-8 w-full min-w-0 justify-between gap-1 border-transparent bg-transparent px-1.5 text-xs sm:w-auto sm:px-2 [&>span]:truncate">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__default">{defaultProviderLabel ? `${defaultProviderLabel} (default)` : "Default provider"}</SelectItem>
                  {(ai.data?.options ?? []).map((option) => (
                    <SelectItem key={option.id} value={option.id}>{option.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={model || "__default"} disabled={busy}
                onValueChange={(value) => {
                  setEditingModel(value === "__manual");
                  if (value !== "__manual") changeModel(value === "__default" ? "" : value);
                }}>
                <SelectTrigger aria-label="Model for next message" className="h-8 w-full min-w-0 justify-between gap-1 border-transparent bg-transparent px-1.5 text-xs sm:w-auto sm:max-w-58 sm:px-2 [&>span]:truncate">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="max-w-[min(24rem,85vw)]">
                  <SelectItem value="__default">{defaultModelLabel ? `${defaultModelLabel} (default)` : "Default model"}</SelectItem>
                  {modelIds.map((id) => <SelectItem key={id} value={id} className="[&>span:last-child]:truncate">{id}</SelectItem>)}
                  <SelectItem value="__manual">Enter model ID…</SelectItem>
                </SelectContent>
              </Select>
              <div className="ml-auto flex items-center gap-1">
                <Button type="button" size="icon" variant={agentMode ? "outline" : "ghost"}
                  className="h-8 w-8 min-[420px]:hidden" title="Agent mode" aria-label="Toggle agent mode"
                  aria-pressed={agentMode} disabled={busy} onClick={() => setAgentMode((value) => !value)}>
                  <Sparkles size={15} />
                </Button>
                {streaming ? (
                  <Button type="button" size="icon" aria-label="Stop generating" title="Stop generating" className="h-8 w-8 rounded-xl" onClick={() => void stop()}>
                    <Square size={13} fill="currentColor" />
                  </Button>
                ) : (
                  <Button type="submit" size="icon" variant="accent" aria-label="Send" title="Send" className="h-8 w-8 rounded-xl" disabled={busy || !input.trim()}>
                    <ArrowUp size={18} />
                  </Button>
                )}
              </div>
            </div>
            {editingModel && (
              <div className="mt-2 flex items-center gap-2">
                <Input aria-label="Custom model ID" placeholder="Enter a model ID" autoFocus value={model} maxLength={160}
                  onChange={(event) => changeModel(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); setEditingModel(false); } }} />
                <Button size="sm" type="button" variant="outline" onClick={() => setEditingModel(false)}>Done</Button>
              </div>
            )}
          </form>
        </div>
      </section>

      {activeSource ? (
        <div
          className="hidden h-full shrink-0 lg:flex"
          style={{ width: `${splitWidth}%` }}
        >
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize citation viewer"
            onMouseDown={(event) => {
              event.preventDefault();
              const startX = event.clientX;
              const startW = splitWidth;
              const onMove = (moveEvent: MouseEvent) => {
                const deltaPct = ((startX - moveEvent.clientX) / window.innerWidth) * 100;
                setSplitWidth(Math.max(28, Math.min(60, Math.round(startW + deltaPct))));
              };
              const onUp = () => {
                window.removeEventListener("mousemove", onMove);
                window.removeEventListener("mouseup", onUp);
              };
              window.addEventListener("mousemove", onMove);
              window.addEventListener("mouseup", onUp);
            }}
            className="w-1.5 cursor-col-resize bg-border/60 transition-colors hover:bg-accent/60"
          />
          <div className="min-w-0 flex-1">
            <CitationSplitViewer
              source={activeSource}
              snippet={snippet.data}
              isPending={snippet.isPending}
              isError={snippet.isError}
              onRetry={() => void snippet.refetch()}
              onClose={() => setActiveSource(null)}
            />
          </div>
        </div>
      ) : null}
      {activeSource ? (
        <div className="fixed inset-y-0 right-0 z-30 w-full max-w-xl shadow-2xl lg:hidden">
          <CitationSplitViewer
            source={activeSource}
            snippet={snippet.data}
            isPending={snippet.isPending}
            isError={snippet.isError}
            onRetry={() => void snippet.refetch()}
            onClose={() => setActiveSource(null)}
          />
        </div>
      ) : null}

      <RetrievalInspectorDrawer
        open={Boolean(inspectorDiagnostics)}
        diagnostics={inspectorDiagnostics}
        onClose={() => setInspectorDiagnostics(null)}
      />

      <Dialog
        open={Boolean(commentTarget)}
        onOpenChange={(open) => {
          if (!open) setCommentTarget(null);
        }}
      >
        <DialogContent className="p-5">
          <DialogTitle className="text-[14px] font-semibold">Rate this answer</DialogTitle>
          <DialogDescription className="mt-1 text-[12px] text-muted-foreground">
            Optional comment — it helps improve grounded answers.
          </DialogDescription>
          <div className="mt-4 flex gap-2">
            <Button
              type="button"
              size="sm"
              variant={commentVote === "up" ? "default" : "outline"}
              onClick={() => setCommentVote("up")}
            >
              <ThumbsUp size={13} /> Good
            </Button>
            <Button
              type="button"
              size="sm"
              variant={commentVote === "down" ? "default" : "outline"}
              onClick={() => setCommentVote("down")}
            >
              <ThumbsDown size={13} /> Bad
            </Button>
          </div>
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={1000}
            rows={4}
            aria-label="Feedback comment"
            placeholder="What could be better?"
            className="mt-3 w-full resize-y rounded-[8px] border border-border bg-surface px-3 py-2 text-[13px] placeholder:text-muted-foreground focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25"
          />
          <div className="mt-4 flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setCommentTarget(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={feedback.isPending}
              onClick={() =>
                commentTarget
                  ? feedback.mutate({
                      messageId: commentTarget,
                      vote: commentVote,
                      note: comment.trim() || undefined,
                    })
                  : undefined
              }
            >
              Submit
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
