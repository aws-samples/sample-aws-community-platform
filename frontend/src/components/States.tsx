// Shared loading / empty / coming-soon / error states (mockup card styling).

export function Loading({ label = "Loading\u2026" }: { label?: string }) {
  return <div className="card text-c" style={{ padding: 32 }}><p className="faint mb-0">{label}</p></div>;
}

export function ComingSoon({ feature }: { feature: string }) {
  return (
    <div className="card text-c" data-testid="coming-soon" style={{ padding: 32 }}>
      <div style={{ fontSize: 32 }}>🚧</div>
      <h3 style={{ margin: "8px 0 4px" }}>Coming soon</h3>
      <p className="faint mb-0">{feature} isn&apos;t available yet in this environment.</p>
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="card text-c" data-testid="empty-state" style={{ padding: 32 }}>
      <div style={{ fontSize: 32 }}>📭</div>
      <p className="faint mb-0">{message}</p>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="card text-c" data-testid="error-state" style={{ padding: 32 }}>
      <div style={{ fontSize: 32 }}>⚠️</div>
      <p className="faint mb-0">{message}</p>
    </div>
  );
}

// Skeleton placeholder matching the IdeaCard layout (vote column + body).
// Shown while the initial page of ideas is loading — avoids a blank flash.
export function IdeaCardSkeleton() {
  return (
    <>
      <style>{`
        @keyframes idea-pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
        .idea-skel { animation: idea-pulse 1.4s ease-in-out infinite; background: var(--border); border-radius: 5px; }
      `}</style>
      {[0, 1, 2].map((i) => (
        <div key={i} style={{
          background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: "var(--radius, 6px)", padding: "14px 16px",
          display: "flex", gap: 14, alignItems: "flex-start",
        }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, minWidth: 52 }}>
            <div className="idea-skel" style={{ width: 38, height: 38, borderRadius: 8 }} />
            <div className="idea-skel" style={{ width: 24, height: 16, borderRadius: 4 }} />
          </div>
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <div className="idea-skel" style={{ height: 14, width: `${55 + i * 10}%`, borderRadius: 4 }} />
              <div className="idea-skel" style={{ height: 14, width: 60, borderRadius: 4, flexShrink: 0 }} />
            </div>
            <div className="idea-skel" style={{ height: 12, width: "90%", borderRadius: 4 }} />
            <div className="idea-skel" style={{ height: 12, width: "70%", borderRadius: 4 }} />
            <div style={{ display: "flex", gap: 6, marginTop: 2 }}>
              <div className="idea-skel" style={{ height: 18, width: 70, borderRadius: 4 }} />
              <div className="idea-skel" style={{ height: 18, width: 55, borderRadius: 4 }} />
              <div className="idea-skel" style={{ height: 18, width: 110, borderRadius: 4 }} />
            </div>
          </div>
        </div>
      ))}
    </>
  );
}

// Spinner row shown at the bottom while loading the next page (infinite scroll).
export function LoadingMoreRow({ label = "ideas" }: { label?: string }) {
  return (
    <>
      <style>{`
        @keyframes idea-spin { to { transform: rotate(360deg); } }
        .idea-spinner {
          width: 16px; height: 16px; border-radius: 50%;
          border: 2px solid var(--border-strong);
          border-top-color: var(--primary);
          animation: idea-spin 0.7s linear infinite;
          flex-shrink: 0;
        }
      `}</style>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
                    gap: 8, padding: "14px 0", color: "var(--text-faint)", fontSize: 13 }}>
        <div className="idea-spinner" />
        Loading more {label}&hellip;
      </div>
    </>
  );
}

// Skeleton for the 3-column EventCard grid in MemberEventsBrowser.
// 6 cards (2 rows) match a typical Upcoming/Completed/Cancelled page.
export function EventCardSkeleton() {
  return (
    <div className="grid cols-3" style={{ gap: 16 }}>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="card" style={{
          animation: `idea-pulse 1.4s ease-in-out ${i * 0.1}s infinite`,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
            <div className="idea-skel" style={{ height: 20, width: 80, borderRadius: 999 }} />
            <div className="idea-skel" style={{ height: 20, width: 70, borderRadius: 999 }} />
          </div>
          <div className="idea-skel" style={{ height: 18, width: "85%", borderRadius: 4, marginBottom: 10 }} />
          <div className="idea-skel" style={{ height: 13, width: "60%", borderRadius: 4, marginBottom: 6 }} />
          <div className="idea-skel" style={{ height: 13, width: "50%", borderRadius: 4, marginBottom: 16 }} />
          <div className="idea-skel" style={{ height: 30, width: 80, borderRadius: 8 }} />
        </div>
      ))}
    </div>
  );
}
