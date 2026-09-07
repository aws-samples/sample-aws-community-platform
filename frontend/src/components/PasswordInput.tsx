import { useId, useState } from "react";

// Reusable password field with a show/hide toggle icon (accessible button,
// keyboard-focusable, not part of tab order for the icon itself so Enter/Tab
// flow through the form naturally). Used on the Login screen for every
// password field (sign in, self-registration, forgot-password reset).
interface PasswordInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  dataTestId?: string;
}

export default function PasswordInput({ value, onChange, placeholder, disabled, dataTestId }: PasswordInputProps) {
  const [visible, setVisible] = useState(false);
  const inputId = useId();

  return (
    <div style={{ position: "relative" }}>
      <input
        id={inputId}
        style={{
          width: "100%", padding: "11px 38px 11px 12px", border: "1.5px solid #e2e8f0",
          borderRadius: 9, fontSize: 14, fontFamily: "inherit", color: "#1e293b",
          background: "#fff", boxSizing: "border-box",
        }}
        type={visible ? "text" : "password"}
        placeholder={placeholder}
        value={value}
        disabled={disabled}
        data-testid={dataTestId}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
      />
      <button
        type="button"
        aria-label={visible ? "Hide password" : "Show password"}
        aria-controls={inputId}
        aria-pressed={visible}
        title={visible ? "Hide password" : "Show password"}
        tabIndex={-1}
        onClick={() => setVisible((v) => !v)}
        style={{
          position: "absolute", right: 4, top: "50%", transform: "translateY(-50%)",
          width: 28, height: 28, border: "none", background: "transparent",
          cursor: "pointer", display: "grid", placeItems: "center", color: "var(--text-muted)",
          padding: 0,
        }}
      >
        {visible ? (
          // eye-off
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a18.5 18.5 0 0 1 5.06-5.94M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
            <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
            <line x1="1" y1="1" x2="23" y2="23" />
          </svg>
        ) : (
          // eye
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        )}
      </button>
    </div>
  );
}
