import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import { IdeaCardSkeleton, LoadingMoreRow } from "../components/States";
import { voteCountPhrase } from "./eventIdeas";
import { groupFilterOptions } from "../lib/groupScope";
import type { Role } from "../roles";

// Event Ideas tab (US-14) — member feed + submit, leader backlog with greenlight/decline.
// Infinite scroll: ideas accumulate as the user scrolls; each tab/filter change
// resets the list and fetches from page 1.

const FORMAT_OPTIONS = ["Any format", "Workshop (hands-on)", "Presentation / Talk",
  "Meetup", "Webinar", "Hackathon", "AMA / Fireside Chat"];
const TIME_OPTIONS = ["No preference", "Weekday morning", "Weekday evening", "Weekend"];
const DELIVERY_OPTIONS = ["No preference", "Virtual", "In-Person", "Hybrid"];
// No Declined entry: declining an idea deletes it, so no row can carry that
// status. Archived is still reachable via the nightly sweep but is not offered
// as a tab.
const STATUS_COLORS: Record<string, string> = {
  Open: "var(--success)", Greenlit: "var(--primary)", Archived: "var(--text-faint)"
};

const PAGE_SIZE_MEMBER = 20;
const PAGE_SIZE_LEADER = 25;

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diff / 86400000);
  if (days < 1) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

function IdeaCard({ idea, onVote, onGreenlight, onDecline, isLeader }: {
  idea: any; onVote: (id: string) => void;
  onGreenlight?: (id: string) => void;
  onDecline?: (id: string) => void;
  isLeader?: boolean;
}) {
  const canVote = idea.status === "Open";
  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: "var(--radius, 6px)", padding: "14px 16px",
      display: "flex", gap: 14, alignItems: "flex-start",
    }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, minWidth: 52 }}>
        <button
          disabled={!canVote}
          onClick={() => onVote(idea.id)}
          style={{
            width: 38, height: 38, borderRadius: 8, border: "2px solid var(--border)",
            background: "var(--surface-2)", cursor: canVote ? "pointer" : "default",
            fontSize: 18, display: "flex", alignItems: "center", justifyContent: "center",
            opacity: canVote ? 1 : 0.4,
          }}
          title={canVote ? "Vote for this idea" : "Voting closed"}
        >👍</button>
        <span style={{ fontSize: 16, fontWeight: 700 }}>{idea.voteCount ?? 0}</span>
        <span style={{ fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: ".4px" }}>votes</span>
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, marginBottom: 4 }}>
          <b style={{ fontSize: 14 }}>{idea.title}</b>
          <span style={{ fontSize: 11, fontWeight: 600, color: STATUS_COLORS[idea.status] || "var(--text-muted)", whiteSpace: "nowrap" }}>
            {idea.status === "Open" ? "● Open" : idea.status === "Greenlit" ? "✅ Greenlit" : "Archived"}
          </span>
        </div>
        {idea.description && <p style={{ fontSize: 13, color: "var(--text-muted)", margin: "0 0 8px", lineHeight: 1.5 }}>{idea.description}</p>}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center", fontSize: 12, color: "var(--text-faint)" }}>
          {idea.format && idea.format !== "Any format" && (
            <span style={{ background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: 4, padding: "1px 6px", fontSize: 11 }}>{idea.format}</span>
          )}
          {idea.deliveryMode && idea.deliveryMode !== "No preference" && (
            <span style={{ background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: 4, padding: "1px 6px", fontSize: 11 }}>{idea.deliveryMode}</span>
          )}
          {idea.timePreference && idea.timePreference !== "No preference" && (
            <span style={{ background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: 4, padding: "1px 6px", fontSize: 11 }}>{idea.timePreference}</span>
          )}
          <span>by <b>{idea.submitterName}</b> · {timeAgo(idea.createdAt)}</span>
        </div>
      </div>

      {isLeader && idea.status === "Open" && onGreenlight && onDecline && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, flexShrink: 0 }}>
          <button className="btn sm primary" onClick={() => onGreenlight(idea.id)}>✅ Greenlight</button>
          <button className="btn sm" onClick={() => onDecline(idea.id)}>✕ Decline</button>
        </div>
      )}
    </div>
  );
}

// ── Shared infinite-scroll hook ──────────────────────────────────────────────

