#!/bin/bash
# Shadow collector: gate + scan log, never buys. Opportunity-set measurement.
set -euo pipefail
export PATH="/root/.npm-global/bin:/root/.local/bin:$PATH"
cd "$(dirname "$0")"
# if deployed under /root/Coding/rh-sniper, prefer that
if [ -d /root/Coding/rh-sniper ]; then
  cd /root/Coding/rh-sniper
  export PATH="/root/.npm-global/bin:/root/.local/bin:$PATH"
fi

export RH_SNIPER_STATE="${RH_SNIPER_STATE:-state.shadow.json}"
export RH_SNIPER_LOG="${RH_SNIPER_LOG:-trades.shadow.jsonl}"
export RH_SNIPER_SCAN_LOG="${RH_SNIPER_SCAN_LOG:-scans.shadow.jsonl}"

exec .venv/bin/rh-sniper run -p adff \
  --shadow-collect \
  --scan-log \
  --hazard-mode shadow \
  --active-hours-cn all \
  --poll 1.0 \
  --gate-every 1 \
  --max-gates 12 \
  --fresh-min-age 30 \
  --fresh-max-age 90 \
  --allowed-lps virtuals \
  --no-unindexed-liq \
  --no-fake-heat \
  "$@"
