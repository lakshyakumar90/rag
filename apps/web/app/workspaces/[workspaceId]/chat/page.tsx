"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";
import { Button } from "../../../../components/ui/button";
import { Card } from "../../../../components/ui/card";
import { Input } from "../../../../components/ui/input";
import { Skeleton } from "../../../../components/ui/skeleton";
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
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [snippets, setSnippets] = useState<Record<string, SearchResponse["items"][number]>>({});
  const [activeSource, setActiveSource] = useState<SourceRef | null>(null);

  const { data: conversations, isLoading } = useQuery({
    queryKey: ["conversations", workspaceId],
    queryFn: () => api.conversations(workspaceId),
  });

  useEffect(() => {
    const firstId = conversations?.[0]?.id;
    if (!conversationId && firstId) loadConversation(firstId);
  }, [conversations, conversationId]);

  const refreshConversations = () =>
    queryClient.invalidateQueries({ queryKey: ["conversations", workspaceId] });

  const createConversation = useMutation({
    mutationFn: () => api.createConversation(workspaceId),
    onSuccess: (conversation) => {
      setConversationId(conversation.id);
      setMessages([]);
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
      toast.error("Could not load conversation");
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

    // Fetch snippets for the citation side panel (SearchResult carries text).
    try {
      const search = await api.search(workspaceId, query);
      setSnippets((current) => ({
        ...current,
        ...Object.fromEntries(search.items.map((item) => [item.chunk_id, item])),
      }));
    } catch {
      // Non-fatal: citations still work without snippets.
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming(true);
    const onEvent = (event: ChatEvent) => {
      if (event.type === "sources") {
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId
              ? { ...message, citations: event.sources }
              : message,
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
      try { await api.stopGeneration(workspaceId, conversationId); } catch { /* already stopped */ }
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
      toast.error("Could not regenerate answer");
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

  return (
    <div className="flex min-h-[70vh] gap-6">
      <aside className="w-56 shrink-0 border-r border-border pr-4">
        <Button className="mb-3 w-full" onClick={() => createConversation.mutate()}>
          New conversation
        </Button>
        {isLoading ? <Skeleton className="h-8 w-full" /> : null}
        <div className="flex flex-col gap-1">
          {conversations?.map((conversation: Conversation) => (
            <div key={conversation.id} className="flex items-center gap-1">
              <button
                className={`flex-1 truncate rounded px-2 py-1 text-left text-sm hover:bg-muted ${
                  conversation.id === conversationId ? "bg-muted font-medium" : ""
                }`}
                onClick={() => loadConversation(conversation.id)}
              >
                {conversation.title}
              </button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => removeConversation.mutate(conversation.id)}
                aria-label="Delete conversation"
              >
                ×
              </Button>
            </div>
          ))}
        </div>
      </aside>

      <section className="flex flex-1 flex-col gap-4">
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto">
          {messages.length ? (
            messages.map((message) => (
              <Card
                key={message.id}
                className={`max-w-[85%] p-4 ${
                  message.role === "user" ? "ml-auto bg-primary/10" : "mr-auto"
                }`}
              >
                <div className="prose-sm break-words text-sm">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      code: ({ children, className }) => (
                        <code className={`rounded bg-muted px-1 py-0.5 font-mono ${className ?? ""}`}>
                          {children}
                        </code>
                      ),
                    }}
                  >
                    {message.content || (message.streaming ? "…" : "")}
                  </ReactMarkdown>
                </div>
                {message.citations.length ? (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {message.citations.map((citation) => (
                      <button
                        key={citation.chunk_id}
                        className="rounded-full border border-border px-2 py-0.5 text-xs hover:bg-muted"
                        onClick={() => setActiveSource(citation)}
                      >
                        [{citation.number}] {citation.filename}
                      </button>
                    ))}
                  </div>
                ) : null}
              </Card>
            ))
          ) : (
            <div className="py-20 text-center text-muted-foreground">
              Ask a question about your uploaded documents.
            </div>
          )}
        </div>

        <div className="flex gap-2">
          <Input
            value={input}
            placeholder="Ask a question…"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") send(); }}
          />
          <Button onClick={send} disabled={streaming || !input.trim()}>Send</Button>
          {streaming ? <Button variant="outline" onClick={stop}>Stop</Button> : null}
          {!streaming && messages.some((message) => message.role === "assistant") ? (
            <Button variant="outline" onClick={regenerate}>Regenerate</Button>
          ) : null}
        </div>
      </section>

      {source ? (
        <aside className="w-80 shrink-0 border-l border-border pl-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-semibold">Source [{source.ref.number}]</h3>
            <Button variant="ghost" size="sm" onClick={() => setActiveSource(null)}>×</Button>
          </div>
          <p className="text-sm font-medium">{source.ref.filename}</p>
          {source.ref.page_number ? (
            <p className="text-xs text-muted-foreground">Page {source.ref.page_number}</p>
          ) : null}
          {source.ref.heading_path?.length ? (
            <p className="text-xs text-muted-foreground">
              {source.ref.heading_path.join(" > ")}
            </p>
          ) : null}
          <p className="mt-3 whitespace-pre-wrap rounded bg-muted p-3 text-sm">{source.snippet}</p>
        </aside>
      ) : null}
    </div>
  );
}