function useInfiniteIdeas(endpoint: string, pageSize: number) {
  const [ideas, setIdeas] = useState<any[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loadingInitial, setLoadingInitial] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [stale, setStale] = useState(false); // dims list while filter-reset fetch runs
  // Surfaced, not swallowed. This catch used to be empty, so a 403 from asking
  // for an out-of-scope group, a network failure and a genuinely empty partition
  // all rendered identically as "No ideas here yet." That is precisely why the
  // feed reading the wrong index partition went unnoticed: it looked like there
  // was simply nothing there.
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchPage = useCallback(async (url: string, append: boolean) => {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();
    try {
      const res = await apiFetch<{ items: any[]; cursor?: string }>(url);
      setIdeas((prev) => append ? [...prev, ...res.items] : res.items);
      setCursor(res.cursor ?? null);
      setHasMore(Boolean(res.cursor));
      setError(null);
    } catch (e) {
      // Keep the existing list (still fail-soft) but say what went wrong.
      setError((e as Error).message || "Could not load ideas.");
      setHasMore(false);
    } finally {
      setLoadingInitial(false);
      setLoadingMore(false);
      setStale(false);
    }
  }, []);

  // Reset + initial fetch whenever endpoint changes (filter/tab change)
  useEffect(() => {
    setLoadingInitial(true);
    setStale(false);
    setCursor(null);
    setHasMore(true);
    const params = new URLSearchParams(endpoint.includes("?") ? endpoint.split("?")[1] : "");
    params.set("limit", String(pageSize));
    const base = endpoint.split("?")[0];
    fetchPage(`${base}?${params.toString()}`, false);
  }, [endpoint, pageSize, fetchPage]);

  const loadMore = useCallback(() => {
    if (!hasMore || loadingMore || loadingInitial) return;
    setLoadingMore(true);
    const params = new URLSearchParams(endpoint.includes("?") ? endpoint.split("?")[1] : "");
    params.set("limit", String(pageSize));
    if (cursor) params.set("cursor", cursor);
    const base = endpoint.split("?")[0];
    fetchPage(`${base}?${params.toString()}`, true);
  }, [hasMore, loadingMore, loadingInitial, endpoint, pageSize, cursor, fetchPage]);

  // Soft-reset: dim existing ideas, re-fetch page 1 (used after mutations like vote/submit).
  // loadingInitial=true gates the ScrollSentinel so it can't fire loadMore() during the fetch.
  const refresh = useCallback(() => {
    setStale(true);
    setLoadingInitial(true);
    setCursor(null);
    setHasMore(true);
    const params = new URLSearchParams(endpoint.includes("?") ? endpoint.split("?")[1] : "");
    params.set("limit", String(pageSize));
    const base = endpoint.split("?")[0];
    fetchPage(`${base}?${params.toString()}`, false);
  }, [endpoint, pageSize, fetchPage]);

  return { ideas, loadingInitial, loadingMore, hasMore, stale, error, loadMore, refresh };
}

// ── Scroll sentinel ──────────────────────────────────────────────────────────

function ScrollSentinel({ onVisible }: { onVisible: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) onVisible();
    }, { rootMargin: "200px" });
    obs.observe(el);
    return () => obs.disconnect();
  }, [onVisible]);
  return <div ref={ref} style={{ height: 1 }} />;
}

// ── Member view ──────────────────────────────────────────────────────────────

