#!/usr/bin/env bash
# Wait for a DynamoDB GSI to reach ACTIVE, failing FAST on anything that is not
# simply "not ready yet".
#
# Why this exists: the obvious inline loop
#
#     for i in $(seq 1 90); do
#       st=$(aws dynamodb describe-table ... --output text 2>/dev/null)
#       [ "$st" = "ACTIVE" ] && break
#       sleep 10
#     done
#
# swallows every error. When an AWS session token expired mid-wait on
# 2026-08-05, every call failed and the loop kept sleeping — 30 minutes of
# apparent "still creating" that was really "no longer authenticated". An expired
# token and a backfilling index must not look the same.
#
# Usage: infra/tools/wait_for_gsi.sh <table> <index> [max-seconds]
set -uo pipefail

TABLE="${1:?usage: wait_for_gsi.sh <table> <index> [max-seconds]}"
INDEX="${2:?usage: wait_for_gsi.sh <table> <index> [max-seconds]}"
MAX="${3:-1800}"
REGION="${AWS_DEFAULT_REGION:-${REGION:-us-east-1}}"

start=$(date +%s)
while :; do
  if ! out=$(aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" \
              --query "Table.GlobalSecondaryIndexes[?IndexName=='$INDEX'].IndexStatus | [0]" \
              --output text 2>&1); then
    echo "FATAL: describe-table failed — not a readiness problem:" >&2
    echo "  $out" >&2
    exit 2
  fi

  elapsed=$(( $(date +%s) - start ))
  case "$out" in
    ACTIVE)  echo "$INDEX ACTIVE after ${elapsed}s"; exit 0 ;;
    None|"") echo "FATAL: $INDEX does not exist on $TABLE" >&2; exit 3 ;;
    CREATING|UPDATING) : ;;
    *)       echo "FATAL: $INDEX in unexpected state '$out'" >&2; exit 4 ;;
  esac

  if [ "$elapsed" -ge "$MAX" ]; then
    echo "TIMEOUT: $INDEX still $out after ${elapsed}s" >&2
    exit 1
  fi
  printf '  %s: %s (%ss)\n' "$INDEX" "$out" "$elapsed"
  sleep 15
done
