/**
 * Typed API client. All request/response shapes come from schema.d.ts, which
 * is generated from the FastAPI OpenAPI document (`pnpm api:types`).
 */
import { apiRequest } from "../auth-client";
import type { components, operations, paths } from "./schema";

export type ApiPaths = paths;
export type ApiOperations = operations;

export type User = components["schemas"]["UserResponse"];
export type Workspace = components["schemas"]["WorkspaceResponse"];
export type WorkspaceCreate = components["schemas"]["WorkspaceCreate"];
export type LoginRequest = components["schemas"]["LoginRequest"];
export type RegisterRequest = components["schemas"]["RegisterRequest"];
export type TokenResponse = components["schemas"]["TokenResponse"];
export type Document = components["schemas"]["DocumentResponse"];
export type Message = components["schemas"]["MessageResponse"];
export type Conversation = components["schemas"]["ConversationResponse"];
export type ChatResponse = components["schemas"]["ChatResponse"];

/** Generic typed request used by feature code as the API grows. */
export function request<T>(path: keyof paths, init?: RequestInit): Promise<T> {
  return apiRequest<T>(path as string, init);
}

/** For paths containing runtime ids (the response shape is still generated). */
export function requestPath<T>(path: string, init?: RequestInit): Promise<T> {
  return apiRequest<T>(path, init);
}

export const api = {
  me: () => request<User>("/api/v1/users/me"),
  listWorkspaces: () => request<Workspace[]>("/api/v1/workspaces"),
  createWorkspace: (body: WorkspaceCreate) =>
    request<Workspace>("/api/v1/workspaces", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listDocuments: (workspaceId: string) =>
    requestPath<components["schemas"]["DocumentPage"]>(
      `/api/v1/workspaces/${workspaceId}/documents`,
    ),
  listConversations: (workspaceId: string) =>
    requestPath<Conversation[]>(`/api/v1/workspaces/${workspaceId}/conversations`),
  listMessages: (workspaceId: string, conversationId: string) =>
    requestPath<Message[]>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages`,
    ),
};