function MemberIdeasView({ groups }: { groups: any[] }) {
  // The member's OWN groups — the only ones they may browse or submit into.
  // Derived once so the filter selector and the submit selector cannot drift
  // apart again (they previously used different lists). Same helper the Member
  // Directory's group filter uses.
  const myGroups = groupFilterOptions(groups, "Member");
  const [filter, setFilter] = useState("Open");
  // "" = every scope the caller can see (community-wide + their own groups).
  // This is the DEFAULT because a member's own groups' ideas are the point of
  // the feed; it previously defaulted to "COMMUNITY", which is why a member saw
  // none of them without hunting through the dropdown one group at a time.
  const [groupFilter, setGroupFilter] = useState("");
  const [showForm, setShowForm] = useState(true);  // expanded by default
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({ title: "", description: "", format: "", timePreference: "", deliveryMode: "", groupId: "COMMUNITY" });
  const [formError, setFormError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  // Pre-fill the submit form's group when the reader narrows to a specific one —
  // a convenience only. `form.groupId` is what actually gets submitted (see
  // handleSubmit), so what the form shows is always what gets sent. "All my
  // groups" ("") is not a submittable target and is deliberately not copied
  // across: an idea has to belong to exactly one scope.
  useEffect(() => {
    if (groupFilter) setForm((prev) => ({ ...prev, groupId: groupFilter }));
  }, [groupFilter]);

  const params = new URLSearchParams();
  if (filter !== "All") params.set("status", filter);
  // OMITTED for "All my groups" on purpose: browse() fans out over the caller's
  // visible scopes only when no groupId is supplied. Setting it unconditionally
  // pinned the feed to a single partition and made that fan-out unreachable.
  if (groupFilter) params.set("groupId", groupFilter);
  const endpoint = `/events/ideas?${params.toString()}`;

  const { ideas, loadingInitial, loadingMore, hasMore, stale, error, loadMore, refresh } =
    useInfiniteIdeas(endpoint, PAGE_SIZE_MEMBER);

  const handleVote = async (id: string) => {
    try { await apiFetch(`/events/ideas/${id}/vote`, { method: "POST" }); refresh(); }
    catch (e) { setMsg((e as Error).message); }
  };

  const handleSubmit = async () => {
    if (!form.title.trim()) { setFormError("Title is required."); return; }
    setSubmitting(true); setFormError(null);
    // The FORM's selector is authoritative — that is the control the user set.
    // This used to read `groupFilter` (the browse filter) instead, so picking a
    // group in the form had no effect on the wire and every idea was filed under
    // whatever the reader happened to be looking at, normally "COMMUNITY".
    const targetGroupId = form.groupId || "COMMUNITY";
    try {
      await apiFetch("/events/ideas", { method: "POST", body: JSON.stringify({
        title: form.title.trim(), description: form.description.trim(),
        format: form.format, timePreference: form.timePreference,
        deliveryMode: form.deliveryMode, groupId: targetGroupId,
      })});
      setMsg("💡 Idea submitted! The community can now vote on it.");
      setShowForm(false);
      setForm({ title: "", description: "", format: "", timePreference: "", deliveryMode: "", groupId: targetGroupId });
      refresh();
    } catch (e) { setFormError((e as Error).message); }
    finally { setSubmitting(false); }
  };

  return (
    <div>
      {/* Suggest form */}
      <div style={{ background: "var(--info-bg)", border: "1px solid var(--info)", borderRadius: "var(--radius, 6px)", padding: "14px 18px", marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }} onClick={() => setShowForm((v) => !v)}>
          <div>
            <b style={{ color: "var(--info)" }}>💡 Suggest an Event</b>
            <span className="faint small" style={{ marginLeft: 8 }}>Have an idea? Submit it — the community votes and leaders act on the most popular ones.</span>
          </div>
          <span style={{ fontSize: 18, color: "var(--info)" }}>{showForm ? "▴" : "▾"}</span>
        </div>
        {showForm && (
          <div style={{ marginTop: 14 }}>
            <div className="field">
              <label>What&apos;s the event about? *</label>
              <input className="input" placeholder="e.g. Hands-on Bedrock Agents workshop"
                value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} maxLength={100} />
              <div className="hint">{form.title.length}/100 chars</div>
            </div>
            <div className="field">
              <label>Describe what you&apos;d like to learn or do</label>
              <textarea className="input" rows={2} placeholder="e.g. Cover tool use, guardrails, 2-hour hands-on for intermediate devs."
                value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} maxLength={500} style={{ resize: "vertical" }} />
              <div className="hint">{form.description.length}/500 chars</div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 12 }}>
              {[
                { label: "Format", key: "format", opts: FORMAT_OPTIONS },
                { label: "Preferred time", key: "timePreference", opts: TIME_OPTIONS },
                { label: "Delivery mode", key: "deliveryMode", opts: DELIVERY_OPTIONS },
              ].map(({ label, key, opts }) => (
                <div className="field mb-0" key={key}>
                  <label>{label}</label>
                  <select className="select" value={(form as any)[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })}>
                    {opts.map((o) => <option key={o}>{o}</option>)}
                  </select>
                </div>
              ))}
            </div>
            <div className="field">
              <label>Which group is this for?</label>
              <select className="select" style={{ maxWidth: 280 }} value={form.groupId} onChange={(e) => setForm({ ...form, groupId: e.target.value })}>
                <option value="COMMUNITY">Community-wide (any group)</option>
                {myGroups.map((g: any) => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
            </div>
            {formError && <p className="small" style={{ color: "var(--danger)" }}>{formError}</p>}
            <div className="btn-row">
              <button className="btn primary" disabled={submitting} onClick={handleSubmit}>
                {submitting ? "Submitting…" : "Submit Idea"}
              </button>
              <button className="btn" onClick={() => setShowForm(false)}>Cancel</button>
            </div>
          </div>
        )}
      </div>

      {msg && (
        <div style={{ background: "var(--success-bg)", border: "1px solid #86efac", borderRadius: "var(--radius)", padding: "10px 14px", marginBottom: 12, display: "flex", justifyContent: "space-between", fontSize: 13 }}>
          <span style={{ color: "var(--success)" }}>{msg}</span>
          <button className="icon-btn" onClick={() => setMsg(null)}>✕</button>
        </div>
      )}

      {/* Filter bar */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <div className="tabs" style={{ border: "none", margin: 0 }}>
          {/* Declined dropped here too: a declined idea is deleted, so the tab
              could only ever be empty. */}
          {["Open", "Greenlit", "All"].map((f) => (
            <div key={f} className={"tab" + (filter === f ? " active" : "")}
              style={{ padding: "4px 12px", fontSize: 12 }} onClick={() => setFilter(f)}>{f}</div>
          ))}
        </div>
        {/* Only groups the member belongs to. The submit form below has always
            filtered on `myState`; this selector did not, so it offered every group
            in the community and the server answered — that inconsistency inside
            one component was the visible half of the cross-group leak. Asking for
            a group you are not in is now a 403, so offering it would only produce
            an error. */}
        <select className="select" style={{ width: "auto", fontSize: 12 }}
          value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}>
          <option value="">All my groups</option>
          <option value="COMMUNITY">Community-wide</option>
          {myGroups.map((g: any) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </select>
      </div>

      {/* List */}
      {error && (
        <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 10 }}>
          <p className="small" style={{ color: "var(--danger)", margin: 0 }}>{error}</p>
        </div>
      )}
      {loadingInitial ? (
        <IdeaCardSkeleton />
      ) : ideas.length === 0 && !error ? (
        <div className="card"><p className="faint">No ideas here yet.</p></div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, opacity: stale ? 0.4 : 1, transition: "opacity .15s" }}>
          {ideas.map((idea) => <IdeaCard key={idea.id} idea={idea} onVote={handleVote} />)}
        </div>
      )}

      {loadingMore && <LoadingMoreRow />}
      {!loadingInitial && hasMore && !loadingMore && (
        <ScrollSentinel onVisible={loadMore} />
      )}
      {!loadingInitial && !hasMore && ideas.length > 0 && (
        <div style={{ textAlign: "center", padding: "12px 0", color: "var(--text-faint)", fontSize: 12 }}>
          — All ideas loaded —
        </div>
      )}
    </div>
  );
}

