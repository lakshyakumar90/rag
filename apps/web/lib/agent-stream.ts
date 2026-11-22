/** SSE client for the bounded agent endpoint. */
import { authFetch } from "./auth-client";

export type AgentCitation = {
  number?: number;
  source_type?: "workspace" | "web";
  filename?: string;
  url?: string;
  page_number?: number | null;
  chunk_id?: string;
  document_id?: string;
  text?: string;
};

export type AgentEvent =
  | {
      type: "tool_start" | "tool_result";
      tool: string;
      step: number;
      detail?: string;
      citations?: AgentCitation[];
    }
  | {
      type: "done";
      answer: string;
      citations: AgentCitation[];
      provider: string;
      model?: string | null;
      steps: number;
      tools: string[];
    }
  | { type: "error"; message: string };

export function parseAgentFrame(frame: string): AgentEvent | undefined {
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).replace(/^ /, ""));
  if (!data.length) return undefined;
  try {
    return JSON.parse(data.join("\n")) as AgentEvent;
  } catch {
    return { type: "error", message: "Malformed agent event" };
  }
}

export async function streamAgent(
  workspaceId: string,
  payload: {
    query: string;
    provider?: string;
    model?: string;
    max_steps?: number;
  },
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<AgentEvent | undefined> {
  const response = await authFetch(`/workspaces/${workspaceId}/agent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`Agent request failed (${response.status})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done: AgentEvent | undefined;
  while (true) {
    const { value, done: streamDone } = await reader.read();
    if (streamDone) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const event = parseAgentFrame(frame);
      if (!event) continue;
      onEvent(event);
      if (event.type === "done" || event.type === "error") done = event;
    }
  }
  if (buffer.trim()) {
    const event = parseAgentFrame(buffer);
    if (event) {
      onEvent(event);
      if (event.type === "done" || event.type === "error") done = event;
    }
  }
  return done;
}
