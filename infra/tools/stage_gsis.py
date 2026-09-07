#!/usr/bin/env python3
"""Stage a service table's GSIs across sequential deployments (findings F2/F-C).

Generalisation of stage_events_gsis.py (kept for history): DynamoDB permits ONE
GSI creation per UpdateTable, so a table going from zero to N indexes needs N
deployments. CloudFormation diffs the new template against its own LAST-KNOWN
TEMPLATE (not against reality), which is why creating the indexes out of band
does not help — the next deploy still batches the creations and fails.

This rewrites `infra/services/service-<svc>-data.yaml` so it declares only the
requested indexes, keeping everything else byte-identical: comment lines inside
the GlobalSecondaryIndexes block are preserved for the indexes that remain.
`AttributeDefinitions` is trimmed to match, because DynamoDB rejects an
attribute definition no key schema references.

Usage:
    python3 infra/tools/stage_gsis.py certifications 1        # GSI1 only
    python3 infra/tools/stage_gsis.py certifications 1 2      # GSI1 + GSI2
    python3 infra/tools/stage_gsis.py certifications 1 2 3    # all (final state)

Deploy + `infra/tools/wait_for_gsi.sh` until ACTIVE between each step. Run the
full set last so the committed template is the complete one.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parents[1] / "services"


def _template_for(service: str) -> Path:
    path = SERVICES_DIR / f"service-{service}-data.yaml"
    if not path.exists():
        raise SystemExit(f"no such template: {path}")
    return path


def _parse_index_blocks(text: str) -> dict[int, str]:
    """Extract each `- IndexName: GSIn` entry (with any comment lines directly
    above it) from the full GlobalSecondaryIndexes block."""
    block_match = re.search(
        r"^      GlobalSecondaryIndexes:\n((?:        .*\n)+)", text, re.M)
    if not block_match:
        raise SystemExit("template has no GlobalSecondaryIndexes block to stage from "
                         "(run from the COMPLETE template)")
    body = block_match.group(1)
    blocks: dict[int, str] = {}
    current_lines: list[str] = []
    current_n: int | None = None
    for line in body.splitlines(keepends=True):
        name = re.match(r"        - IndexName: GSI(\d+)", line)
        if name:
            if current_n is not None:
                blocks[current_n] = "".join(current_lines)
            # Comments preceding this index belong to it.
            comment_lines = []
            while current_lines and current_lines[-1].lstrip().startswith("#"):
                comment_lines.insert(0, current_lines.pop())
            if current_n is not None:
                blocks[current_n] = "".join(current_lines)
            current_lines = comment_lines + [line]
            current_n = int(name.group(1))
        else:
            current_lines.append(line)
    if current_n is not None:
        blocks[current_n] = "".join(current_lines)
    return blocks


def _load_blocks(service: str, text: str) -> dict[int, str]:
    """The COMPLETE index set, cached on first run: staging GSI1-only rewrites
    the template, so a later `1 2` run could no longer find GSI2's definition
    in the file. The cache (infra/tools/.gsi-stage-cache-<svc>.json) is
    refreshed whenever the template declares more indexes than the cache —
    i.e. whenever the complete template is restored/extended."""
    import json
    cache_path = Path(__file__).with_name(f".gsi-stage-cache-{service}.json")
    in_file = _parse_index_blocks(text) if "GlobalSecondaryIndexes:" in text else {}
    cached: dict[int, str] = {}
    if cache_path.exists():
        cached = {int(k): v for k, v in json.loads(cache_path.read_text()).items()}
    merged = {**cached, **in_file}
    if merged != cached:
        cache_path.write_text(json.dumps({str(k): v for k, v in merged.items()}))
    if not merged:
        raise SystemExit("no GSI definitions found in template or cache — "
                         "run once from the COMPLETE template first")
    return merged


def main(argv: list[str]) -> int:
    if len(argv) < 1:
        print(__doc__, file=sys.stderr)
        return 2
    service, keep = argv[0], [int(a) for a in argv[1:]]
    template = _template_for(service)
    text = template.read_text()
    blocks = _load_blocks(service, text)
    unknown = [n for n in keep if n not in blocks]
    if unknown:
        print(f"template does not define GSI{unknown} (has {sorted(blocks)})",
              file=sys.stderr)
        return 2

    # AttributeDefinitions trimmed to pk/sk + kept indexes' keys.
    attr_lines = ["      AttributeDefinitions:",
                  "        - { AttributeName: pk, AttributeType: S }",
                  "        - { AttributeName: sk, AttributeType: S }"]
    for n in keep:
        attr_lines.append(f"        - {{ AttributeName: gsi{n}pk, AttributeType: S }}")
        attr_lines.append(f"        - {{ AttributeName: gsi{n}sk, AttributeType: S }}")
    attrs_re = re.compile(r"^      AttributeDefinitions:\n(?:        - .*\n)+", re.M)
    text = attrs_re.sub("\n".join(attr_lines) + "\n", text, count=1)

    gsi_block = ""
    if keep:
        gsi_block = "      GlobalSecondaryIndexes:\n" + "".join(blocks[n] for n in keep)
    block_re = re.compile(
        r"^      GlobalSecondaryIndexes:\n(?:        .*\n)+", re.M)
    if block_re.search(text):
        text = block_re.sub(gsi_block, text, count=1)
    elif gsi_block:
        # Template currently has no index block (fully staged down): re-insert
        # before StreamSpecification, where the complete template keeps it.
        text = text.replace("      StreamSpecification:",
                            gsi_block + "      StreamSpecification:", 1)

    template.write_text(text)
    print(f"service-{service}-data.yaml now declares: "
          f"{[f'GSI{n}' for n in keep] or 'no GSIs'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
