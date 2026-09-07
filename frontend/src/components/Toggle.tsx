// On/off switch styled by .toggle/.toggle.on (portal.css). Implemented as a
// native <button role="switch"> — a single, unambiguous event path (the previous
// hidden-checkbox-inside-label version had two competing handlers via the
// label's native click forwarding and did not toggle reliably in the browser).
// Native button = keyboard accessible (Space/Enter) for free.
// `labelHidden` keeps the label as the switch's accessible name without
// rendering it as visible text (for rows that already show the name elsewhere).
export default function Toggle({
  checked, onChange, label, testId, disabled, labelHidden,
}: { checked: boolean; onChange: (v: boolean) => void; label?: string; testId?: string; disabled?: boolean; labelHidden?: boolean }) {
  const btn = (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      data-testid={testId}
      disabled={disabled}
      className={"toggle" + (checked ? " on" : "")}
      onClick={() => { if (!disabled) onChange(!checked); }}
      style={{ border: "none", padding: 0, flexShrink: 0, ...(disabled ? { opacity: 0.5, cursor: "not-allowed" } : {}) }}
    />
  );
  if (!label || labelHidden) return btn;
  return (
    <span className="flex" style={{ gap: 10 }}>
      <span>{label}</span>
      {btn}
    </span>
  );
}
