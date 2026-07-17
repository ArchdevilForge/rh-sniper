#!/bin/bash
# ~$100 live test: EV-filtered adff. REAL MONEY.
set -euo pipefail
export PATH="/root/.npm-global/bin:/root/.local/bin:$PATH"
cd /root/Coding/rh-sniper

export RH_ETH_USD="${RH_ETH_USD:-1000}"

# fund wallet first: need native >= --min-wallet-eth
exec .venv/bin/rh-sniper run -p adff --live \
  --wallet "${GMGN_WALLET:-0x37e9f4a84693bce7f7729612ee91a94c91eef898}" \
  --bankroll-eth 0.053 \
  --buy-eth 0.001 \
  --max-positions 2 \
  --max-open-exposure-pct 50 \
  --daily-loss-usd 15 \
  --min-wallet-eth 0.02 \
  --probe-eth 0 \
  --active-hours-cn all \
  --poll 1.0 \
  --gate-every 1 \
  --max-gates 8 \
  --fresh-min-age 30 \
  --fresh-max-age 90 \
  --allowed-lps virtuals \
  --no-unindexed-liq \
  --lp-drop-pct 25 \
  --min-liq-hold 0 \
  --max-hold-sec 60 \
  --hard-sl 15 \
  --tp-ladder 8:100
