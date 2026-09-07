import { useEffect, useRef, useState } from "react";
import Toggle from "./Toggle";

// Column settings popover for DataTable (US-8.9 preference UI, redesigned).
// Standard interactions: drag a row by its handle to reorder, flip a switch to
// show/hide. Keyboard equivalent for reorder is ArrowUp/ArrowDown on the handle,
// so the panel is usable without a pointer.
export interface ColumnSettingsItem {
  key: string;
  label: string;
}

export default function ColumnSettings(props: {
  tableId: string;
  items: ColumnSettingsItem[]; // in current display order
  hidden: string[];
  onReorder: (orderedKeys: string[]) => void;
  onToggle: (key: string) => void;
  onReset: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [dragKey, setDragKey] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close on outside click / Escape — expected popover behaviour.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const keys = props.items.map((i) => i.key);
  const visibleCount = keys.filter((k) => !props.hidden.includes(k)).length;

  const moveTo = (from: string, to: string) => {
    if (from === to) return;
    const order = [...keys];
    const i = order.indexOf(from);
    const j = order.indexOf(to);
    if (i < 0 || j < 0) return;
    order.splice(i, 1);
    order.splice(j, 0, from);
    props.onReorder(order);
  };

  const nudge = (key: string, dir: -1 | 1) => {
    const i = keys.indexOf(key);
    const j = i + dir;
    if (j < 0 || j >= keys.length) return;
    moveTo(key, keys[j]);
  };

  return (
    <div className={"colset" + (open ? " open" : "")} ref={wrapRef}>
      <button
        className={"icon-btn" + (open ? " active" : "")}
        title="Column settings"
        aria-label="Column settings"
        aria-expanded={open}
        aria-haspopup="dialog"
        data-testid={`${props.tableId}-cols`}
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path fill="currentColor" d="M2 2h3v12H2V2zm4.5 0h3v12h-3V2zM11 2h3v12h-3V2z" opacity=".35" />
          <path fill="currentColor" d="M2 2h3v12H2V2zm4.5 0h3v8h-3V2z" />
        </svg>
      </button>

      {open && (
        <div className="colset-panel" role="dialog" aria-label="Column settings" data-testid={`${props.tableId}-cols-panel`}>
          <div className="cs-head">
            <b>Columns</b>
            <span className="cs-sub">Drag to reorder · switch to show or hide</span>
          </div>

          <ul className="cs-list">
            {props.items.map((item) => {
              const shown = !props.hidden.includes(item.key);
              const lastOne = shown && visibleCount === 1;
              return (
                <li
                  key={item.key}
                  className={"cs-item" + (dragKey === item.key ? " dragging" : "") + (shown ? "" : " off")}
                  draggable
                  onDragStart={(e) => { setDragKey(item.key); e.dataTransfer.effectAllowed = "move"; }}
                  onDragOver={(e) => { e.preventDefault(); if (dragKey) moveTo(dragKey, item.key); }}
                  onDragEnd={() => setDragKey(null)}
                  onDrop={(e) => { e.preventDefault(); setDragKey(null); }}
                  data-testid={`${props.tableId}-cols-item-${item.key}`}
                >
                  <button
                    type="button"
                    className="cs-grip"
                    aria-label={`Reorder ${item.label}. Use arrow up and arrow down keys.`}
                    onKeyDown={(e) => {
                      if (e.key === "ArrowUp") { e.preventDefault(); nudge(item.key, -1); }
                      if (e.key === "ArrowDown") { e.preventDefault(); nudge(item.key, 1); }
                    }}
                  >
                    <svg width="10" height="16" viewBox="0 0 10 16" aria-hidden="true" focusable="false">
                      <circle cx="3" cy="4" r="1.35" fill="currentColor" />
                      <circle cx="7" cy="4" r="1.35" fill="currentColor" />
                      <circle cx="3" cy="8" r="1.35" fill="currentColor" />
                      <circle cx="7" cy="8" r="1.35" fill="currentColor" />
                      <circle cx="3" cy="12" r="1.35" fill="currentColor" />
                      <circle cx="7" cy="12" r="1.35" fill="currentColor" />
                    </svg>
                  </button>
                  <span className="cs-name">{item.label}</span>
                  <Toggle
                    checked={shown}
                    disabled={lastOne}
                    label={`Show ${item.label}`}
                    labelHidden
                    testId={`${props.tableId}-cols-toggle-${item.key}`}
                    onChange={() => props.onToggle(item.key)}
                  />
                </li>
              );
            })}
          </ul>

          <div className="cs-foot">
            <span className="cs-count">{visibleCount} of {keys.length} shown</span>
            <button className="cs-link" data-testid={`${props.tableId}-cols-reset`} onClick={props.onReset}>Reset</button>
          </div>
        </div>
      )}
    </div>
  );
}
