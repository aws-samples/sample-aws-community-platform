// Thin, contract-bound REST client for the SPA.
// - Base URL + Cognito details come from runtime config.json (injected at deploy, D7).
// - Treats HTTP 501 as a first-class "feature not yet available" signal (FQ8/BR-17)
//   so the UI can render a "coming soon" state while a service is mock/partial.

export interface RuntimeConfig {
  apiEndpoint: string;
  userPoolId: string;
  userPoolClientId: string;
}

export class FeatureNotAvailableError extends Error {
  constructor(public readonly path: string) {
    super(`Feature not available: ${path}`);
    this.name = "FeatureNotAvailableError";
  }
}

export class SessionExpiredError extends Error {
  constructor() {
    super("Your session has expired. Please sign in again.");
    this.name = "SessionExpiredError";
  }
}

// Registered by App so a 401 anywhere forces a clean re-login instead of
// every page independently showing a fetch error.
let _onSessionExpired: (() => void) | null = null;
export function setSessionExpiredHandler(fn: (() => void) | null): void {
  _onSessionExpired = fn;
}

let _config: RuntimeConfig | null = null;

export async function loadConfig(): Promise<RuntimeConfig> {
  if (_config) return _config;
  const res = await fetch("/config.json", { cache: "no-store" });
  _config = (await res.json()) as RuntimeConfig;
  return _config;
}

// Session token from a real login/OTP-verify (US-1.2/1.32), held in memory for the
// life of the tab. apiFetch attaches it to every request unless the caller passes
// an explicit `token` override (e.g. during the login/otp exchange itself).
let _authToken: string | null = null;

export function setAuthToken(token: string | null): void {
  _authToken = token;
}

export function getAuthToken(): string | null {
  return _authToken;
}

// Cognito refresh token, held IN MEMORY ONLY and never persisted — not in
// sessionStorage alongside the session, and certainly not in localStorage. See
// session.ts for the "short-lived JWT off persistent storage" stance this keeps
// intact: a refresh token is long-lived and would be a materially bigger prize.
//
// The cost of memory-only is bounded and acceptable: it survives exactly as long
// as the JS context, which is all `refreshSession` needs, because the only caller
// is a group join/leave in the same context that logged in. After a page reload
// the token is gone, `refreshSession` becomes a no-op, and group membership stays
// as the current ID token has it until the next sign-in — which is the same
// position OTP-gated users are in permanently (they get no refresh token at all).
let _refreshToken: string | null = null;

export function setRefreshToken(token: string | null): void {
  _refreshToken = token;
}

export function hasRefreshToken(): boolean {
  return Boolean(_refreshToken);
}

/** Re-mint the ID token so custom claims (role, group membership) are current.
 *
 * Returns the new token on success, or null when refresh is unavailable or fails.
 * NEVER throws and never triggers the session-expired path: a failed refresh
 * leaves the existing, still-valid token in place. Signing the user out because
 * we could not *improve* their token would be a worse outcome than the staleness
 * being fixed. */
export async function refreshSession(): Promise<string | null> {
  if (!_refreshToken) return null;
  try {
    // `token: ""` suppresses the Authorization header: this endpoint is public,
    // and the bearer we hold is the stale token being replaced.
    const res = await apiFetch<{ token?: string }>("/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refreshToken: _refreshToken }),
      token: "",
    });
    if (!res?.token) return null;
    setAuthToken(res.token);
    return res.token;
  } catch {
    return null;
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { token?: string } = {},
): Promise<T> {
  const cfg = await loadConfig();
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const token = init.token ?? _authToken;
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${cfg.apiEndpoint}${path}`, { ...init, headers });
  } catch {
    // Browser-level failure (network down, or a response blocked for missing
    // CORS headers). Raw "Failed to fetch" is meaningless to users.
    throw new Error("Could not reach the server. Check your connection and try again; if the problem persists, sign out and back in.");
  }

  // Cognito authorizer rejection — token expired or invalid. Trigger re-login.
  if (res.status === 401 && _authToken && !path.startsWith("/auth")) {
    _onSessionExpired?.();
    throw new SessionExpiredError();
  }

  if (res.status === 501) throw new FeatureNotAvailableError(path); // coming soon
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    let message = (body && (body.message as string)) || `Request failed: ${res.status}`;
    // Surface per-field validation details as human sentences ("Bio: length
    // must be 1-2000") — "Validation failed." alone is useless. The field name is
    // capitalised so it reads as prose rather than a raw field:message join.
    const details = body?.details as { field?: string; message?: string }[] | undefined;
    if (Array.isArray(details) && details.length > 0) {
      const sentences = details.map((d) => {
        const field = d.field ? d.field.charAt(0).toUpperCase() + d.field.slice(1) : "";
        return [field, d.message].filter(Boolean).join(": ");
      });
      message += " " + sentences.join("; ");
    }
    throw new Error(message);
  }
  return body as T;
}

// Raw-text sibling of apiFetch, for endpoints that return something other than
// JSON. Added for the event .ics download (US-2.8): the endpoint is behind the
// Cognito authorizer, so a plain <a href> would arrive unauthenticated, and
// apiFetch would try to JSON-parse an iCalendar body.
export async function apiFetchText(
  path: string,
  init: RequestInit & { token?: string } = {},
): Promise<string> {
  const cfg = await loadConfig();
  const headers = new Headers(init.headers);
  const token = init.token ?? _authToken;
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${cfg.apiEndpoint}${path}`, { ...init, headers });
  } catch {
    throw new Error("Could not reach the server. Check your connection and try again.");
  }
  if (res.status === 401 && _authToken) {
    _onSessionExpired?.();
    throw new SessionExpiredError();
  }
  if (res.status === 501) throw new FeatureNotAvailableError(path);
  const text = await res.text();
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return text;
}

// Trigger a browser download for text content fetched through apiFetchText.
export function downloadText(filename: string, content: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// Direct-to-S3 upload via a presigned POST grant (Unit 6 evidence/badge
// uploads). NO Authorization header and NO JSON content type: the request goes
// to S3, not the API, and the policy in `fields` is the entire authorization —
// including the 5 MB size cap and exact content type, which S3 itself enforces
// (a too-big file fails here with a 4xx rather than ever reaching a reviewer).
export interface UploadGrant {
  fileKey: string;
  uploadUrl: string;
  fields: Record<string, string>;
}

export async function uploadToPresignedPost(grant: UploadGrant, file: File): Promise<void> {
  const form = new FormData();
  Object.entries(grant.fields).forEach(([k, v]) => form.append(k, v));
  form.append("file", file); // must be LAST per S3 POST rules
  let res: Response;
  try {
    res = await fetch(grant.uploadUrl, { method: "POST", body: form });
  } catch {
    throw new Error("Could not reach file storage. Check your connection and try again.");
  }
  if (!res.ok) {
    if (res.status === 400 || res.status === 403) {
      throw new Error("Upload rejected — the file may exceed 5 MB or have the wrong type.");
    }
    throw new Error(`Upload failed: ${res.status}`);
  }
}
