import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/apiClient";
import Toggle from "../components/Toggle";
import PeoplePicker, { type PickedPerson } from "../components/PeoplePicker";
import type { Role } from "../roles";

// Create / edit event modal (US-2.1/2.2/2.4/2.18).
// Replaces the generic FormModal because the mockup's form is genuinely
// role-shaped: Scope is a select for a Community Leader and a readonly field
// for a User Group Leader. An event owns a time span — a Start and an End —
// which covers both a one-hour webinar and a multi-day hackathon.
export const EVENT_TYPES = [
  "Meetup", "Workshop", "Hackathon", "Webinar",
  "AMA / Fireside Chat", "Conference", "Presentation", "Social",
];
export const DELIVERY_MODES = ["Virtual", "In-Person", "Hybrid"];
const MAX_EVENT_SPAN_DAYS = 30;

export interface EventFormValues {
  id?: string;
  title?: string;
  description?: string;
  type?: string;
  deliveryMode?: string;
  groupId?: string | null;
  startsAt?: string;
  endsAt?: string;
  location?: string;
  announceOnCreate?: boolean;
  announceByEmail?: boolean;
}

interface GroupOption { id: string; name: string }

function toLocalInput(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function EventModal(props: {
  mode: "create" | "edit";
  role: Role;
  ledGroupId?: string | null;
  groups: GroupOption[];
  initial?: EventFormValues;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isUgl = props.role === "UserGroupLeader";

  const [values, setValues] = useState<EventFormValues>({
    type: EVENT_TYPES[1],
    deliveryMode: DELIVERY_MODES[0],
    groupId: isUgl ? props.ledGroupId ?? null : null,
    ...props.initial,
  });
  const [presenters, setPresenters] = useState<PickedPerson[]>([]);
  const [organizers, setOrganizers] = useState<PickedPerson[]>([]);
  const [externals, setExternals] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // This form is taller than the modal, so the card itself scrolls and the
  // Submit button sits far below the error banner. Without scrolling the banner
  // into view a failed validation is invisible from the button — which reads as
  // "the Save button does nothing".
  const errorRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (error) errorRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [error]);

  // Edit mode: prefill the pickers from the event's current designations so
  // saving cannot silently wipe them (a replace-style PUT with empty lists
  // would do exactly that).
  useEffect(() => {
    if (props.mode !== "edit" || !props.initial?.id) return;
    let cancelled = false;
    apiFetch<{ items: any[] }>(`/events/${props.initial.id}/designations`)
      .then((res) => {
        if (cancelled) return;
        const rows = res.items ?? [];
        const toPerson = (d: any): PickedPerson => (
          { id: d.userId, name: d.displayName ?? d.userId, role: d.roleAtDesignation ?? "Member" });
        setPresenters(rows.filter((d) => d.kind === "presenter" && !d.external).map(toPerson));
        setOrganizers(rows.filter((d) => d.kind === "organizer").map(toPerson));
        setExternals(rows.filter((d) => d.kind === "presenter" && d.external)
          .map((d) => d.displayName));
      })
      .catch(() => { /* designations stay empty; the manage screen still shows them */ });
    return () => { cancelled = true; };
  }, [props.mode, props.initial?.id]);

  const set = (patch: Partial<EventFormValues>) => setValues((v) => ({ ...v, [Object.keys(patch)[0]]: Object.values(patch)[0] }));

  const virtual = values.deliveryMode === "Virtual" || values.deliveryMode === "Hybrid";

  const validate = (): string | null => {
    if (!values.title?.trim()) return "Title is required.";
    if (!values.type) return "Event type is required.";
    if (!values.deliveryMode) return "Delivery mode is required.";
    // Free text: a join link, an address, or a room name (a Virtual/Hybrid event
    // may legitimately name a physical room). Only an explicit http:// link is
    // refused, so a private event's join link never travels in cleartext (BR-V3).
    if (!values.location?.trim()) return "A location or join link is required.";
    if (values.location.trim().toLowerCase().startsWith("http://")) {
      return "A join link must use https://. Free text (for example a room name) is also fine.";
    }
    if (!values.startsAt) return "Start date & time is required.";
    if (!values.endsAt) return "End date & time is required.";
    const start = new Date(values.startsAt);
    const end = new Date(values.endsAt);
    if (Number.isNaN(start.getTime())) return "Start date & time is invalid.";
    if (Number.isNaN(end.getTime())) return "End date & time is invalid.";
    if (end <= start) return "End must be after the start.";
    if (end.getTime() - start.getTime() > MAX_EVENT_SPAN_DAYS * 86400000) {
      return `An event cannot span more than ${MAX_EVENT_SPAN_DAYS} days.`;
    }
    if (!isUgl && props.mode === "create" && values.groupId === undefined) {
      return "Scope is required.";
    }
    if (isUgl && props.mode === "create" && !values.groupId) {
      // A UGL always has a led group; missing here means a stale session.
      // Submitting anyway would only produce the backend's 403 — and BR-A3
      // deliberately treats a UGL's null scope as an attempted community-wide
      // create, so it must NOT be silently coerced into their own group.
      return "Your led group could not be determined. Please sign out and back in.";
    }
    return null;
  };

  const submit = async () => {
    const problem = validate();
    if (problem) { setError(problem); return; }
    setSaving(true);
    setError(null);
    const designations = {
      presenters: presenters.map((p) => p.id),
      organizers: organizers.map((p) => p.id),
      externalPresenters: externals,
    };
    const base = {
      title: values.title, description: values.description ?? "",
      type: values.type, deliveryMode: values.deliveryMode,
      groupId: values.groupId ?? null, location: values.location,
      startsAt: new Date(values.startsAt!).toISOString(),
      endsAt: new Date(values.endsAt!).toISOString(),
      announceOnCreate: Boolean(values.announceOnCreate),
      announceByEmail: Boolean(values.announceByEmail),
      ...designations,
    };
    try {
      if (props.mode === "edit" && values.id) {
        await apiFetch(`/events/${values.id}`, {
          method: "PUT",
          body: JSON.stringify(base),
        });
        // The event PUT ignores designation fields by design; they are replaced
        // through their own endpoint (same payload the Manage screen uses).
        await apiFetch(`/events/${values.id}/designations`, {
          method: "PUT",
          body: JSON.stringify(designations),
        });
      } else {
        await apiFetch("/events", {
          method: "POST",
          body: JSON.stringify(base),
        });
      }
      props.onSaved();
      props.onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const title = props.mode === "create"
    ? (isUgl ? "Create Event — your group" : "Create Event")
    : (isUgl ? "Edit Event — your group" : "Edit Event");

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={title}
         style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  overflow: "auto", padding: "30px 0" }}>
      <div className="card" style={{ width: 620, maxWidth: "94vw", maxHeight: "90vh", overflowY: "auto" }}>
        <div className="card-head"><h3>{title}</h3>
          <button className="icon-btn" data-testid="event-modal-close" aria-label="Close"
                  onClick={props.onClose}>✕</button></div>

        {error && <div className="banner error" ref={errorRef} data-testid="event-modal-error" role="alert">{error}</div>}

        <div className="field"><label htmlFor="ev-title">Title <span style={{ color: "var(--danger)" }}>*</span></label>
          <input id="ev-title" className="input" data-testid="event-title"
                 placeholder="e.g. Serverless Deep Dive" value={values.title ?? ""}
                 onChange={(e) => set({ title: e.target.value })} /></div>

        <div className="field"><label htmlFor="ev-desc">Description</label>
          <textarea id="ev-desc" className="textarea" data-testid="event-description"
                    value={values.description ?? ""}
                    onChange={(e) => set({ description: e.target.value })} /></div>

        <div className="form-row">
          <div className="field"><label htmlFor="ev-type">Event type</label>
            <select id="ev-type" className="select" data-testid="event-type" value={values.type}
                    onChange={(e) => set({ type: e.target.value })}>
              {EVENT_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select></div>
          <div className="field"><label htmlFor="ev-mode">Delivery mode</label>
            <select id="ev-mode" className="select" data-testid="event-mode" value={values.deliveryMode}
                    onChange={(e) => set({ deliveryMode: e.target.value })}>
              {DELIVERY_MODES.map((m) => <option key={m}>{m}</option>)}
            </select></div>
        </div>

        <div className="form-row">
          <div className="field"><label htmlFor="ev-starts">Start date &amp; time <span style={{ color: "var(--danger)" }}>*</span></label>
            <input id="ev-starts" className="input" type="datetime-local" data-testid="event-startsat"
                   value={toLocalInput(values.startsAt)}
                   onChange={(e) => set({ startsAt: e.target.value })} /></div>
          <div className="field"><label htmlFor="ev-ends">End date &amp; time <span style={{ color: "var(--danger)" }}>*</span></label>
            <input id="ev-ends" className="input" type="datetime-local" data-testid="event-endsat"
                   value={toLocalInput(values.endsAt)}
                   onChange={(e) => set({ endsAt: e.target.value })} /></div>
        </div>
        <div className="hint" style={{ marginTop: -6, marginBottom: 12 }}>
          For a single session, set the end a short while after the start. For a multi-day event
          (e.g. a hackathon), pick the closing date &amp; time — up to {MAX_EVENT_SPAN_DAYS} days.
        </div>

        <div className="field"><label htmlFor="ev-location">Location / virtual link <span style={{ color: "var(--danger)" }}>*</span></label>
          <input id="ev-location" className="input" data-testid="event-location"
                 placeholder={virtual ? "https://meeting-url — or a room name" : "Address or room name"}
                 value={values.location ?? ""}
                 onChange={(e) => set({ location: e.target.value })} />
          <div className="hint">Free text — a join link, an address, or a meeting room name.
            Links must use https://.</div></div>

        <div className="field"><label htmlFor="ev-scope">Scope</label>
          {isUgl ? (
            <>
              <input id="ev-scope" className="input" data-testid="event-scope-readonly" readOnly
                     value={`${props.groups.find((g) => g.id === props.ledGroupId)?.name ?? "Your group"} (your group)`} />
              <div className="hint">User Group Leaders can create events only for the group they lead.</div>
            </>
          ) : (
            <select id="ev-scope" className="select" data-testid="event-scope"
                    value={values.groupId ?? ""}
                    onChange={(e) => set({ groupId: e.target.value || null })}>
              <option value="">Community-wide (all groups)</option>
              {props.groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          )}
        </div>

        <PeoplePicker label="Presenters / facilitators" testId="event-presenters"
                      selected={presenters} onChange={setPresenters}
                      allowExternal externals={externals} onExternalsChange={setExternals}
                      hint="Search members and leaders, or add an external presenter by name.
                            Presenters earn delivery points on completion — but only designees
                            who hold the Member role. Leaders and external presenters do not earn." />
        <PeoplePicker label="Organizers" testId="event-organizers"
                      selected={organizers} onChange={setOrganizers}
                      hint="Organizers earn organize points on completion, same eligibility rule." />

        <div className="field"><label>Also post an announcement</label>
          <div className="flex" style={{ gap: 8, alignItems: "center" }}>
            <Toggle checked={Boolean(values.announceOnCreate)} testId="event-announce"
                    label="Also post an announcement" labelHidden
                    onChange={(on) => set({ announceOnCreate: on })} />
            <span className="muted small">Broadcasts this event to its audience via the announcement panel</span>
          </div>
          <div className="flex mt-8" style={{ gap: 8, alignItems: "center" }}>
            <Toggle checked={Boolean(values.announceByEmail)} testId="event-announce-email"
                    label="Send the announcement by email" labelHidden
                    onChange={(on) => set({ announceByEmail: on })} />
            <span className="muted small">…and also send it as an email</span>
          </div></div>

        <div className="btn-row">
          <button className="btn primary" data-testid="event-submit" disabled={saving} onClick={submit}>
            {saving ? "Saving…" : props.mode === "create" ? "Publish Event" : "Save Changes"}
          </button>
          <button className="btn" data-testid="event-cancel" onClick={props.onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
