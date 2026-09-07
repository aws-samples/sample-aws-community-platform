import { useEffect, useRef, useState } from "react";

// A compact multi-select dropdown with checkboxes. Replaces the ugly native
// <select multiple> — looks like a regular dropdown but opens a checkbox list
// in a popover. Shows selected count or "All" as the trigger label.
export interface MultiSelectOption {
  value: string;
  label: string;
}

export default function MultiSelect({ options, selected, onChange, label, testId, allLabel = "All" }: {
  options: readonly MultiSelectOption[];
  selected: string[];
  onChange: (next: string[]) => void;
  label?: string;
  testId?: string;
  allLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const allSelected = selected.length === 0 || selected.length === options.length;
  const triggerLabel = allSelected
    ? allLabel
    : selected.length === 1
      ? options.find((o) => o.value === selected[0])?.label ?? selected[0]
      : `${selected.length} selected`;

  const toggle = (value: string) => {
    const next = selected.includes(value)
      ? selected.filter((v) => v !== value)
      : [...selected, value];
    // If all are now selected (or none left unchecked), reset to "all" (empty = all).
    onChange(next.length === options.length ? options.map((o) => o.value) : next);
  };

  const selectAll = () => onChange(options.map((o) => o.value));
  const clearAll = () => onChange([]);

  return (
    <div className="field" style={{ margin: 0, position: "relative" }} ref={ref}>
      {label && <label>{label}</label>}
      <button type="button" className="select" data-testid={testId}
              onClick={() => setOpen((o) => !o)}
              style={{ textAlign: "left", cursor: "pointer", display: "flex",
                       justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {triggerLabel}
        </span>
        <span style={{ marginLeft: 8, fontSize: 10, opacity: 0.6 }}>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="card" style={{
          position: "absolute", top: "100%", left: 0, zIndex: 120, minWidth: "100%",
          maxHeight: 220, overflowY: "auto", padding: "6px 0", marginTop: 2,
          boxShadow: "0 4px 16px rgba(0,0,0,.12)", border: "1px solid var(--border)",
        }}>
          <div style={{ display: "flex", gap: 8, padding: "2px 10px 6px", borderBottom: "1px solid var(--border)" }}>
            <button type="button" className="small" style={{ color: "var(--primary)", cursor: "pointer", background: "none", border: "none", padding: 0 }}
                    onClick={selectAll}>All</button>
            <button type="button" className="small" style={{ color: "var(--danger)", cursor: "pointer", background: "none", border: "none", padding: 0 }}
                    onClick={clearAll}>None</button>
          </div>
          {options.map((o) => (
            <label key={o.value} style={{ display: "flex", alignItems: "center", gap: 8,
                                          padding: "5px 10px", cursor: "pointer", fontSize: 13 }}
                   data-testid={testId ? `${testId}-${o.value}` : undefined}>
              <input type="checkbox" checked={selected.includes(o.value)}
                     onChange={() => toggle(o.value)} />
              {o.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
