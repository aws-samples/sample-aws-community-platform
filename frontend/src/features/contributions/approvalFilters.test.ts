import { describe, expect, it } from "vitest";

import { activityFilterOptions, groupFilterOptions } from "./approvalFilters";

// Regression cover for a bug found during live validation of the approval-queue
// paging fix. The filter dropdown was built from `a.activityId`, but the
// framework endpoint returns `a.id`. The missing field read as undefined, React
// rendered <option> with no value, and the browser then submits the option's TEXT
// — so the request became `activityId=Public speaking` while the server matches
// `public-speaking`. Result: selecting any activity showed "Showing 0".
//
// The server was fine throughout (activityId=public-speaking returned rows); the
// defect was entirely in constructing the option value.

const ACTIVITIES = [
  { id: "public-speaking", name: "Public speaking" },
  { id: "blog", name: "Blog / article" },
];

describe("activityFilterOptions", () => {
  it("uses the id as the option value, never the display name", () => {
    // THE bug: this returned [undefined, "Public speaking"], and an <option>
    // with no value submits its label.
    expect(activityFilterOptions(ACTIVITIES)).toEqual([
      ["public-speaking", "Public speaking"],
      ["blog", "Blog / article"],
    ]);
  });

  it("never emits an entry whose value is the label", () => {
    for (const [value, label] of activityFilterOptions(ACTIVITIES)) {
      expect(value).not.toBe(label);
      expect(value).toBeTruthy();
    }
  });

  it("drops entries with no usable id rather than rendering a valueless option", () => {
    // A valueless option is what caused the silent fallback, so it must not be
    // rendered at all — better a missing filter entry than one that filters wrong.
    const messy = [
      { id: "blog", name: "Blog / article" },
      { name: "No id at all" },
      { id: "", name: "Empty id" },
      { id: null, name: "Null id" },
    ];
    expect(activityFilterOptions(messy)).toEqual([["blog", "Blog / article"]]);
  });

  it("falls back to the id for a label when the name is missing", () => {
    // Losing a pretty label is cosmetic; losing the value breaks filtering.
    expect(activityFilterOptions([{ id: "mentor-member" }])).toEqual([
      ["mentor-member", "mentor-member"],
    ]);
  });

  it("handles absent data while the request is in flight", () => {
    expect(activityFilterOptions(undefined)).toEqual([]);
    expect(activityFilterOptions(null)).toEqual([]);
    expect(activityFilterOptions([])).toEqual([]);
  });
});

describe("groupFilterOptions", () => {
  it("uses the id as the value", () => {
    expect(groupFilterOptions([{ id: "g-1", name: "Example Test Group" }]))
      .toEqual([["g-1", "Example Test Group"]]);
  });

  it("drops unusable entries and tolerates absent data", () => {
    expect(groupFilterOptions([{ name: "orphan" }, { id: "g-2", name: "Real" }]))
      .toEqual([["g-2", "Real"]]);
    expect(groupFilterOptions(undefined)).toEqual([]);
  });
});
