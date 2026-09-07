// Selectable IANA time zones offered across the portal (My Profile, Preferences
// > Time Zone, Add/Edit User, and the system-wide default in Admin Settings).
// One list so the member-facing and admin-facing pickers can't drift apart.
export interface TimezoneOption {
  value: string;
  label: string;
}

export const TIMEZONE_OPTIONS: TimezoneOption[] = [
  { value: "UTC", label: "(UTC) Coordinated Universal Time" },
  { value: "America/Los_Angeles", label: "(UTC-08:00) America/Los_Angeles" },
  { value: "America/New_York", label: "(UTC-05:00) America/New_York" },
  { value: "Europe/London", label: "(UTC+00:00) Europe/London" },
  { value: "Europe/Berlin", label: "(UTC+01:00) Europe/Berlin" },
  { value: "Asia/Kolkata", label: "(UTC+05:30) Asia/Kolkata" },
  { value: "Asia/Singapore", label: "(UTC+08:00) Asia/Singapore" },
  { value: "Asia/Tokyo", label: "(UTC+09:00) Asia/Tokyo" },
  { value: "Australia/Sydney", label: "(UTC+10:00) Australia/Sydney" },
];

/** Bare IANA identifiers, for pickers that don't want the offset prefix. */
export const TIMEZONES = TIMEZONE_OPTIONS.map((o) => o.value);

/**
 * Options for a time-zone picker, guaranteeing `current` is selectable.
 * Existing profiles may hold a zone that predates this list (it used to be a
 * free-text field), and a dropdown that omits it would silently reset the
 * member's saved value on the next save.
 */
export function timezoneOptions(current?: string | null): TimezoneOption[] {
  const c = (current ?? "").trim();
  return c && !TIMEZONES.includes(c) ? [{ value: c, label: c }, ...TIMEZONE_OPTIONS] : TIMEZONE_OPTIONS;
}
