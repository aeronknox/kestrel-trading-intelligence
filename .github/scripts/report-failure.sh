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
  grep -v '^\s*$' "$log" | tail -n 12 | cut -c1-500 | sed "s/^/::error title=${title}::/"
fi
rm -f "$log"
exit "$status"
