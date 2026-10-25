#!/usr/bin/env bash
# Validate an imported team and show the forecast, so the result can be compared with the sheet.
# Usage: check.sh DATA_DIR TEAM_ID [AS_OF_DATE]
#   DATA_DIR  the folder that contains teams/ (the data repository root)
#   TEAM_ID   the team folder name below teams/
#   AS_OF     optional reference date YYYY-MM-DD (default: today), useful for historical sheets
set -euo pipefail
data_dir="${1:?usage: check.sh DATA_DIR TEAM_ID [AS_OF_DATE]}"
team="${2:?usage: check.sh DATA_DIR TEAM_ID [AS_OF_DATE]}"
as_of=()
if [ -n "${3:-}" ]; then as_of=(--as-of "$3"); fi

command -v foresprint >/dev/null 2>&1 || { echo "foresprint is not installed, see https://github.com/swallat/foresprint/blob/main/docs/installation.md" >&2; exit 1; }
sf=(foresprint)

echo "== check =="
"${sf[@]}" --data "$data_dir/teams" ${as_of[@]+"${as_of[@]}"} check
echo
echo "== forecast =="
"${sf[@]}" --data "$data_dir/teams" ${as_of[@]+"${as_of[@]}"} forecast "$team"
