import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/apiClient";
import { useDebounced } from "../lib/useDebounced";

// Searchable multi-select of portal people (Members, User Group Leaders,
// Community Leaders) backed by the member directory typeahead
// (GET /members?q=&limit=10). Selected people render as removable chips.
//
// Non-Member picks are annotated "no points" at SELECTION time — BR-P3 says
// only Members earn, and the old UI left a leader to discover that after the
// event (mockup gap G9). With `allowExternal`, a free-text entry adds an
// external presenter chip, which never earns points.

export interface PickedPerson {
  id: string;
  name: string;
  role: string;
  /** Groups the person belongs to, carried straight from the directory row.
   *  Optional — existing callers ignore it. Used by the Adjust Points screen so
   *  it can offer the member's own groups without a second request (and without
   *  GET /members/{id}, which triggers a 4-way cross-service fan-out). */
  groupIds?: string[];
}

interface DirectoryHit {
  id: string;
  firstName?: string;
  lastName?: string;
  email?: string;
  role?: string;
  memberGroupIds?: string[];
}

export default function PeoplePicker(props: {
  label: string;
  testId: string;
  selected: PickedPerson[];
  onChange: (next: PickedPerson[]) => void;
  hint?: string;
  allowExternal?: boolean;
  externals?: string[];
  onExternalsChange?: (next: string[]) => void;
  // Scope the typeahead to one group's roster (GET /members?groupId=). Used by
  // the UGL revoke flow so a leader only searches members of the group they lead.
  groupId?: string;
}) {
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const [hits, setHits] = useState<DirectoryHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [extName, setExtName] = useState("");
  const q = useDebounced(term, 300);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    let cancelled = false;
    setSearching(true);
    const scope = props.groupId ? `&groupId=${encodeURIComponent(props.groupId)}` : "";
    apiFetch<{ items: DirectoryHit[] }>(`/members?q=${encodeURIComponent(q.trim())}&limit=10${scope}`)
      .then((res) => { if (!cancelled) { setHits(res.items ?? []); setOpen(true); } })
      .catch(() => { if (!cancelled) setHits([]); })
      .finally(() => { if (!cancelled) setSearching(false); });
    return () => { cancelled = true; };
  }, [q, props.groupId]);

  // Close the dropdown on an outside click.
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const add = (hit: DirectoryHit) => {
    if (props.selected.some((p) => p.id === hit.id)) return;
    const name = [hit.firstName, hit.lastName].filter(Boolean).join(" ") || hit.email || hit.id;
    props.onChange([...props.selected, {
      id: hit.id, name, role: hit.role ?? "Member", groupIds: hit.memberGroupIds ?? [],
    }]);
    setTerm("");
    setHits([]);
    setOpen(false);
  };

  const remove = (id: string) =>
    props.onChange(props.selected.filter((p) => p.id !== id));

  const addExternal = () => {
    const name = extName.trim();
    if (!name || !props.onExternalsChange) return;
    const list = props.externals ?? [];
    if (!list.includes(name)) props.onExternalsChange([...list, name]);
    setExtName("");
  };

  const removeExternal = (name: string) =>
    props.onExternalsChange?.((props.externals ?? []).filter((n) => n !== name));

  const inputId = `${props.testId}-input`;

  return (
    <div className="field" ref={boxRef} style={{ position: "relative" }}>
      <label htmlFor={inputId}>{props.label}</label>

      {(props.selected.length > 0 || (props.externals ?? []).length > 0) && (
        <div className="flex" style={{ gap: 6, flexWrap: "wrap", marginBottom: 6 }}
             data-testid={`${props.testId}-chips`}>
          {props.selected.map((p) => (
            <span key={p.id} className="badge blue" data-testid={`${props.testId}-chip-${p.id}`}>
              {p.name}
              {p.role !== "Member" && <span className="faint"> · no points ({p.role})</span>}
              <button type="button" className="icon-btn" aria-label={`Remove ${p.name}`}
                      style={{ marginLeft: 4 }} onClick={() => remove(p.id)}>✕</button>
            </span>
          ))}
          {(props.externals ?? []).map((name) => (
            <span key={name} className="badge amber" data-testid={`${props.testId}-ext-${name}`}>
              {name}<span className="faint"> · External — no points</span>
              <button type="button" className="icon-btn" aria-label={`Remove ${name}`}
                      style={{ marginLeft: 4 }} onClick={() => removeExternal(name)}>✕</button>
            </span>
          ))}
        </div>
      )}

      <input id={inputId} className="input" data-testid={props.testId}
             placeholder="🔍 Type a name or email…" value={term} autoComplete="off"
             role="combobox" aria-expanded={open} aria-controls={`${props.testId}-list`}
             onFocus={() => hits.length > 0 && setOpen(true)}
             onChange={(e) => setTerm(e.target.value)} />

      {open && (hits.length > 0 || searching) && (
        <div id={`${props.testId}-list`} role="listbox" className="card"
             data-testid={`${props.testId}-results`}
             style={{ position: "absolute", zIndex: 20, left: 0, right: 0, marginTop: 4,
                      maxHeight: 220, overflowY: "auto", padding: 4 }}>
          {searching && <div className="faint small" style={{ padding: 8 }}>Searching…</div>}
          {hits.map((h) => {
            const name = [h.firstName, h.lastName].filter(Boolean).join(" ") || h.email || h.id;
            const picked = props.selected.some((p) => p.id === h.id);
            return (
              <button key={h.id} type="button" role="option" aria-selected={picked}
                      className="btn sm" data-testid={`${props.testId}-hit-${h.id}`}
                      disabled={picked} onClick={() => add(h)}
                      style={{ display: "flex", width: "100%", justifyContent: "space-between",
                               marginBottom: 2 }}>
                <span>{name}</span>
                <span className="faint small">{h.role ?? "Member"}{picked ? " · added" : ""}</span>
              </button>
            );
          })}
          {!searching && hits.length === 0 && (
            <div className="faint small" style={{ padding: 8 }}>No matches.</div>
          )}
        </div>
      )}

      {props.allowExternal && (
        <div className="flex mt-8" style={{ gap: 8 }}>
          <input className="input" data-testid={`${props.testId}-external`}
                 placeholder="External presenter name…" value={extName}
                 aria-label="External presenter name"
                 onChange={(e) => setExtName(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addExternal(); } }} />
          <button type="button" className="btn sm" data-testid={`${props.testId}-external-add`}
                  onClick={addExternal}>＋ Add external</button>
        </div>
      )}

      {props.hint && <div className="hint">{props.hint}</div>}
    </div>
  );
}
