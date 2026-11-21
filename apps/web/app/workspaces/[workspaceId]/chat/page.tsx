"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { History, RotateCw, Square } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../../../../components/ui/button";
import { Input } from "../../../../components/ui/input";
import { RowSkeleton } from "../../../../components/ui/skeleton";
import { Badge } from "../../../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../../../../components/ui/dialog";
import {
  api,
  type Conversation,
  type SearchResponse,
} from "../../../../lib/api/client";
import type { ChatEvent } from "../../../../lib/chat-stream";
import { streamChat } from "../../../../lib/chat-stream";
import type { components } from "../../../../lib/api/schema";

type SourceRef = components["schemas"]["SourceRef"];
type DisplayMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: SourceRef[];
  streaming?: boolean;
};

function lastAssistantIndex(messages: DisplayMessage[]): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant") return index;
  }
  return -1;
}

export default function ChatPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [snippets, setSnippets] = useState<Record<string, SearchResponse["items"][number]>>({});
  const [activeSource, setActiveSource] = useState<SourceRef | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  const { data: conversations, isLoading } = useQuery({
    queryKey: ["conversations", workspaceId],
    queryFn: () => api.conversations(workspaceId),
  });

  useEffect(() => {
    const firstId = conversations?.[0]?.id;
    if (!conversationId && firstId) void loadConversation(firstId);
  }, [conversations, conversationId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const refreshConversations = () =>
    queryClient.invalidateQueries({ queryKey: ["conversations", workspaceId] });

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

  async function loadConversation(id: string) {
    setConversationId(id);
    setHistoryOpen(false);
    try {
      const history = await api.messages(workspaceId, id);
      setMessages(
        history.map((message) => ({
          id: message.id,
          role: message.role as "user" | "assistant",
          content: message.content,
          citations: (message.citations ?? []) as SourceRef[],
        })),
      );
    } catch {
      toast.error("Could not load that conversation");
    }
  }

  async function send() {
    const query = input.trim();
    if (!query || streaming) return;
    setInput("");
    let conversation = conversationId;
    if (!conversation) {
      const created = await api.createConversation(workspaceId);
      conversation = created.id;
      setConversationId(conversation);
      refreshConversations();
    }

    const userId = `user-${Date.now()}`;
    const assistantId = `assistant-${Date.now()}`;
    setMessages((current) => [
      ...current,
      { id: userId, role: "user", content: query, citations: [] },
      { id: assistantId, role: "assistant", content: "", citations: [], streaming: true },
    ]);

    try {
      const search = await api.search(workspaceId, query);
      setSnippets((current) => ({
        ...current,
        ...Object.fromEntries(search.items.map((item) => [item.chunk_id, item])),
      }));
    } catch {
      // Non-fatal: the answer still streams without preview snippets.
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming(true);
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
      } else if (event.type === "error") {
        toast.error(event.message);
      }
    };

    try {
      await streamChat(
        workspaceId,
        { query, conversation_id: conversation },
        onEvent,
        controller.signal,
      );
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
    setStreaming(false);
  }

  async function regenerate() {
    if (!conversationId || streaming) return;
    setStreaming(true);
    try {
      const response = await api.regenerate(workspaceId, conversationId);
      setMessages((current) =>
        current.map((message, index) =>
          message.role === "assistant" && index === lastAssistantIndex(current)
            ? { ...message, content: response.answer, citations: response.citations }
            : message,
        ),
      );
      toast.success("Answer regenerated");
    } catch {
      toast.error("Could not regenerate the answer");
    } finally {
      setStreaming(false);
    }
  }

  const source = activeSource
    ? {
        ref: activeSource,
        snippet: snippets[activeSource.chunk_id]?.text ?? "Snippet unavailable",
      }
    : null;

  const conversationList = (
    <div className="flex flex-col gap-0.5">
      <Button size="sm" className="mb-2 w-full" onClick={() => createConversation.mutate()}>
        New conversation
      </Button>
      {isLoading ? <RowSkeleton lines={1} /> : null}
      {conversations?.map((conversation: Conversation) => (
        <div key={conversation.id} className="group flex items-center gap-1">
          <button
            className={`min-w-0 flex-1 truncate rounded-[6px] px-2 py-2 text-left text-[12px] hover:bg-muted ${
              conversation.id === conversationId ? "bg-muted font-medium" : "text-muted-foreground"
            }`}
            onClick={() => void loadConversation(conversation.id)}
          >
            {conversation.title}
          </button>
          <Button
            variant="ghost"
            size="sm"
            className="opacity-0 group-hover:opacity-100 focus:opacity-100"
            aria-label="Delete conversation"
            onClick={() => removeConversation.mutate(conversation.id)}
          >
            ×
          </Button>
        </div>
      ))}
    </div>
  );

  return (
    <div className="flex gap-0 lg:gap-6">
      <aside className="hidden w-[220px] shrink-0 border-r border-border pr-4 lg:block">
        {conversationList}
      </aside>

      <section className="flex h-[calc(100dvh-230px)] min-h-[420px] min-w-0 flex-1 flex-col md:h-[calc(100dvh-210px)]">
        <div className="mb-3 flex items-center gap-2 lg:hidden">
          <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
            <Button variant="outline" size="sm" onClick={() => setHistoryOpen(true)}>
              <History size={14} /> Conversations
            </Button>
            <DialogContent side="bottom" className="p-4">
              <DialogTitle>Conversations</DialogTitle>
              <DialogDescription className="mb-3 text-[12px] text-muted-foreground">
                Pick a thread or start a new one.
              </DialogDescription>
              {conversationList}
            </DialogContent>
          </Dialog>
        </div>

        <div ref={scrollRef} className="flex flex-1 flex-col gap-5 overflow-y-auto pb-6">
          {messages.length ? (
            messages.map((message) => (
              <article
                key={message.id}
                className={`result-in max-w-[92%] text-[13px] leading-relaxed sm:max-w-[78%] ${
                  message.role === "user"
                    ? "self-end rounded-[10px] bg-muted px-4 py-3"
                    : "self-start"
                }`}
              >
                <div className="prose-sm break-words [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[12px] [&_pre]:overflow-x-auto [&_pre]:rounded-[8px] [&_pre]:border [&_pre]:border-border [&_pre]:bg-muted [&_pre]:p-3">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {message.content || (message.streaming ? "…" : "")}
                  </ReactMarkdown>
                </div>
                {message.citations.length ? (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {message.citations.map((citation) => (
                      <button
                        key={citation.chunk_id}
                        onClick={() => setActiveSource(citation)}
                        className="inline-flex items-center gap-1 rounded-[6px] border border-border px-1.5 py-0.5 font-mono text-[10px] text-accent hover:bg-muted"
                      >
                        [{citation.number}]
                        <span className="max-w-[120px] truncate font-sans text-muted-foreground">
                          {citation.filename}
                        </span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </article>
            ))
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 py-20 text-center">
              <p className="text-[14px]">Ask anything about your documents.</p>
              <p className="max-w-sm text-[12px] text-muted-foreground">
                Answers come only from the files in this workspace, with citations you can open.
              </p>
            </div>
          )}
        </div>

        <form
          className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t border-border bg-background py-3"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <Input
            value={input}
            aria-label="Question"
            placeholder="Ask a question…"
            onChange={(event) => setInput(event.target.value)}
            className="w-full min-w-0 sm:w-auto sm:flex-1"
          />
          <div className="flex w-full items-center justify-end gap-2 sm:w-auto">
            <Button type="submit" disabled={streaming || !input.trim()}>
              Send
            </Button>
            {streaming ? (
              <Button type="button" variant="outline" onClick={() => void stop()}>
                <Square size={13} /> Stop
              </Button>
            ) : null}
            {!streaming && messages.some((message) => message.role === "assistant") ? (
              <Button type="button" variant="ghost" onClick={() => void regenerate()}>
                <RotateCw size={13} /> <span className="hidden sm:inline">Regenerate</span>
                <span className="sr-only sm:hidden">Regenerate</span>
              </Button>
            ) : null}
          </div>
        </form>
      </section>

      <Dialog
        open={Boolean(activeSource)}
        onOpenChange={(open) => {
          if (!open) setActiveSource(null);
        }}
      >
        <DialogContent side="right" className="p-5">
          {source ? (
            <>
              <DialogTitle className="text-[14px] font-semibold">
                Source [{source.ref.number}]
              </DialogTitle>
              <DialogDescription className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <Badge tone="accent">{source.ref.filename}</Badge>
                {source.ref.page_number ? <span>page {source.ref.page_number}</span> : null}
              </DialogDescription>
              {source.ref.heading_path?.length ? (
                <p className="mt-2 font-mono text-[10px] text-muted-foreground">
                  {source.ref.heading_path.join(" > ")}
                </p>
              ) : null}
              <p className="mt-5 whitespace-pre-wrap rounded-[8px] border border-border bg-muted p-3 text-[12px] leading-relaxed">
                {source.snippet}
              </p>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
