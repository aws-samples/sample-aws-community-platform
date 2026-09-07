import { describe, expect, it } from "vitest";
import {
  ALL_STATUS_VALUES,
  buildLedgerQuery,
  certLedgerStatusLabel,
  exportFilename,
  toExportRow,
} from "./certLedger";

const gname = (id?: string | null) => (id ? { "g-1": "Serverless Guild" }[id] ?? "—" : "Community-wide");

describe("buildLedgerQuery", () => {
  it("always includes the quarter", () => {
    expect(buildLedgerQuery({ quarter: "2026-Q2", statuses: [...ALL_STATUS_VALUES] }))
      .toBe("quarter=2026-Q2");
  });

  it("omits status when all are selected (server default)", () => {
    const q = buildLedgerQuery({ quarter: "2026-Q2", statuses: [...ALL_STATUS_VALUES] });
    expect(q).not.toContain("status");
  });

  it("sends status csv for a strict subset", () => {
    const q = buildLedgerQuery({ quarter: "2026-Q2", statuses: ["Active", "Revoked"] });
    expect(q).toContain("status=Active%2CRevoked");
  });

  it("includes group, cert and member filters when set", () => {
    const q = buildLedgerQuery({
      quarter: "2026-Q2", groupId: "g-1", certId: "cert-saa", memberId: "u-1",
      statuses: [...ALL_STATUS_VALUES],
    });
    expect(q).toContain("groupId=g-1");
    expect(q).toContain("certId=cert-saa");
    expect(q).toContain("memberId=u-1");
  });

  it("sends a free-text member name", () => {
    const q = buildLedgerQuery({
      quarter: "2026-Q2", memberName: "alex", statuses: [...ALL_STATUS_VALUES],
    });
    expect(q).toContain("memberName=alex");
  });

  it("trims the member name and omits it when blank", () => {
    expect(buildLedgerQuery({
      quarter: "2026-Q2", memberName: "  alex kim  ", statuses: [...ALL_STATUS_VALUES],
    })).toContain("memberName=alex+kim");
    // Whitespace only must not become a filter that matches nothing.
    expect(buildLedgerQuery({
      quarter: "2026-Q2", memberName: "   ", statuses: [...ALL_STATUS_VALUES],
    })).not.toContain("memberName");
  });

  it("treats empty group as all groups (omitted)", () => {
    const q = buildLedgerQuery({ quarter: "2026-Q2", groupId: "", statuses: [...ALL_STATUS_VALUES] });
    expect(q).not.toContain("groupId");
  });
});

describe("certLedgerStatusLabel", () => {
  it("renders Approved as Active", () => {
    expect(certLedgerStatusLabel("Approved")).toBe("Active");
  });
  it("passes other statuses through", () => {
    expect(certLedgerStatusLabel("Expired")).toBe("Expired");
    expect(certLedgerStatusLabel("Revoked")).toBe("Revoked");
  });
});

describe("exportFilename", () => {
  it("encodes scope and quarter (quarter case preserved)", () => {
    expect(exportFilename("Serverless Guild", "2026-Q2")).toBe("certifications_serverless-guild_2026-Q2.csv");
  });
  it("appends the member when filtered", () => {
    expect(exportFilename("All groups", "2026-Q2", "Alex Morgan"))
      .toBe("certifications_all-groups_2026-Q2_alex-morgan.csv");
  });
});

describe("toExportRow", () => {
  it("maps a row to CSV columns with names, not ids, and Active label", () => {
    const row = {
      memberName: "Alex Morgan", certName: "AWS SA", certCategory: "AWS Certification",
      certificationDate: "2026-05-02", dateEarned: "2026-05-02",
      decidedAt: "2026-05-04T09:00:00Z", creditedGroupId: "g-1",
      status: "Approved", expiresAt: "2029-05-02",
    };
    expect(toExportRow(row, gname)).toEqual({
      member: "Alex Morgan",
      certification: "AWS SA",
      category: "AWS Certification",
      certification_date: "2026-05-02",
      earned_date: "2026-05-02",
      approved_date: "2026-05-04",
      user_group: "Serverless Guild",
      status: "Active",
      expires_on: "2029-05-02",
    });
  });

  it("falls back gracefully for missing fields", () => {
    const out = toExportRow({ certId: "cert-x", status: "Revoked" }, gname);
    expect(out.member).toBe("Unknown member");
    expect(out.certification).toBe("cert-x");
    expect(out.user_group).toBe("Community-wide");
    expect(out.status).toBe("Revoked");
  });
});
