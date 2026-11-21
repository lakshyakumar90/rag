/** SSE client for the streaming chat endpoint. */
import { authFetch } from "./auth-client";
import type { ChatResponse } from "./api/client";
import type { components } from "./api/schema";

type SourceRef = components["schemas"]["SourceRef"];

export type ChatEvent =
  | { type: "sources"; sources: SourceRef[] }
  | { type: "token"; text: string }
  | {
      type: "done";
      answer: string;
      answerable: boolean;
      citations: SourceRef[];
      tokens?: { input: number; output: number; estimated: boolean };
      conversation_id?: string;
    }
  | { type: "error"; message: string };

export async function streamChat(
  workspaceId: string,
  payload: {
    query: string;
    conversation_id?: string;
    document_ids?: string[];
    provider?: string;
  },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<ChatResponse | undefined> {
  const response = await authFetch(`/workspaces/${workspaceId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`Chat request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done: ChatResponse | undefined;

  while (true) {
    const { value, done: finished } = await reader.read();
    if (finished) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((part) => part.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.slice(6)) as ChatEvent;
      onEvent(event);
      if (event.type === "done") {
        done = {
          answer: event.answer,
          answerable: event.answerable,
          citations: event.citations,
          sources: [],
          provider: "",
          conversation_id: event.conversation_id,
        } as ChatResponse;
      }
    }
  }
  return done;
}
