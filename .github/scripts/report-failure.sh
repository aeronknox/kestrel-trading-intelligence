#!/usr/bin/env bash
# Run a command; if it fails, turn the end of its output into annotations on the run page
# (job logs need admin rights to read through the API, annotations don't).
#   .github/scripts/report-failure.sh "Install browser" npx playwright install chromium
set -uo pipefail
title="$1"
shift
log="$(mktemp)"
"$@" 2>&1 | tee "$log"
status=${PIPESTATUS[0]}
if [ "$status" -ne 0 ]; then
  echo "::error title=${title} failed (exit ${status})::$*"
  # Skip blank lines and Compose's per-container progress lines, which bury the actual error.
  grep -v -E '^\s*$| Container [^ ]+ +(Waiting|Healthy|Started|Starting|Created|Creating|Running|Recreated?)$' "$log" \
    | tail -n 15 | cut -c1-500 | sed "s/^/::error title=${title}::/"
fi
rm -f "$log"
exit "$status"
