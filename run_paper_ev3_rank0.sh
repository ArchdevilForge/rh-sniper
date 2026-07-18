#!/bin/bash
# paper_ev3_rank0: same as paper_ev2 + max-client-rank 0 only (single-variable).
# New log files — does not overwrite paper_ev2.
set -euo pipefail
export PATH="/root/.npm-global/bin:/root/.local/bin:$PATH"
cd /root/Coding/rh-sniper

export RH_SNIPER_STATE="${RH_SNIPER_STATE:-state.paper_ev3_rank0.json}"
export RH_SNIPER_LOG="${RH_SNIPER_LOG:-trades.paper_ev3_rank0.jsonl}"
export RH_SNIPER_SCAN_LOG="${RH_SNIPER_SCAN_LOG:-scans.paper_ev3_rank0.jsonl}"
export RH_ETH_USD="${RH_ETH_USD:-1000}"

exec .venv/bin/rh-sniper run -p adff --paper-positions \
  --bankroll-eth 0.053 \
  --buy-eth 0.001 \
  --max-positions 999 \
  --max-open-exposure-pct 0 \
  --daily-loss-usd 999999 \
  --probe-eth 0 \
  --active-hours-cn all \
  --poll 1.0 \
  --gate-every 1 \
  --max-gates 12 \
  --min-mc 1000 \
  --max-mc 50000 \
  --min-liq 30 \
  --fresh-min-age 30 \
  --fresh-max-age 90 \
  --max-top10 0.70 \
  --max-top10-fresh 0.95 \
  --soft-retry-sec 2 \
  --no-unindexed-liq \
  --allowed-lps virtuals \
  --no-fake-heat \
  --lp-drop-pct 25 \
  --min-liq-hold 0 \
  --max-hold-sec 60 \
  --hard-sl 15 \
  --tp-ladder 8:100 \
  --scan-log \
  --hazard-mode shadow \
  --max-client-rank 0
