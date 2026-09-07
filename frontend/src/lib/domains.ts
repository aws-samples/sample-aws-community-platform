// Allowed-email-domain field helpers (US-8.3 / BR-P3).
//
// Extracted 2026-08-11 after a deployed-app bug: the comma key did nothing in the
// "Allowed email domains" field. The field is a CONTROLLED input whose value was
// derived from the parsed array, so typing "amazon.com," parsed to
// ["amazon.com"] — filter(Boolean) drops the empty tail — and the re-render put
// "amazon.com" back in the box, swallowing the character. Same for the space
// after a comma. Both parse and join were individually correct; the defect was
// deriving the DISPLAYED value from the parse output instead of the raw draft,
// which is why the logic worth pinning is `domainsFieldValue`.

/** Raw text -> the array the API expects. Trims, drops empties. */
export function parseDomains(text: string): string[] {
  return text.split(",").map((d) => d.trim()).filter(Boolean);
}

/** Stored value -> canonical display text. Tolerates a plain string. */
export function joinDomains(stored: unknown): string {
  if (Array.isArray(stored)) return stored.join(", ");
  return typeof stored === "string" ? stored : "";
}

/**
 * What the input should show. While editing (`draft` non-null) the admin's raw
 * text is returned VERBATIM so partial input such as a trailing comma survives;
 * once committed (`draft === null`) the canonical form is shown.
 */
export function domainsFieldValue(draft: string | null, stored: unknown): string {
  return draft ?? joinDomains(stored);
}
