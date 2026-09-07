import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getAuthToken, refreshSession, setAuthToken, setRefreshToken, hasRefreshToken } from "./apiClient";
import { loadSession, saveSession } from "./session";
import { refreshMembershipClaims } from "./refreshMembership";

// The refresh flow's contract is mostly about what it must NOT do: it must not
// throw, must not sign the user out, and must not clobber a good token when the
// refresh fails. Those are the cases exercised here.

const FETCH_OK = (token: string) =>
  vi.fn().mockImplementation((url: string) => {
    if (String(url).endsWith("/config.json")) {
      return Promise.resolve(new Response(JSON.stringify({
        apiEndpoint: "https://api.test", userPoolId: "p", userPoolClientId: "c",
      }), { status: 200 }));
    }
    return Promise.resolve(new Response(JSON.stringify({ token }), { status: 200 }));
  });

const FETCH_STATUS = (status: number, body: unknown = {}) =>
  vi.fn().mockImplementation((url: string) => {
    if (String(url).endsWith("/config.json")) {
      return Promise.resolve(new Response(JSON.stringify({
        apiEndpoint: "https://api.test", userPoolId: "p", userPoolClientId: "c",
      }), { status: 200 }));
    }
    return Promise.resolve(new Response(JSON.stringify(body), { status }));
  });

beforeEach(() => {
  sessionStorage.clear();
  setAuthToken(null);
  setRefreshToken(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("refresh token storage", () => {
  it("is held in memory and never written to sessionStorage", () => {
    saveSession({ token: "id-token", role: "Member" });
    setRefreshToken("refresh-secret");

    expect(hasRefreshToken()).toBe(true);
    // The stored session must contain no trace of it — a long-lived credential on
    // disk-adjacent storage is exactly what session.ts set out to avoid.
    const raw = sessionStorage.getItem("cp.session") ?? "";
    expect(raw).not.toContain("refresh-secret");
    expect(loadSession()).toEqual({ token: "id-token", role: "Member" });
  });
});

describe("refreshSession", () => {
  it("installs the new token and returns it", async () => {
    vi.stubGlobal("fetch", FETCH_OK("new-id-token"));
    setAuthToken("stale-id-token");
    setRefreshToken("refresh-secret");

    const out = await refreshSession();

    expect(out).toBe("new-id-token");
    expect(getAuthToken()).toBe("new-id-token");
  });

  it("returns null without calling the API when no refresh token is held", async () => {
    const fetchMock = FETCH_OK("unused");
    vi.stubGlobal("fetch", fetchMock);
    setAuthToken("stale-id-token");

    expect(await refreshSession()).toBeNull();
    // This is the post-reload and OTP-login case. It must be free, not a failed
    // round-trip on every join.
    expect(fetchMock).not.toHaveBeenCalled();
    expect(getAuthToken()).toBe("stale-id-token");
  });

  it("keeps the existing token when the refresh is rejected", async () => {
    vi.stubGlobal("fetch", FETCH_STATUS(401, { message: "expired" }));
    setAuthToken("stale-id-token");
    setRefreshToken("expired-refresh");

    expect(await refreshSession()).toBeNull();
    // A failed refresh must NOT sign the user out. Their current token is still
    // valid; all they lose is the claim update.
    expect(getAuthToken()).toBe("stale-id-token");
  });

  it("returns null rather than throwing when the network fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      if (String(url).endsWith("/config.json")) {
        return Promise.resolve(new Response(JSON.stringify({
          apiEndpoint: "https://api.test", userPoolId: "p", userPoolClientId: "c",
        }), { status: 200 }));
      }
      return Promise.reject(new TypeError("network down"));
    }));
    setAuthToken("stale-id-token");
    setRefreshToken("refresh-secret");

    await expect(refreshSession()).resolves.toBeNull();
    expect(getAuthToken()).toBe("stale-id-token");
  });

  it("treats a 200 with no token as a failure", async () => {
    vi.stubGlobal("fetch", FETCH_STATUS(200, {}));
    setAuthToken("stale-id-token");
    setRefreshToken("refresh-secret");

    expect(await refreshSession()).toBeNull();
    // Installing "" as the bearer would turn one failed refresh into a 401 on the
    // next call, and a 401 forces a sign-out.
    expect(getAuthToken()).toBe("stale-id-token");
  });
});

describe("refreshMembershipClaims", () => {
  it("syncs the persisted session so a reload keeps the fresh token", async () => {
    vi.stubGlobal("fetch", FETCH_OK("new-id-token"));
    saveSession({ token: "stale-id-token", role: "Member" });
    setAuthToken("stale-id-token");
    setRefreshToken("refresh-secret");

    await refreshMembershipClaims();

    expect(getAuthToken()).toBe("new-id-token");
    expect(loadSession()?.token).toBe("new-id-token");
  });

  it("leaves the stored session untouched when refresh is unavailable", async () => {
    vi.stubGlobal("fetch", FETCH_STATUS(401));
    saveSession({ token: "stale-id-token", role: "Member" });
    setAuthToken("stale-id-token");
    setRefreshToken("expired-refresh");

    await expect(refreshMembershipClaims()).resolves.toBeUndefined();

    expect(loadSession()?.token).toBe("stale-id-token");
  });

  it("never throws, so a successful join is never reported as a failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("everything is broken")));
    setRefreshToken("refresh-secret");

    await expect(refreshMembershipClaims()).resolves.toBeUndefined();
  });
});