// ── Leader view (CL + UGL) ───────────────────────────────────────────────────

function LeaderIdeasView({ role, ledGroupId, groups }: { role: Role; ledGroupId?: string; groups: any[] }) {
  const isUgl = role === "UserGroupLeader";
  const [statusFilter, setStatusFilter] = useState("Open");
  const [groupFilter, setGroupFilter] = useState(isUgl ? (ledGroupId || "") : "");
  const [greenlightTarget, setGreenlightTarget] = useState<string | null>(null);
  const [declineTarget, setDeclineTarget] = useState<string | null>(null);
  const [greenlightNote, setGreenlightNote] = useState("");
  const [declineReason, setDeclineReason] = useState("");
  const [acting, setActing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const params = new URLSearchParams({ status: statusFilter });
  if (groupFilter) {
    params.set("groupId", groupFilter);
  } else if (!isUgl) {
    // "All groups": the feed index is partitioned by group and this service
    // keeps no group registry, so the CL's own group list tells it which
    // partitions to walk (same contract as the cross-group event stats).
    // Without this the server could only read COMMUNITY and every group-scoped
    // idea went missing.
    const ids = groups.map((g: any) => g.id).filter(Boolean);
    if (ids.length) params.set("groupIds", ids.join(","));
  }
  const endpoint = `/events/ideas/backlog?${params.toString()}`;

  const { ideas, loadingInitial, loadingMore, hasMore, stale, error, loadMore, refresh } =
    useInfiniteIdeas(endpoint, PAGE_SIZE_LEADER);

  const openCount = ideas.filter((i) => i.status === "Open").length;
  // The idea being declined, so the confirmation can name what is about to be
  // deleted. Deleting the wrong card is unrecoverable, and an id in a URL is no
  // help — the title and vote count are what a leader recognises.
  const declineIdea = ideas.find((i) => i.id === declineTarget);

  const handleVote = async (id: string) => {
    try { await apiFetch(`/events/ideas/${id}/vote`, { method: "POST" }); refresh(); }
    catch (e) { setMsg((e as Error).message); }
  };

  const doGreenlight = async () => {
    if (!greenlightTarget) return;
    setActing(true);
    try {
      await apiFetch(`/events/ideas/${greenlightTarget}/greenlight`, {
        method: "POST", body: JSON.stringify({ note: greenlightNote }),
      });
      setMsg("✅ Idea greenlit! Submitter has been notified.");
      setGreenlightTarget(null); setGreenlightNote("");
      refresh();
    } catch (e) { setMsg((e as Error).message); }
    finally { setActing(false); }
  };

  const doDecline = async () => {
    if (!declineTarget || !declineReason.trim()) return;
    setActing(true);
    try {
      await apiFetch(`/events/ideas/${declineTarget}/decline`, {
        method: "POST", body: JSON.stringify({ reason: declineReason }),
      });
      // No "submitter has been notified" — nothing consumes IdeaDeclined, so no
      // notification is sent and claiming one would be false.
      setMsg("Idea deleted permanently.");
      setDeclineTarget(null); setDeclineReason("");
      refresh();
    } catch (e) { setMsg((e as Error).message); }
    finally { setActing(false); }
  };

  return (
    <div>
      {isUgl && (
        <div style={{ background: "var(--info-bg)", border: "1px solid var(--info)", borderRadius: "var(--radius)", padding: "10px 14px", marginBottom: 14, fontSize: 13, color: "var(--info)" }}>
          ℹ️ Showing ideas for <b>{groups.find((g) => g.id === ledGroupId)?.name || "your group"}</b> only.
        </div>
      )}

      {msg && (
        <div style={{ background: "var(--success-bg)", border: "1px solid #86efac", borderRadius: "var(--radius)", padding: "10px 14px", marginBottom: 12, display: "flex", justifyContent: "space-between", fontSize: 13 }}>
          <span style={{ color: "var(--success)" }}>{msg}</span>
          <button className="icon-btn" onClick={() => setMsg(null)}>✕</button>
        </div>
      )}

      {/* Filter tabs */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
        <div className="tabs" style={{ border: "none", margin: 0 }}>
          {/* Declined and Archived removed: declining deletes the idea, and an
              archived idea is not something a leader acts on. Greenlit works now
              that the feed index is partitioned by status — it previously
              returned nothing because only Open ideas were indexed at all. */}
          {["Open", "Greenlit"].map((s) => (
            <div key={s} className={"tab" + (statusFilter === s ? " active" : "")}
              style={{ padding: "4px 12px", fontSize: 12 }}
              onClick={() => setStatusFilter(s)}>
              {/* The count is derived from the loaded page, so it is only
                  meaningful while the Open tab is the one being shown —
                  otherwise it read "Open (0)" whenever another tab was active. */}
              {s}{s === "Open" && statusFilter === "Open" ? ` (${openCount})` : ""}
            </div>
          ))}
        </div>
        {!isUgl && (
          <select className="select" style={{ width: "auto", fontSize: 12 }}
            value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}>
            <option value="">All groups</option>
            <option value="COMMUNITY">Community-wide</option>
            {groups.map((g: any) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
        )}
      </div>

      {/* List */}
      {error && (
        <div className="card" style={{ borderColor: "var(--danger)", marginBottom: 10 }}>
          <p className="small" style={{ color: "var(--danger)", margin: 0 }}>{error}</p>
        </div>
      )}
      {loadingInitial ? (
        <IdeaCardSkeleton />
      ) : ideas.length === 0 && !error ? (
        <div className="card"><p className="faint">No {statusFilter.toLowerCase()} ideas.</p></div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, opacity: stale ? 0.4 : 1, transition: "opacity .15s" }}>
          {ideas.map((idea) => (
            <IdeaCard key={idea.id} idea={idea} onVote={handleVote}
              isLeader onGreenlight={setGreenlightTarget} onDecline={setDeclineTarget} />
          ))}
        </div>
      )}

      {loadingMore && <LoadingMoreRow />}
      {!loadingInitial && hasMore && !loadingMore && (
        <ScrollSentinel onVisible={loadMore} />
      )}
      {!loadingInitial && !hasMore && ideas.length > 0 && (
        <div style={{ textAlign: "center", padding: "12px 0", color: "var(--text-faint)", fontSize: 12 }}>
          — All ideas loaded —
        </div>
      )}

      {/* Greenlight modal */}
      {greenlightTarget && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="card" style={{ width: 480, maxWidth: "92vw" }}>
            <div className="card-head"><h3>✅ Greenlight this idea</h3><button className="icon-btn" onClick={() => setGreenlightTarget(null)}>✕</button></div>
            <p className="small">The submitter will be notified. You can then create the event using the idea&apos;s details.</p>
            <div className="field">
              <label>Note to submitter (optional)</label>
              <textarea className="input" rows={2} placeholder="e.g. Great idea — planning to schedule for next month!"
                value={greenlightNote} onChange={(e) => setGreenlightNote(e.target.value)} style={{ resize: "vertical" }} />
            </div>
            <div className="btn-row mt-12">
              <button className="btn primary" disabled={acting} onClick={doGreenlight}>
                {acting ? "Saving…" : "✅ Greenlight & Notify Submitter"}
              </button>
              <button className="btn" onClick={() => setGreenlightTarget(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Decline modal */}
      {declineTarget && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="card" style={{ width: 480, maxWidth: "92vw" }} role="alertdialog"
               aria-modal="true" aria-labelledby="decline-idea-title">
            <div className="card-head">
              <h3 id="decline-idea-title" style={{ margin: 0 }}>Delete this idea permanently?</h3>
              <button className="icon-btn" aria-label="Close"
                      onClick={() => setDeclineTarget(null)}>✕</button>
            </div>
            {/* Declining DELETES the idea — the copy leads with that because it is
                the actual and irreversible consequence, and follows the wording
                shape used for the other destructive confirmations (see the
                Remove Member confirm on the group detail page).
                It deliberately no longer claims the submitter is notified:
                nothing consumes the IdeaDeclined event, so no notification is
                sent and saying otherwise would be false. */}
            <div style={{ fontSize: 13.5, color: "var(--text-muted)", lineHeight: 1.6 }}
                 data-testid="decline-idea-warning">
              {declineIdea?.title && (
                <p style={{ marginTop: 0 }}>
                  You are about to delete <b>&ldquo;{declineIdea.title}&rdquo;</b>
                  {declineIdea.submitterName ? <> submitted by <b>{declineIdea.submitterName}</b></> : null}.
                </p>
              )}
              <p style={{ color: "var(--danger)" }}>
                ⚠️ Declining <b>permanently deletes</b> this idea and{" "}
                {voteCountPhrase(declineIdea?.voteCount)} cast on it.
                It will disappear from every tab and <b>cannot be undone</b>.
              </p>
              <p style={{ marginBottom: 0 }}>
                Your reason is recorded against the deletion. It is not shown to the
                submitter, so tell them separately if they should know — they are free
                to submit the idea again.
              </p>
            </div>
            <div className="field mt-12">
              <label htmlFor="decline-idea-reason">Reason for deleting *</label>
              <textarea id="decline-idea-reason" className="input" rows={3}
                placeholder="e.g. We have a similar session planned for Q4."
                value={declineReason} onChange={(e) => setDeclineReason(e.target.value)}
                style={{ resize: "vertical" }} />
            </div>
            <div className="btn-row mt-12">
              <button className="btn danger" data-testid="decline-idea-confirm"
                      disabled={acting || !declineReason.trim()} onClick={doDecline}>
                {acting ? "Deleting…" : "Delete Idea Permanently"}
              </button>
              <button className="btn" data-testid="decline-idea-cancel"
                      onClick={() => setDeclineTarget(null)}>Keep Idea</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main export ──────────────────────────────────────────────────────────────

export default function EventIdeasTab({ role, ledGroupId }: { role: Role; ledGroupId?: string }) {
  const groups = useApi<{ items: any[] }>("/groups");
  const groupList = groups.data?.items ?? [];
  const isLeader = role === "CommunityLeader" || role === "UserGroupLeader";

  if (groups.loading) return <IdeaCardSkeleton />;

  return isLeader
    ? <LeaderIdeasView role={role} ledGroupId={ledGroupId} groups={groupList} />
    : <MemberIdeasView groups={groupList} />;
}
