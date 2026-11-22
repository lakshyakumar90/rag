/**
 * Typed API client. All request/response shapes come from schema.d.ts, which
 * is generated from the FastAPI OpenAPI document (`pnpm api:types`).
 */
import { apiRequest } from "../auth-client";
import type { components, paths } from "./schema";

export type ApiPaths = paths;
type S = components["schemas"];

export type User = S["UserResponse"];
export type Workspace = S["WorkspaceResponse"];
export type WorkspaceCreate = S["WorkspaceCreate"];
export type Document = S["DocumentResponse"];
export type DocumentPage = S["DocumentPage"];
export type Member = S["MemberResponse"];
export type Invitation = S["InvitationResponse"];
export type InvitationCreated = S["InvitationCreatedResponse"];
export type Conversation = S["ConversationResponse"];
export type Message = S["MessageResponse"];
export type ChatResponse = S["ChatResponse"];
export type SearchResponse = S["SearchResponse"];
export type ProviderConfig = S["ProviderConfigResponse"];
export type ConnectionTest = S["ConnectionTestResponse"];
export type CLIStatus = S["CLIStatusResponse"];
export type FeedbackRequest = S["FeedbackRequest"];
export type FeedbackResponse = S["FeedbackResponse"];
export type Usage = S["UsageResponse"];
export type Analytics = S["AnalyticsResponse"];
export type AuditEntry = S["AuditEntryResponse"];
export type AIProviderOptions = S["ProviderOptionsResponse"];
export type AIProviderOption = S["ProviderOption"];
export type AIDefaults = S["AIDefaultsResponse"];
export type ProviderTest = S["ProviderTestResponse"];
export type ProviderModels = S["ProviderModelsResponse"];

/** Static (parameterless) path, checked against the generated schema. */
export function request<T>(path: keyof paths, init?: RequestInit): Promise<T> {
  return apiRequest<T>(path as string, init);
}

