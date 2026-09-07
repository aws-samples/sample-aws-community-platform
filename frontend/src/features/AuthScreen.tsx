import React, { useEffect, useState } from "react";
import { apiFetch, setAuthToken, setRefreshToken } from "../lib/apiClient";
import type { Role } from "../roles";
import type { Session } from "../lib/session";
import PasswordInput from "../components/PasswordInput";

interface LoginResponse {
  token?: string;
  // Present on the password path only, absent on the OTP path (see
  // auth_service.verify_otp for why). Optional therefore means "refresh may not
  // be available", not "the server forgot to send it".
  refreshToken?: string;
  role: Role;
  otpRequired: boolean;
  challengeId?: string;
  ledGroupId?: string;
  firstName?: string;
  lastName?: string;
}

// Real auth screen wired to the Identity & Access service (US-1.2 login,
// US-1.32 OTP re-verification, US-1.30 self-registration, US-1.20 password
// reset). Every user, including the bootstrap Administrator (US-1.27), signs
// in and resets their password through the same Cognito-backed flow. No
// client-side role picker — the role comes back from the API.
export default function AuthScreen({ onSignedIn }: { onSignedIn: (session: Session) => void }) {
  const [tab, setTab] = useState<"login" | "register">("login");
  // Pre-login gate (US-1.30 addendum) — the Self-Registration tab is HIDDEN by
  // default and only appears once /public/settings confirms it's enabled.
  // (Defaulting to shown caused the tab to flash for a moment and then vanish
  // when the Administrator had turned it off. Hidden-until-confirmed is also
  // the safer default when settings are unreachable.)
  const [selfRegistrationEnabled, setSelfRegistrationEnabled] = useState(false);
  const [communityName, setCommunityName] = useState("AWS Community Portal");
  const [logoUrl, setLogoUrl] = useState("");

  useEffect(() => {
    apiFetch<{ selfRegistrationEnabled?: boolean; communityName?: string; logoUrl?: string }>("/public/settings")
      .then((s) => {
        // Strictly `=== true`: show ONLY on an explicit enabled. `!== false`
        // would also show the tab when the field is absent from the response
        // (partial payload, contract change, a proxy trimming the body), which
        // is the one fail-open left in an otherwise hidden-by-default gate.
        if (s.selfRegistrationEnabled === true) setSelfRegistrationEnabled(true);
        if (s.communityName) setCommunityName(s.communityName);
        if (s.logoUrl) setLogoUrl(s.logoUrl);
      })
      .catch(() => { /* settings unreachable — keep the tab hidden */ });
  }, []);

  useEffect(() => {
    if (!selfRegistrationEnabled) setTab("login");
  }, [selfRegistrationEnabled]);

  // Login state
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);

  // Forgot-password state (US-1.20 — Cognito hosted forgot-password flow,
  // two steps: request a code, then submit code + new password).
  const [resetOpen, setResetOpen] = useState(false);
  const [resetStep, setResetStep] = useState<"request" | "confirm">("request");
  const [resetEmail, setResetEmail] = useState("");
  const [resetCode, setResetCode] = useState("");
  const [resetNewPassword, setResetNewPassword] = useState("");
  const [resetConfirmPassword, setResetConfirmPassword] = useState("");
  const [resetMessage, setResetMessage] = useState<string | null>(null);
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetBusy, setResetBusy] = useState(false);

  const resetPasswordsMismatch = resetConfirmPassword.length > 0 && resetNewPassword !== resetConfirmPassword;

  const openReset = () => {
    setResetOpen(true);
    setResetStep("request");
    setResetEmail(loginEmail);
    setResetCode("");
    setResetNewPassword("");
    setResetConfirmPassword("");
    setResetMessage(null);
    setResetError(null);
  };

  const closeReset = () => setResetOpen(false);

  const submitResetRequest = async () => {
    setResetError(null);
    setResetBusy(true);
    try {
      const res = await apiFetch<{ message: string }>("/auth/reset", {
        method: "POST",
        body: JSON.stringify({ email: resetEmail }),
      });
      setResetMessage(res.message);
      setResetStep("confirm");
    } catch (e) {
      setResetError((e as Error).message || "Could not send the reset code.");
    } finally {
      setResetBusy(false);
    }
  };

  // Re-send the code without leaving the confirm step (previously this called
  // setResetStep("request"), which collapsed the code/new-password fields back
  // to the email-only step — losing whatever the user had already entered).
  const resendResetCode = async () => {
    setResetError(null);
    setResetBusy(true);
    try {
      const res = await apiFetch<{ message: string }>("/auth/reset", {
        method: "POST",
        body: JSON.stringify({ email: resetEmail }),
      });
      setResetMessage(res.message);
    } catch (e) {
      setResetError((e as Error).message || "Could not send the reset code.");
    } finally {
      setResetBusy(false);
    }
  };

  const submitResetConfirm = async () => {
    setResetError(null);
    if (resetNewPassword !== resetConfirmPassword) {
      setResetError("Passwords do not match.");
      return;
    }
    setResetBusy(true);
    try {
      await apiFetch("/auth/reset/confirm", {
        method: "POST",
        // .trim(): codes are pasted out of an email and routinely arrive with a
        // trailing space or newline, which Cognito compares literally and
        // rejects as a mismatch. The server strips too (that is the
        // authoritative fix); this keeps the bad value from leaving the browser.
        body: JSON.stringify({ email: resetEmail.trim(), code: resetCode.trim(), newPassword: resetNewPassword }),
      });
      setResetOpen(false);
      setLoginEmail(resetEmail);
      setLoginPassword("");
      setLoginError(null);
    } catch (e) {
      setResetError((e as Error).message || "Could not reset the password.");
    } finally {
      setResetBusy(false);
    }
  };

  // Register state — no password fields (BR-P8). Registration collects identity
  // only; the credential is established via the inline set-password step below.
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [registerBusy, setRegisterBusy] = useState(false);

  // Post-registration set-password step: after /auth/register succeeds the UI
  // automatically calls /auth/reset to send the verification code, then shows
  // this inline form so the user sets a password and signs in without leaving
  // the screen.
  const [regStep, setRegStep] = useState<"form" | "set-password">("form");
  const [regSetCode, setRegSetCode] = useState("");
  const [regSetPassword, setRegSetPassword] = useState("");
  const [regSetConfirm, setRegSetConfirm] = useState("");
  const [regSetError, setRegSetError] = useState<string | null>(null);
  const [regSetBusy, setRegSetBusy] = useState(false);
  const regSetMismatch = regSetConfirm.length > 0 && regSetPassword !== regSetConfirm;

  const resetRegForm = () => {
    setRegStep("form");
    setRegSetCode(""); setRegSetPassword(""); setRegSetConfirm(""); setRegSetError(null);
  };

  const completeSession = (res: LoginResponse) => {
    if (!res.token) return;
    setAuthToken(res.token);
    // In-memory only, and NOT part of the Session object below — Session is what
    // gets written to sessionStorage, and the refresh token must never land there.
    setRefreshToken(res.refreshToken ?? null);
    onSignedIn({
      token: res.token,
      role: res.role,
      ledGroupId: res.ledGroupId,
      firstName: res.firstName,
      lastName: res.lastName,
    });
  };

  const submitLogin = async () => {
    setLoginError(null);
    setLoginBusy(true);
    try {
      const res = await apiFetch<LoginResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: loginEmail, password: loginPassword }),
      });
      if (res.otpRequired && res.challengeId) {
        setChallengeId(res.challengeId);
      } else {
        completeSession(res);
      }
    } catch (e) {
      setLoginError((e as Error).message || "Sign in failed. Check your email and password.");
    } finally {
      setLoginBusy(false);
    }
  };

  const submitOtp = async () => {
    if (!challengeId) return;
    setLoginError(null);
    setLoginBusy(true);
    try {
      const res = await apiFetch<LoginResponse>("/auth/otp", {
        method: "POST",
        body: JSON.stringify({ code: otpCode, challengeId }),
      });
      completeSession(res);
    } catch (e) {
      setLoginError((e as Error).message || "Invalid or expired code.");
    } finally {
      setLoginBusy(false);
    }
  };

  // Step 1 — create account, then auto-send reset code and show set-password step.
  const submitRegister = async () => {
    setRegisterError(null);
    setRegisterBusy(true);
    try {
      await apiFetch<{ message?: string }>("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email: regEmail, firstName, lastName }),
      });
      // Auto-trigger the forgot-password code send so the user can set their
      // password inline without having to navigate anywhere.
      await apiFetch<{ message: string }>("/auth/reset", {
        method: "POST",
        body: JSON.stringify({ email: regEmail }),
      });
      setRegStep("set-password");
    } catch (e) {
      setRegisterError((e as Error).message || "Registration failed.");
    } finally {
      setRegisterBusy(false);
    }
  };

  // Step 2 — confirm reset code + new password, then auto sign in.
  const submitRegSetPassword = async () => {
    if (regSetPassword !== regSetConfirm) { setRegSetError("Passwords do not match."); return; }
    setRegSetError(null);
    setRegSetBusy(true);
    try {
      await apiFetch("/auth/reset/confirm", {
        method: "POST",
        body: JSON.stringify({ email: regEmail.trim(), code: regSetCode.trim(), newPassword: regSetPassword }),
      });
      // Password set — auto sign in immediately.
      const res = await apiFetch<LoginResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: regEmail, password: regSetPassword }),
      });
      if (res.otpRequired && res.challengeId) {
        // Edge case: OTP required even after confirmResetPassword (e.g. system
        // clock skew). Drop to the login tab with the challenge pre-loaded.
        setChallengeId(res.challengeId);
        setLoginEmail(regEmail);
        setTab("login");
        resetRegForm();
      } else {
        completeSession(res);
      }
    } catch (e) {
      setRegSetError((e as Error).message || "Could not set your password. Check the code and try again.");
    } finally {
      setRegSetBusy(false);
    }
  };

  const resendRegCode = async () => {
    setRegSetError(null);
    setRegSetBusy(true);
    try {
      await apiFetch<{ message: string }>("/auth/reset", {
        method: "POST",
        body: JSON.stringify({ email: regEmail }),
      });
    } catch (e) {
      setRegSetError((e as Error).message || "Could not resend the code.");
    } finally {
      setRegSetBusy(false);
    }
  };

  // Shared auth button style
  const authBtnStyle: React.CSSProperties = {
    width: "100%", padding: "13px", background: "linear-gradient(135deg, #1f5fbf, #174a96)",
    color: "#fff", border: "none", borderRadius: 10, fontSize: 14.5, fontWeight: 700,
    cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
    gap: 8, boxShadow: "0 2px 8px rgba(31,95,191,.30)", letterSpacing: 0.1,
  };
  const authBtnDisabledStyle: React.CSSProperties = {
    ...authBtnStyle,
    background: "linear-gradient(135deg, #5b8dd9, #4a74bf)",
    boxShadow: "none", cursor: "not-allowed",
  };  const authInputStyle: React.CSSProperties = {
    width: "100%", padding: "11px 12px 11px 38px", border: "1.5px solid #e2e8f0",
    borderRadius: 9, fontSize: 14, fontFamily: "inherit", color: "#1e293b",
    background: "#fff", boxSizing: "border-box",
  };
  const fieldLabelStyle: React.CSSProperties = {
    display: "block", fontSize: 13, fontWeight: 600, color: "#334155", marginBottom: 6,
  };
  const fieldWrapStyle: React.CSSProperties = { marginBottom: 16 };
  const iconWrapStyle: React.CSSProperties = { position: "relative" };
  const fieldIconStyle: React.CSSProperties = {
    position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)",
    color: "#94a3b8", fontSize: 15, pointerEvents: "none", lineHeight: 1,
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "stretch", overflow: "hidden" }}>

      {/* ── Left brand panel ── */}
      <div style={{
        width: 400, flexShrink: 0, background: "linear-gradient(160deg, #0f2d5e 0%, #1a4a9e 55%, #7c3aed 100%)",
        display: "flex", flexDirection: "column", justifyContent: "space-between",
        padding: "48px 44px", color: "#fff", position: "relative", overflow: "hidden",
      }} className="auth-brand-panel">

        {/* decorative circles */}
        <div style={{
          position: "absolute", width: 380, height: 380, borderRadius: "50%",
          background: "rgba(255,255,255,.04)", top: -80, right: -120,
        }} />
        <div style={{
          position: "absolute", width: 260, height: 260, borderRadius: "50%",
          background: "rgba(255,153,0,.08)", bottom: 60, left: -60,
        }} />

        {/* Logo + name */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, position: "relative", zIndex: 1 }}>
          {logoUrl
            ? <img src={logoUrl} alt={communityName} style={{ width: 48, height: 48, borderRadius: 12, objectFit: "contain" }} />
            : <div style={{
                width: 48, height: 48, borderRadius: 12, flexShrink: 0,
                background: "linear-gradient(135deg, #FF9900, #e67e00)",
                display: "grid", placeItems: "center", fontSize: 22, fontWeight: 900,
                color: "#fff", boxShadow: "0 4px 14px rgba(255,153,0,.45)",
              }}>A</div>}
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, lineHeight: 1.25 }}>{communityName}</div>
          </div>
        </div>

        {/* Tagline + features */}
        <div style={{ position: "relative", zIndex: 1 }}>
          <h2 style={{ fontSize: 30, fontWeight: 800, lineHeight: 1.25, margin: "0 0 14px", letterSpacing: -0.4 }}>
            Your community.<br />Your <span style={{ color: "#FF9900" }}>achievements</span>.<br />One place.
          </h2>
          <p style={{ fontSize: 14, opacity: 0.75, lineHeight: 1.6, margin: "0 0 28px" }}>
            Connect with builders, track certifications and contributions, collaborate in group forums, and stay ahead with live AWS news.
          </p>
          {[
            { ic: "🏆", txt: "Track certifications & earn contribution points" },
            { ic: "📅", txt: "Discover and RSVP to community events" },
            { ic: "💬", txt: "Collaborate in group forums & discussions" },
            { ic: "🔔", txt: "Live \"What's New in AWS\" feed with smart search" },
          ].map(({ ic, txt }) => (
            <div key={txt} style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 13.5, opacity: 0.85, marginBottom: 13 }}>
              <div style={{
                width: 34, height: 34, borderRadius: 8, background: "rgba(255,255,255,.12)",
                display: "grid", placeItems: "center", fontSize: 16, flexShrink: 0,
              }}>{ic}</div>
              {txt}
            </div>
          ))}
        </div>

        <div style={{ fontSize: 12, opacity: 0.4, position: "relative", zIndex: 1 }}>
          {communityName} · Community Portal
        </div>
      </div>

      {/* ── Right form panel ── */}
      <div style={{
        flex: 1, minWidth: 0, display: "flex", flexDirection: "column", alignItems: "center",
        justifyContent: "center", padding: "48px 40px", background: "#f0f4f8", overflowY: "auto",
        maxWidth: 700,
      }}>
        <div style={{
          width: "100%", maxWidth: 420,
          background: "#fff", borderRadius: 16,
          padding: "36px 36px",
          boxShadow: "0 4px 24px rgba(15,23,42,.08), 0 1px 4px rgba(15,23,42,.04)",
        }}>

          {/* Form title */}
          <div style={{ marginBottom: 28 }}>
            <h2 style={{ fontSize: 22, fontWeight: 800, margin: "0 0 4px", color: "#0f2d5e" }}>
              {tab === "login" ? "Welcome back"
                : regStep === "set-password" ? "Set your password"
                : "Create your account"}
            </h2>
            <p style={{ fontSize: 13.5, color: "#64748b", margin: 0 }}>
              {tab === "login"
                ? "Sign in with your work email and password"
                : regStep === "set-password"
                ? `Enter the code we sent to ${regEmail} and choose a password`
                : "Register as a Member and start contributing"}
            </p>
          </div>

          {/* Pill tab switcher — hidden during set-password step */}
          {selfRegistrationEnabled && regStep === "form" && (
            <div style={{
              display: "flex", background: "#f1f5f9", borderRadius: 10, padding: 4, marginBottom: 28,
            }}>
              {(["login", "register"] as const).map((t) => (
                <div key={t} data-testid={t === "login" ? "tab-login" : "tab-register"}
                  onClick={() => { setTab(t); if (t === "register") resetRegForm(); }}
                  style={{
                    flex: 1, textAlign: "center", padding: "9px 14px", borderRadius: 7,
                    fontSize: 13.5, fontWeight: 600, cursor: "pointer", transition: "all .15s",
                    color: tab === t ? "#0f2d5e" : "#64748b",
                    background: tab === t ? "#fff" : "transparent",
                    boxShadow: tab === t ? "0 1px 4px rgba(15,23,42,.10)" : "none",
                  }}>
                  {t === "login" ? "Sign in" : "Self-Registration"}
                </div>
              ))}
            </div>
          )}

          {/* ── Sign-in form ── */}
          {tab === "login" && (
            <div>
              {!challengeId ? (
                <>
                  <div style={fieldWrapStyle}>
                    <label style={fieldLabelStyle}>Email</label>
                    <div style={iconWrapStyle}>
                      <span style={fieldIconStyle}>✉</span>
                      <input style={authInputStyle} type="email" placeholder="you@company.com"
                             data-testid="login-email" value={loginEmail}
                             onChange={(e) => setLoginEmail(e.target.value)} disabled={loginBusy} />
                    </div>
                  </div>
                  <div style={fieldWrapStyle}>
                    <label style={fieldLabelStyle}>Password</label>
                    <div style={{ position: "relative" }}>
                      <PasswordInput placeholder="Enter your password" dataTestId="login-password"
                                     value={loginPassword} onChange={setLoginPassword} disabled={loginBusy} />
                    </div>
                  </div>
                  <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 18, marginTop: -6 }}>
                    <a href="#" data-testid="forgot-password" style={{ fontSize: 12.5, color: "#1f5fbf", fontWeight: 500 }}
                       onClick={(e) => { e.preventDefault(); openReset(); }}>Forgot password?</a>
                  </div>
                  {loginError && (
                    <p style={{ color: "#b91c1c", fontSize: 13, marginBottom: 12 }}>{loginError}</p>
                  )}
                  <button style={loginBusy || !loginEmail || !loginPassword ? authBtnDisabledStyle : authBtnStyle}
                          data-testid="sign-in" disabled={loginBusy || !loginEmail || !loginPassword}
                          onClick={submitLogin}>
                    {loginBusy ? "Signing in…" : <><span>Sign in</span><span>→</span></>}
                  </button>
                </>
              ) : (
                /* OTP step */
                <>
                  <div style={{
                    background: "var(--info-bg)", border: "1px solid var(--border)",
                    borderLeft: "3px solid var(--primary)", borderRadius: 9, padding: "12px 14px",
                    fontSize: 13, color: "var(--text)", marginBottom: 18, lineHeight: 1.5,
                  }}>
                    🔐 <strong>Security check required.</strong> Enter the 6-digit code sent to your work email to confirm you still have access.
                  </div>
                  <div style={fieldWrapStyle}>
                    <label style={fieldLabelStyle}>One-time code</label>
                    <div style={iconWrapStyle}>
                      <span style={fieldIconStyle}>🔑</span>
                      <input style={authInputStyle} placeholder="6-digit code" data-testid="otp-code"
                             value={otpCode} onChange={(e) => setOtpCode(e.target.value)} />
                    </div>
                  </div>
                  {loginError && (
                    <p style={{ color: "#b91c1c", fontSize: 13, marginBottom: 12 }}>{loginError}</p>
                  )}
                  <button style={loginBusy || !otpCode ? authBtnDisabledStyle : authBtnStyle}
                          data-testid="verify-otp" disabled={loginBusy || !otpCode} onClick={submitOtp}>
                    {loginBusy ? "Verifying…" : <><span>Verify &amp; continue</span><span>→</span></>}
                  </button>
                </>
              )}

              <div style={{
                display: "flex", alignItems: "flex-start", gap: 8, background: "#f8fafc",
                border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px", marginTop: 18,
                fontSize: 12, color: "#64748b", lineHeight: 1.45,
              }} data-testid="lockout-disclaimer">
                <span style={{ fontSize: 15, flexShrink: 0, marginTop: 1 }}>🛡</span>
                For your security, repeated failed sign-in attempts will temporarily lock your account.
              </div>
            </div>
          )}

          {/* ── Self-Registration form ── */}
          {tab === "register" && selfRegistrationEnabled && (
            <div>
              {/* Step 1: identity collection */}
              {regStep === "form" && (
                <>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <div style={fieldWrapStyle}>
                      <label style={fieldLabelStyle}>First name</label>
                      <input style={{ ...authInputStyle, paddingLeft: 12 }} placeholder="Jordan"
                             value={firstName} onChange={(e) => setFirstName(e.target.value)} />
                    </div>
                    <div style={fieldWrapStyle}>
                      <label style={fieldLabelStyle}>Last name</label>
                      <input style={{ ...authInputStyle, paddingLeft: 12 }} placeholder="Lee"
                             value={lastName} onChange={(e) => setLastName(e.target.value)} />
                    </div>
                  </div>
                  <div style={fieldWrapStyle}>
                    <label style={fieldLabelStyle}>Work email</label>
                    <div style={iconWrapStyle}>
                      <span style={fieldIconStyle}>✉</span>
                      <input style={authInputStyle} type="email" placeholder="you@company.com"
                             data-testid="reg-email" value={regEmail}
                             onChange={(e) => setRegEmail(e.target.value)} />
                    </div>
                    <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 5, lineHeight: 1.45 }}>
                      Use the email address your organisation issued you — access depends on continued control of that mailbox.
                    </div>
                  </div>
                  {registerError && (
                    <p style={{ color: "#b91c1c", fontSize: 13, marginBottom: 12 }}>{registerError}</p>
                  )}
                  <button style={registerBusy || !firstName || !lastName || !regEmail ? authBtnDisabledStyle : authBtnStyle}
                          data-testid="create-account"
                          disabled={registerBusy || !firstName || !lastName || !regEmail}
                          onClick={submitRegister}>
                    {registerBusy ? "Creating account…" : <><span>Create account</span><span>→</span></>}
                  </button>
                </>
              )}

              {/* Step 2: enter code + set password */}
              {regStep === "set-password" && (
                <>
                  <div style={{
                    background: "#f0fdf4", border: "1px solid #bbf7d0", borderLeft: "3px solid #16a34a",
                    borderRadius: 9, padding: "10px 14px", fontSize: 13, color: "#14532d",
                    marginBottom: 20, lineHeight: 1.5,
                  }}>
                    ✅ <strong>Account created!</strong> We've sent a verification code to <strong>{regEmail}</strong>. Enter it below along with your new password.
                  </div>
                  <div style={fieldWrapStyle}>
                    <label style={fieldLabelStyle}>Verification code</label>
                    <div style={iconWrapStyle}>
                      <span style={fieldIconStyle}>🔑</span>
                      <input style={authInputStyle} placeholder="Code from email"
                             data-testid="reg-set-code" value={regSetCode}
                             onChange={(e) => setRegSetCode(e.target.value)} />
                    </div>
                  </div>
                  <div style={fieldWrapStyle}>
                    <label style={fieldLabelStyle}>New password</label>
                    <PasswordInput placeholder="Create a password" dataTestId="reg-set-password"
                                   value={regSetPassword} onChange={setRegSetPassword} />
                  </div>
                  <div style={fieldWrapStyle}>
                    <label style={fieldLabelStyle}>Confirm password</label>
                    <PasswordInput placeholder="Re-enter your password" dataTestId="reg-set-confirm"
                                   value={regSetConfirm} onChange={setRegSetConfirm} />
                    {regSetMismatch && (
                      <div style={{ fontSize: 12, color: "#b91c1c", marginTop: 4 }}>Passwords do not match.</div>
                    )}
                  </div>
                  {regSetError && (
                    <p style={{ color: "#b91c1c", fontSize: 13, marginBottom: 12 }}>{regSetError}</p>
                  )}
                  <button style={regSetBusy || !regSetCode || !regSetPassword || !regSetConfirm || regSetMismatch ? authBtnDisabledStyle : authBtnStyle}
                          data-testid="reg-set-submit"
                          disabled={regSetBusy || !regSetCode || !regSetPassword || !regSetConfirm || regSetMismatch}
                          onClick={submitRegSetPassword}>
                    {regSetBusy ? "Setting password…" : <><span>Set password &amp; sign in</span><span>→</span></>}
                  </button>
                  <div style={{ marginTop: 12, textAlign: "center" }}>
                    <a href="#" style={{ fontSize: 12.5, color: "#1f5fbf" }}
                       onClick={(e) => { e.preventDefault(); resendRegCode(); }}>
                      {regSetBusy ? "Sending…" : "Didn't get a code? Send again"}
                    </a>
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── Forgot password panel ── */}
          {resetOpen && (
            <div style={{
              marginTop: 20, background: "#f8fafc", border: "1px solid #e2e8f0",
              borderRadius: 10, padding: "18px 20px",
            }} data-testid="reset-password-panel">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                <strong style={{ fontSize: 14, color: "#0f2d5e" }}>Reset password</strong>
                <a href="#" style={{ fontSize: 12.5, color: "#64748b" }}
                   onClick={(e) => { e.preventDefault(); closeReset(); }}>✕ Close</a>
              </div>

              {resetStep === "request" && (
                <div>
                  <p style={{ fontSize: 13, color: "#64748b", marginBottom: 14, lineHeight: 1.5 }}>
                    Enter your account email. If it exists, you will receive a verification code.
                  </p>
                  <div style={fieldWrapStyle}>
                    <label style={fieldLabelStyle}>Email</label>
                    <div style={iconWrapStyle}>
                      <span style={fieldIconStyle}>✉</span>
                      <input style={authInputStyle} type="email" placeholder="you@company.com"
                             data-testid="reset-email" value={resetEmail}
                             onChange={(e) => setResetEmail(e.target.value)} />
                    </div>
                  </div>
                  {resetError && <p style={{ color: "#b91c1c", fontSize: 13, marginBottom: 12 }}>{resetError}</p>}
                  <button style={resetBusy || !resetEmail ? authBtnDisabledStyle : authBtnStyle}
                          data-testid="send-reset-code" disabled={resetBusy || !resetEmail}
                          onClick={submitResetRequest}>
                    {resetBusy ? "Sending…" : "Send verification code"}
                  </button>
                </div>
              )}

              {resetStep === "confirm" && (
                <div>
                  {resetMessage && (
                    <p style={{ fontSize: 13, color: "#64748b", marginBottom: 14, lineHeight: 1.5 }}>{resetMessage}</p>
                  )}
                  <div style={fieldWrapStyle}>
                    <label style={fieldLabelStyle}>Verification code</label>
                    <div style={iconWrapStyle}>
                      <span style={fieldIconStyle}>🔑</span>
                      <input style={authInputStyle} placeholder="Code from email" data-testid="reset-code"
                             value={resetCode} onChange={(e) => setResetCode(e.target.value)} />
                    </div>
                  </div>
                  <div style={fieldWrapStyle}>
                    <label style={fieldLabelStyle}>New password</label>
                    <PasswordInput placeholder="Create a new password" dataTestId="reset-new-password"
                                   value={resetNewPassword} onChange={setResetNewPassword} />
                  </div>
                  <div style={fieldWrapStyle}>
                    <label style={fieldLabelStyle}>Confirm new password</label>
                    <PasswordInput placeholder="Re-enter your new password" dataTestId="reset-confirm-password"
                                   value={resetConfirmPassword} onChange={setResetConfirmPassword} />
                    {resetPasswordsMismatch && (
                      <div style={{ fontSize: 12, color: "#b91c1c", marginTop: 4 }}>Passwords do not match.</div>
                    )}
                  </div>
                  {resetError && <p style={{ color: "#b91c1c", fontSize: 13, marginBottom: 12 }}>{resetError}</p>}
                  <button style={resetBusy || !resetCode || !resetNewPassword || !resetConfirmPassword || resetPasswordsMismatch ? authBtnDisabledStyle : authBtnStyle}
                          data-testid="confirm-reset"
                          disabled={resetBusy || !resetCode || !resetNewPassword || !resetConfirmPassword || resetPasswordsMismatch}
                          onClick={submitResetConfirm}>
                    {resetBusy ? "Resetting…" : "Reset password"}
                  </button>
                  <div style={{ marginTop: 10, textAlign: "center" }}>
                    <a href="#" style={{ fontSize: 12.5, color: "#1f5fbf" }}
                       onClick={(e) => { e.preventDefault(); resendResetCode(); }}>
                      {resetBusy ? "Sending…" : "Didn't get a code? Send again"}
                    </a>
                  </div>
                </div>
              )}
            </div>
          )}

        </div>
      </div>

      {/* Responsive: hide brand panel on narrow screens */}
      <style>{`
        body { background: #f0f4f8 !important; }
        @media (max-width: 860px) { .auth-brand-panel { display: none !important; } }
      `}</style>
    </div>
  );
}
