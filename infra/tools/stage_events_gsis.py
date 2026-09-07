#!/usr/bin/env python3
"""Stage the Events table's GSIs across sequential deployments (finding F2).

DynamoDB permits ONE GSI creation per UpdateTable, so a table going from zero to
four indexes needs four deployments. CloudFormation diffs the new template
against its own LAST-KNOWN TEMPLATE (not against reality), which is why creating
the indexes out of band first does not work — it still batches four creations and
fails. See
aidlc-docs/construction/events/infrastructure-design/deployment-architecture.md

This rewrites `infra/services/service-events-data.yaml` so it declares only the
requested indexes, keeping everything else byte-identical. `AttributeDefinitions`
is trimmed to match, because DynamoDB rejects an attribute definition that no key
schema references ("Some AttributeDefinitions are not used").

Usage:
    python3 infra/tools/stage_events_gsis.py 1        # GSI1 only
    python3 infra/tools/stage_events_gsis.py 1 2      # GSI1 + GSI2
    python3 infra/tools/stage_events_gsis.py 1 2 4 3  # all four (final state)

Run with all four at the end so the committed template is the complete one.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "services" / "service-events-data.yaml"

# Comment text kept alongside each index so the staged template stays readable.
NOTES = {
    1: ("# GSI1 - listings + calendar. SCOPE#<groupId|COMMUNITY>#<status> / startsAt.\n"
        "        # Queried as a partition walk over the caller's visible scopes."),
    2: ("# GSI2 - a member's own RSVPs. USER#<userId> / RSVP#<startsAt>#<eventId>.\n"
        "        # Also serves Member Profiles' activity-count fan-out."),
    3: ("# GSI3 - Content Library. SPARSE: only a Clean material on a Completed\n"
        "        # event carries the key, so the index holds publishable content only."),
    4: ("# GSI4 - UNUSED since the reminder feature was removed (2026-08-27).\n"
        "        # Kept only so the drop can be staged as its own change."),
}


def render_attributes(keep: list[int]) -> str:
    lines = ["      AttributeDefinitions:",
             "        - { AttributeName: pk, AttributeType: S }",
             "        - { AttributeName: sk, AttributeType: S }"]
    for n in keep:
        lines.append(f"        - {{ AttributeName: gsi{n}pk, AttributeType: S }}")
        lines.append(f"        - {{ AttributeName: gsi{n}sk, AttributeType: S }}")
    return "\n".join(lines) + "\n"


def render_indexes(keep: list[int]) -> str:
    if not keep:
        return ""
    lines = ["      GlobalSecondaryIndexes:"]
    for n in keep:
        lines.append(f"        {NOTES[n]}")
        lines.append(f"        - IndexName: GSI{n}")
        lines.append("          KeySchema:")
        lines.append(f"            - {{ AttributeName: gsi{n}pk, KeyType: HASH }}")
        lines.append(f"            - {{ AttributeName: gsi{n}sk, KeyType: RANGE }}")
        lines.append("          Projection: { ProjectionType: ALL }")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    keep = [int(a) for a in argv]
    if any(n not in NOTES for n in keep):
        print(f"indexes must be from {sorted(NOTES)}", file=sys.stderr)
        return 2

    text = TEMPLATE.read_text()

    attrs = re.compile(r"^      AttributeDefinitions:\n(?:        - .*\n)+", re.M)
    if not attrs.search(text):
        print("could not locate AttributeDefinitions block", file=sys.stderr)
        return 1
    text = attrs.sub(render_attributes(keep), text, count=1)

    # The index block runs from `GlobalSecondaryIndexes:` up to (not including)
    # the next same-indentation key, which is StreamSpecification.
    idx = re.compile(r"^      GlobalSecondaryIndexes:\n(?:.*\n)*?(?=^      StreamSpecification:)", re.M)
    if idx.search(text):
        text = idx.sub(render_indexes(keep), text, count=1)
    else:
        text = text.replace("      StreamSpecification:",
                            render_indexes(keep) + "      StreamSpecification:", 1)

    TEMPLATE.write_text(text)
    print(f"service-events-data.yaml now declares: {[f'GSI{n}' for n in keep] or 'no GSIs'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
