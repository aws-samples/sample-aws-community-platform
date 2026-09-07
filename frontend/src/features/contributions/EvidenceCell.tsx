import { safeHref } from "../../lib/safeUrl";

// The evidence link as rendered in the leader approval queue (finding
// f-74a4a413). Extracted from ContributionsPage rather than left inline for one
// reason: as an inline ternary inside a column definition it was unreachable
// from a test, so the single most security-sensitive render decision in the SPA
// was covered by nothing. safeUrl.test.ts proves safeHref works; it cannot
// prove a call site actually uses it.
//
// Why this still matters after the server-side https check: that check only
// guards NEW submissions. Rows stored before it shipped still hold whatever the
// member typed, and this component is the only thing standing between such a row
// and a leader's session — React does not sanitize href, so a stored
// `javascript:` URI renders as a live link and executes on click, in the
// session of the CL/UGL reviewing the queue.
//
// Returning a plain <span> rather than an <a> with a neutralised href is
// deliberate: there is no anchor at all, so there is nothing to click, no
// target for a middle-click or "copy link address", and no href for a later
// refactor to accidentally repopulate.
export function EvidenceCell({ value }: { value: unknown }) {
  const href = safeHref(value);
  if (href) {
    return <a href={href} target="_blank" rel="noreferrer">link ↗</a>;
  }
  // Present but untrusted: say so, rather than rendering nothing. A reviewer
  // seeing a blank cell would assume the member forgot the evidence; they need
  // to know a value exists and was refused, so they can reject it.
  if (value) {
    return <span title="Evidence link is not a valid https URL.">unsafe link</span>;
  }
  return <>—</>;
}
