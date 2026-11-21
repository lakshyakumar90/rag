/** SSE client for the streaming chat endpoint (POST + fetch stream reader). */
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

type StreamOptions = {
  maxRetries?: number;
  retryDelayMs?: number;
};

/** Split an SSE buffer into frames, keeping any trailing partial frame. */
export function splitSseFrames(buffer: string): { frames: string[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const parts = normalized.split("\n\n");
  return { frames: parts.slice(0, -1), rest: parts[parts.length - 1] ?? "" };
}

/** Parse one SSE frame; multi-line `data:` fields are joined with newlines. */
export function parseSseFrame(frame: string): ChatEvent | undefined {
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return undefined;
  try {
    return JSON.parse(data.join("\n")) as ChatEvent;
  } catch {
    return { type: "error", message: "Malformed stream event" };
  }
}

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
  options: StreamOptions = {},
): Promise<ChatResponse | undefined> {
  const maxRetries = options.maxRetries ?? 1;
  const delay = options.retryDelayMs ?? 300;
  let done: ChatResponse | undefined;
  let attempt = 0;

  while (attempt <= maxRetries) {
    let receivedToken = false;
    try {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
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

      while (true) {
        const { value, done: finished } = await reader.read();
        if (finished) break;
        buffer += decoder.decode(value, { stream: true });
        const { frames, rest } = splitSseFrames(buffer);
        buffer = rest;
        for (const frame of frames) {
          const event = parseSseFrame(frame);
          if (!event) continue;
          if (event.type === "token") receivedToken = true;
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
      // Flush a final frame that lacked a trailing blank line.
      if (buffer.trim()) {
        const event = parseSseFrame(buffer);
        if (event) onEvent(event);
      }
      return done;
    } catch (error) {
      if (signal?.aborted || (error instanceof DOMException && error.name === "AbortError")) {
        throw error;
      }
      // Retrying after tokens would duplicate the assistant message; only
      // reconnect when the stream failed before producing any content.
      if (attempt >= maxRetries || receivedToken) throw error;
      attempt += 1;
      onEvent({
        type: "error",
        message: `Stream interrupted, reconnecting (${attempt}/${maxRetries})…`,
      });
      await new Promise((resolve) => setTimeout(resolve, delay * attempt));
    }
  }
  return done;
}
