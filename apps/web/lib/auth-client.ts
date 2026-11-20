/**
 * Browser auth client.
 *
 * The access token lives only in this module's memory (never localStorage, so
 * XSS cannot persist it). The refresh token is set by the API as an HttpOnly,
 * Secure cookie and is never exposed to JavaScript — every request that may
 * need it uses `credentials: "include"`.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_expires_in: number;
}

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function clearAccessToken(): void {
  accessToken = null;
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as {
      error?: { message?: string };
    };
    return body.error?.message ?? `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

export async function login(email: string, password: string): Promise<void> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error(await readError(response));
  const tokens = (await response.json()) as TokenResponse;
  accessToken = tokens.access_token;
}

/** Silent refresh. Returns false when there is no usable session. */
export async function refresh(): Promise<boolean> {
  const response = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    accessToken = null;
    return false;
  }
  const tokens = (await response.json()) as TokenResponse;
  accessToken = tokens.access_token;
  return true;
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
  accessToken = null;
}

/** Fetch with the access token attached; retry once after a silent refresh. */
export async function authFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
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
