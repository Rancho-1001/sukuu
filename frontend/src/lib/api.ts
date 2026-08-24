/**
 * The one door to the API.
 *
 * Three jobs: attach the token, unwrap the response, and turn the backend's
 * error envelope into something a form can render. The backend guarantees
 * `detail` is always a sentence and that field-level problems arrive beside it
 * under `errors`, so `ApiError` can carry both without any per-call checking.
 *
 * **On 401.** A token that has expired mid-session is not the same as a bad
 * password at the login form. The first should drop the session and send the
 * user back to log in; the second is just a failed attempt and must not clear
 * anything. The difference here is whether a token was sent at all.
 *
 * **On where the token lives.** localStorage, which means script running on
 * this origin can read it. An httpOnly cookie would not be readable, but the
 * API issues bearer tokens rather than setting cookies, and changing that is a
 * backend decision with CSRF consequences of its own. Written down rather than
 * glossed over: this is the weakest link in the auth story.
 */

import type { FieldError } from "./types";

const BASE_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "sukuu.token";

export class ApiError extends Error {
  readonly status: number;
  readonly fields: FieldError[];

  constructor(status: number, message: string, fields: FieldError[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fields = fields;
  }

  /** The message for one field, if the API blamed it. */
  fieldError(name: string): string | undefined {
    return this.fields.find((error) => error.field === name)?.message;
  }
}

export function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    // Safari in private mode throws rather than returning null.
    return null;
  }
}

export function writeToken(token: string | null): void {
  try {
    if (token === null) localStorage.removeItem(TOKEN_KEY);
    else localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* Not fatal: the session simply will not survive a reload. */
  }
}

type Listener = () => void;
let onSessionExpired: Listener = () => {};

/** Wired up by the auth provider, which is the only thing that can react. */
export function setSessionExpiredHandler(listener: Listener): void {
  onSessionExpired = listener;
}

async function parseError(response: Response): Promise<ApiError> {
  let detail = `Request failed (${response.status})`;
  let fields: FieldError[] = [];
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") detail = body.detail;
    if (Array.isArray(body?.errors)) fields = body.errors;
  } catch {
    /* A gateway or proxy answered with something that is not our envelope. */
  }
  return new ApiError(response.status, detail, fields);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = readToken();
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${BASE_URL}${path}`, { ...init, headers });

  if (response.status === 401 && token) {
    // We sent a token and it was refused: the session is over. A 401 with no
    // token is an anonymous request or a failed login, and neither should
    // reach in and clear state.
    writeToken(null);
    onSessionExpired();
  }

  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),

  /**
   * Login speaks form encoding, not JSON.
   *
   * That is the OAuth2 password-flow shape FastAPI's docs "Authorize" button
   * posts, which is what makes the API demonstrable without this frontend. The
   * field is called `username`; ours holds an email.
   */
  login: async (email: string, password: string) => {
    const form = new URLSearchParams({ username: email, password });
    const response = await fetch(`${BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form,
    });
    if (!response.ok) throw await parseError(response);
    return (await response.json()) as import("./types").Token;
  },
};

/** Build a query string, leaving out anything unset. */
export function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : "";
}
