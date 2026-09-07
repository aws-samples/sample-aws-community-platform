import { beforeEach, describe, expect, it } from "vitest";
import { clearSession, loadSession, saveSession, updateSessionToken } from "./session";
import { getAuthToken, setAuthToken } from "./apiClient";

beforeEach(() => {
  sessionStorage.clear();
  setAuthToken(null);
});

describe("session persistence (sessionStorage)", () => {
  it("round-trips a saved session and primes the auth token on load", () => {
    saveSession({ token: "jwt-abc", role: "UserGroupLeader", ledGroupId: "g-1" });
    expect(getAuthToken()).toBeNull(); // save alone does not prime the token
    const s = loadSession();
    expect(s).toEqual({ token: "jwt-abc", role: "UserGroupLeader", ledGroupId: "g-1" });
    expect(getAuthToken()).toBe("jwt-abc"); // load primes apiClient
  });

  it("returns null when nothing is stored", () => {
    expect(loadSession()).toBeNull();
    expect(getAuthToken()).toBeNull();
  });

  it("returns null for a malformed / tokenless payload and does not prime", () => {
    sessionStorage.setItem("cp.session", "not json");
    expect(loadSession()).toBeNull();
    sessionStorage.setItem("cp.session", JSON.stringify({ role: "Member" }));
    expect(loadSession()).toBeNull();
    expect(getAuthToken()).toBeNull();
  });

  it("clearSession removes the stored session", () => {
    saveSession({ token: "jwt-abc", role: "Member" });
    clearSession();
    expect(loadSession()).toBeNull();
  });
});

describe("updateSessionToken (mid-session ID-token refresh)", () => {
  it("replaces the token and keeps every other field", () => {
    saveSession({ token: "old", role: "Member", firstName: "Ana", lastName: "One" });

    const next = updateSessionToken("fresh");

    expect(next).toEqual({ token: "fresh", role: "Member", firstName: "Ana", lastName: "One" });
    expect(loadSession()?.token).toBe("fresh");
  });

  it("does NOT re-prime the old token while reading the stored session", () => {
    // The trap this guards: updateSessionToken reads the stored session in order
    // to rewrite it, and loadSession's side effect is to install whatever token it
    // finds as the active bearer. Reading via loadSession would therefore reinstate
    // the OLD token immediately after refreshSession had installed the new one —
    // silently undoing the refresh. Hence the side-effect-free readSession.
    saveSession({ token: "old", role: "Member" });
    setAuthToken("fresh"); // as refreshSession would have just done

    updateSessionToken("fresh");

    expect(getAuthToken()).toBe("fresh");
  });

  it("is a no-op when no session is stored", () => {
    expect(updateSessionToken("fresh")).toBeNull();
    expect(loadSession()).toBeNull();
  });
});
