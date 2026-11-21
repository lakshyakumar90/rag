/**
 * Browser auth client.
 *
 * The access token lives only in this module's memory (never localStorage, so
 * XSS cannot persist it). The refresh token stays in an HttpOnly, Secure
 * cookie set by the API. Every request uses `credentials: "include"` and
 * retries once after a silent refresh on 401.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
/** Origin-only base, for callers that already pass the `/api/v1/...` path. */
export const API_ORIGIN = API_BASE.replace(/\/api\/v1\/?$/, "");

export type TokenResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_expires_in: number;
};

export type ApiErrorShape = {
  error?: { code?: string; message?: string; request_id?: string };
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code?: string,
    readonly requestId?: string,
  ) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshRequest: Promise<boolean> | undefined;
const listeners = new Set<() => void>();

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  listeners.forEach((listener) => listener());
}

export function clearAccessToken(): void {
  setAccessToken(null);
}

/** Subscribe to token changes so React state can mirror the in-memory store. */
export function subscribeAccessToken(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function readError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as ApiErrorShape;
    return new ApiError(
      response.status,
      body.error?.message ?? `Request failed (${response.status})`,
      body.error?.code,
      body.error?.request_id,
    );
  } catch {
    return new ApiError(response.status, `Request failed (${response.status})`);
  }
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw await readError(response);
  const tokens = (await response.json()) as TokenResponse;
  setAccessToken(tokens.access_token);
  return tokens;
}

export async function register(
  email: string,
  password: string,
  fullName?: string,
): Promise<void> {
  const response = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({
      email,
      password,
      ...(fullName ? { full_name: fullName } : {}),
    }),
  });
  if (!response.ok) throw await readError(response);
}

/** Silent refresh. Returns false when there is no usable session. */
export function refresh(): Promise<boolean> {
  refreshRequest ??= refreshSession().finally(() => {
    refreshRequest = undefined;
  });
  return refreshRequest;
}

async function refreshSession(): Promise<boolean> {
  const priorToken = getAccessToken();
  const response = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  const tokens = response.ok ? ((await response.json()) as TokenResponse) : null;
  if (getAccessToken() === priorToken) {
    setAccessToken(tokens?.access_token ?? null);
  }
  return Boolean(getAccessToken());
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
  setAccessToken(null);
}

/** Fetch with the access token attached; retry once after a silent refresh. */
export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const url = path.startsWith("http")
    ? path
    : path.startsWith("/api/")
      ? `${API_ORIGIN}${path}`
      : `${API_BASE}${path}`;
  const send = (): Promise<Response> =>
    fetch(url, {
      ...init,
      credentials: "include",
      headers: {
        ...init.headers,
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    });

  let response = await send();
  if (response.status === 401 && (await refresh())) {
    response = await send();
  }
  return response;
}

/** Multipart upload with progress events (fetch cannot report upload progress). */
export function uploadWithProgress<T>(
  path: string,
  file: File,
  onProgress: (percent: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const url = path.startsWith("http")
      ? path
      : path.startsWith("/api/")
        ? `${API_ORIGIN}${path}`
        : `${API_BASE}${path}`;
    xhr.open("POST", url);
    xhr.withCredentials = true;
    if (accessToken) xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new ApiError(xhr.status, `Upload failed (${xhr.status})`));
        return;
      }
      onProgress(100);
      try {
        resolve(xhr.responseText ? (JSON.parse(xhr.responseText) as T) : (undefined as T));
      } catch {
        reject(new Error("Invalid upload response"));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

/** Typed convenience wrapper: returns parsed JSON or throws ApiError. */
export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await authFetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  if (!response.ok) throw await readError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