/** For paths containing runtime ids (the response shape is still generated). */
export function requestPath<T>(path: string, init?: RequestInit): Promise<T> {
  return apiRequest<T>(path, init);
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  me: () => request<User>("/api/v1/users/me"),
  updateMe: (fullName: string | null) =>
    apiRequest<User>("/api/v1/users/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name: fullName }),
    }),
  listWorkspaces: () => request<Workspace[]>("/api/v1/workspaces"),
  createWorkspace: (body: WorkspaceCreate) =>
    apiRequest<Workspace>("/api/v1/workspaces", json(body)),
  deleteWorkspace: (id: string) =>
    apiRequest<void>(`/api/v1/workspaces/${id}`, { method: "DELETE" }),

  documents: (workspaceId: string, status?: string) =>
    requestPath<DocumentPage>(
      `/api/v1/workspaces/${workspaceId}/documents${
        status ? `?status=${status}` : ""
      }`,
    ),
  documentSnippet: (workspaceId: string, documentId: string, chunkId: string) =>
    requestPath<S["DocumentSnippetResponse"]>(
      `/api/v1/workspaces/${workspaceId}/documents/${documentId}/chunks/${chunkId}`,
    ),
  deleteDocument: (workspaceId: string, documentId: string) =>
    apiRequest<void>(`/api/v1/workspaces/${workspaceId}/documents/${documentId}`, {
      method: "DELETE",
    }),
  createSource: (workspaceId: string, body: S["SourceCreate"]) =>
    apiRequest<Document>(
      `/api/v1/workspaces/${workspaceId}/sources`,
      json(body),
    ),
  documentGrants: (workspaceId: string, documentId: string) =>
    requestPath<S["GrantResponse"]>(
      `/api/v1/workspaces/${workspaceId}/documents/${documentId}/grants`,
    ),
  updateDocumentGrants: (
    workspaceId: string,
    documentId: string,
    restricted: boolean,
    userIds: string[],
  ) =>
    apiRequest<S["GrantResponse"]>(
      `/api/v1/workspaces/${workspaceId}/documents/${documentId}/grants`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ restricted, user_ids: userIds }),
      },
    ),
  cacheStats: () => request<Record<string, number>>("/api/v1/ai/cache-stats"),
  embeddingProfiles: () =>
    request<S["EmbeddingProfileResponse"][]>("/api/v1/embedding-profiles"),
  createEmbeddingProfile: (body: S["EmbeddingProfileCreate"]) =>
    apiRequest<S["EmbeddingProfileResponse"]>(
      "/api/v1/embedding-profiles",
      json(body),
    ),
  validateEmbeddingProfile: (name: string) =>
    apiRequest<S["EmbeddingProfileValidation"]>(
      `/api/v1/embedding-profiles/${encodeURIComponent(name)}/validate`,
      { method: "POST" },
    ),
  switchWorkspaceProfile: (workspaceId: string, profileName: string) =>
    apiRequest<Record<string, string>>(
      `/api/v1/embedding-profiles/workspaces/${workspaceId}/switch`,
      json({ profile_name: profileName }),
    ),
  reindexDocument: (workspaceId: string, documentId: string) =>
    apiRequest<Document>(
      `/api/v1/workspaces/${workspaceId}/documents/${documentId}/reindex`,
      { method: "POST" },
    ),

  members: (workspaceId: string) =>
    requestPath<Member[]>(`/api/v1/workspaces/${workspaceId}/members`),
  invitations: (workspaceId: string) =>
    requestPath<Invitation[]>(`/api/v1/workspaces/${workspaceId}/invitations`),
  invite: (workspaceId: string, email: string, role: "admin" | "member") =>
    apiRequest<InvitationCreated>(
      `/api/v1/workspaces/${workspaceId}/invitations`,
      json({ email, role }),
    ),
  changeRole: (workspaceId: string, userId: string, role: string) =>
    apiRequest<Member>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    }),
  removeMember: (workspaceId: string, userId: string) =>
    apiRequest<void>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, {
      method: "DELETE",
    }),

  conversations: (workspaceId: string) =>
    requestPath<Conversation[]>(`/api/v1/workspaces/${workspaceId}/conversations`),
  createConversation: (
    workspaceId: string,
    title?: string,
    provider?: string,
    model?: string,
  ) =>
    apiRequest<Conversation>(
      `/api/v1/workspaces/${workspaceId}/conversations`,
      json({ title: title ?? null, provider: provider ?? null, model: model ?? null }),
    ),
  messages: (workspaceId: string, conversationId: string) =>
    requestPath<Message[]>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages`,
    ),
  renameConversation: (workspaceId: string, conversationId: string, title: string) =>
    apiRequest<Conversation>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      },
    ),
  deleteConversation: (workspaceId: string, conversationId: string) =>
    apiRequest<void>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}`,
      { method: "DELETE" },
    ),
  stopGeneration: (workspaceId: string, conversationId: string) =>
    apiRequest<{ cancelled: boolean }>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/stop`,
      { method: "POST" },
    ),
  regenerate: (workspaceId: string, conversationId: string) =>
    apiRequest<ChatResponse>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/regenerate`,
      { method: "POST" },
    ),
  search: (workspaceId: string, query: string) =>
    apiRequest<SearchResponse>(`/api/v1/workspaces/${workspaceId}/search`, json({ query })),

  providerConfigs: () => request<S["ProviderConfigResponse"][]>("/api/v1/provider-configs"),
  addProviderConfig: (body: {
    provider_type: string;
    base_url?: string | null;
    model?: string | null;
    api_key: string;
  }) => apiRequest<ProviderConfig>("/api/v1/provider-configs", json(body)),
  testProviderConfig: (id: string) =>
    apiRequest<ConnectionTest>(`/api/v1/provider-configs/${id}/test`, { method: "POST" }),
  deleteProviderConfig: (id: string) =>
    apiRequest<void>(`/api/v1/provider-configs/${id}`, { method: "DELETE" }),
  cliStatus: () => request<CLIStatus>("/api/v1/providers/cli/status"),

  aiProviders: () => request<AIProviderOptions>("/api/v1/ai/providers"),
  aiDefaults: () => request<AIDefaults>("/api/v1/ai/defaults"),
  saveAIDefaults: (provider: string, model: string | null) =>
    apiRequest<AIDefaults>(
      "/api/v1/ai/defaults",
      json({ provider, model: model || null }),
    ),
  testAIProvider: (provider: string, model?: string | null, configId?: string | null) =>
    apiRequest<ProviderTest>(
      "/api/v1/ai/test",
      json({ provider, model: model || null, config_id: configId || null }),
    ),
  aiModels: (provider: string, configId?: string | null) =>
    requestPath<ProviderModels>(
      `/api/v1/ai/models?provider=${encodeURIComponent(provider)}${
        configId ? `&config_id=${encodeURIComponent(configId)}` : ""
      }`,
    ),
  setConversationSelection: (
    workspaceId: string,
    conversationId: string,
    provider: string | null,
    model: string | null,
  ) =>
    apiRequest<Conversation>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/selection`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, model }),
      },
    ),
  acceptInvitation: (token: string) =>
    apiRequest<Workspace>("/api/v1/invitations/accept", json({ token })),

  setFeedback: (
    workspaceId: string,
    messageId: string,
    vote: "up" | "down",
    comment?: string | null,
  ) =>
    apiRequest<FeedbackResponse>(
      `/api/v1/workspaces/${workspaceId}/messages/${messageId}/feedback`,
      json({ vote, comment: comment ?? null }),
    ),
  usage: (workspaceId: string) =>
    requestPath<Usage>(`/api/v1/workspaces/${workspaceId}/usage`),
  analytics: (workspaceId: string) =>
    requestPath<Analytics>(`/api/v1/workspaces/${workspaceId}/usage/analytics`),
  auditLog: (workspaceId: string) =>
    requestPath<AuditEntry[]>(`/api/v1/workspaces/${workspaceId}/audit-log`),
  exportWorkspace: (workspaceId: string) =>
    requestPath<Record<string, unknown>>(
      `/api/v1/workspaces/${workspaceId}/export`,
    ),
  deleteAccount: () => apiRequest<void>("/api/v1/account", { method: "DELETE" }),
};
