// Minimal client-side CSV parser for Bulk Import (US-1.31). Deliberately avoids
// third-party xlsx/CSV libraries: an npm audit of `xlsx` (SheetJS) surfaced two
// unpatched high-severity CVEs (Prototype Pollution, ReDoS) with no npm-published
// fix, which is an unacceptable risk for a path that parses admin-uploaded files.
// CSV-only keeps the attack surface small and auditable.
export function parseCsvText(text: string): Record<string, string>[] {
  const rows = splitCsvRows(text);
  if (rows.length === 0) return [];
  const headers = rows[0].map((h) => h.trim());
  return rows.slice(1)
    .filter((r) => r.some((c) => c.trim() !== ""))
    .map((r) => {
      const obj: Record<string, string> = {};
      headers.forEach((h, i) => { obj[h] = (r[i] ?? "").trim(); });
      return obj;
    });
}

// Splits raw CSV text into rows of fields, honoring double-quoted fields that may
// contain commas, newlines, or escaped ("") quotes.
function splitCsvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

  for (let i = 0; i < normalized.length; i++) {
    const c = normalized[i];
    if (inQuotes) {
      if (c === '"') {
        if (normalized[i + 1] === '"') { field += '"'; i++; } else { inQuotes = false; }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field); field = "";
    } else if (c === "\n") {
      row.push(field); field = "";
      rows.push(row); row = [];
    } else {
      field += c;
    }
  }
  if (field !== "" || row.length > 0) { row.push(field); rows.push(row); }
  return rows;
}

// Maps parsed rows into the backend's expected bulk-import row shape.
export function toImportRows(parsed: Record<string, string>[]): Record<string, unknown>[] {
  return parsed.map((r) => ({
    email: r.email ?? "",
    first_name: r.first_name ?? r.firstName ?? "",
    last_name: r.last_name ?? r.lastName ?? "",
    city: r.city ?? "",
    country: r.country ?? "",
    professional_role: r.professional_role ?? r.professionalRole ?? "",
    aws_project: r.aws_project ?? r.awsProject ?? "",
  }));
}

// time_zone is intentionally NOT an import column — imported users take the
// system-wide default time zone (Admin > Preferences), which an admin can
// override per user afterwards via Edit User.
export const IMPORT_TEMPLATE_HEADERS = [
  "email", "first_name", "last_name", "city", "country", "professional_role", "aws_project",
];

export const IMPORT_TEMPLATE_CSV =
  IMPORT_TEMPLATE_HEADERS.join(",") + "\n" +
  "member@example.com,Jane,Doe,Seattle,USA,Solutions Architect,yes\n";
