#!/usr/bin/env bash
# Fails when the test coverage of a Go package falls below its floor.
#
# The floors sit a few points under the figures measured on 2026-10-24, so that an ordinary
# change does not trip them but a package whose tests are dropped or left behind does. Raise a
# floor when its package gets better; lower one only with a reason in the pull request.
#
# Run from the go/ folder: bash ../scripts/coverage-floor.sh
set -euo pipefail

floors="
engine 92
capacity 94
planning 93
calendar 82
forecast 82
analysis 82
sources 87
ticketimport 87
storage 82
app 78
datasvc 73
gitsync 62
githistory 67
sprintcal 60
assign 95
"

packages=()
while read -r name _; do
  [ -n "$name" ] && packages+=("./internal/$name")
done <<<"$floors"

out=$(go test -count=1 -cover "${packages[@]}")
echo "$out"

status=0
while read -r name floor; do
  [ -n "$name" ] || continue
  got=$(grep -E "internal/$name[[:space:]].*coverage:" <<<"$out" | sed -E 's/.*coverage: ([0-9.]+)%.*/\1/' | head -n1)
  if [ -z "$got" ]; then
    echo "::error::No coverage figure for internal/$name"
    status=1
  elif awk -v g="$got" -v f="$floor" 'BEGIN { exit !(g < f) }'; then
    echo "::error::internal/$name has $got % coverage, the floor is $floor %"
    status=1
  fi
done <<<"$floors"
exit $status
