# rh-sniper

Robinhood-chain meme sniper via [GMGN OpenAPI](https://gmgn.ai) (`gmgn-cli`).

**Strategy replica — not copy-trading.**

It encodes the common playbook reverse-engineered from high-PnL Robinhood wallets:

```
safe_lp + mc_in_range + min_liq + (fresh OR reheat) + can_sell
  → fixed-size buy
  → ladder TP / SL (GMGN condition-orders)
  → LP-pull emergency dump
```

Default mode is **dry-run** (quotes only). Real money requires explicit `--live`.

> ⚠️ Meme trading can and will lose money. LP pulls, honeypots, lag, and rate limits are normal failure modes. This is research / automation tooling, not financial advice.

---

## Features

- **Entry filters** (not wallet mirroring)
  - Safe launchpads: `noxa` / `bankr` / `trench` / `virtuals` / `flap`
  - Market-cap band by profile
  - Fresh open window **or** reheat (1h volume / swaps)
  - `can_sell` / honeypot / tax / top10 / live quote gate
- **Exits**
  - Ladder take-profit + hard stop via `--condition-orders`
  - **LP monitor**: dump 100% if liquidity drops hard, floor breaks, or max hold hit
- **Rate-limit aware loop** (GMGN leaky bucket `rate=20/s`)
  - Fast loop: trenches scan + light position liquidity check
  - Slow gate: hard-check only a few candidates
- **Profiles** inspired by reversed styles: `adff` / `7a23` / `417c`

---

## Requirements

- Python **3.10+**
- [`gmgn-cli`](https://www.npmjs.com/package/gmgn-cli) installed and configured
- GMGN API key (and private key for live swaps)
- Robinhood-chain wallet funded if using `--live`

```bash
npm install -g gmgn-cli
gmgn-cli config --check
```

---

## Quick start

```bash
git clone https://github.com/ArchdevilForge/rh-sniper.git
cd rh-sniper

# single dry-run cycle (no funds moved)
python3 rh_sniper.py --once --profile adff

# continuous dry-run
python3 rh_sniper.py --profile adff

# live (real money) — start tiny
python3 rh_sniper.py --live --profile adff \
  --buy-eth 0.02 --max-positions 2 --daily-loss-usd 30
```

Optional wallet override:

```bash
export GMGN_WALLET=0xYourWalletBoundToApiKey
python3 rh_sniper.py --profile adff
```

Runtime files (gitignored):

| File | Purpose |
|------|---------|
| `state.json` | seen tokens / open positions |
| `trades.jsonl` | reject / buy / dump log |

Override paths with `RH_SNIPER_STATE` / `RH_SNIPER_LOG`.

---

## Profiles

Parameter packs from reverse engineering — **style**, not “mirror this address”.

| Profile | Size default | MC band | Style |
|---------|--------------|---------|--------|
| `adff` | `0.03` ETH | $3k–$15k | High frequency, micro-cap, tight exits |
| `7a23` | `0.06` ETH | $5k–$40k | Mid size, slightly more patient |
| `417c` | `0.12` ETH | $8k–$50k | Larger size, wider ladder / reheat |

```bash
python3 rh_sniper.py --profile adff
python3 rh_sniper.py --profile 7a23 --min-mc 8000 --max-mc 30000
python3 rh_sniper.py --profile 417c --buy-eth 0.05
```

---

## Entry rules (hard gate)

A candidate must pass:

1. **safe_lp** — launchpad in allowlist (use `--allow-uniswap` only if you accept naked pool risk)
2. **mc_in_range** — live market cap inside profile band
3. **min_liq** — liquidity floor
4. **timing**
   - `fresh`: open/create age ≤ `fresh_max_age`
   - `reheat`: older token but 1h volume/swaps above threshold
5. **can_sell** / not honeypot / tax not insane / top10 not extreme
6. **buy quote** must route

Then: fixed-size buy + ladder condition orders.

---

## LP pull (main kill condition)

Most losses on new RH pools are not “wrong direction” — they are **liquidity removal**.

| Trigger | Action |
|---------|--------|
| LP vs entry drops ≥ `--lp-drop-pct` (default 35%) | market sell 100% |
| Absolute liq `< --min-liq-hold` | dump |
| `can_sell` flips / honeypot | dump |
| hold time `> --max-hold-sec` | time stop dump |

Price SL handles “price down”. **LP monitor handles “pool gone”.**

Atomic same-block rugs can still win against any REST poller. Expect reduced damage, not zero rugs.

---

## API pacing

GMGN uses a leaky bucket: **rate=20, capacity=20**, routes have weights.

Defaults:

| Loop | Default | Work | Approx weight |
|------|---------|------|----------------|
| Fast | `--poll 1` | `trenches` + position `info` | 3 + 1×positions |
| Gate | every `--gate-every 2` | ≤ `--max-gates 2` hard checks | ≤ 8 / 2s |
| Security mon | every `--mon-sec-every 3` | position `security` | +1×positions |
| Trade | event | `swap` | 5 |

Steady-state target ~**7–12 weight/s** under the 20/s cap.

```bash
# recommended
python3 rh_sniper.py --poll 1 --gate-every 2 --max-gates 2 --mon-sec-every 3

# more aggressive (still not full 200ms hard-check spam)
python3 rh_sniper.py --poll 0.5 --gate-every 3 --max-gates 1
```

**Do not** set `--poll 0.2` with high `--max-gates` — you will 429 / ban.

---

## CLI reference

```text
--profile adff|7a23|417c
--wallet 0x...
--buy-eth 0.03
--slippage 30
--poll 1.0
--gate-every 2
--max-gates 2
--mon-sec-every 3
--min-mc / --max-mc
--min-liq
--fresh-max-age
--reheat-min-vol
--lp-drop-pct 35
--min-liq-hold 800
--max-hold-sec
--max-positions 3
--daily-loss-usd 100
--allow-uniswap
--live
--once
```

---

## Why not copy-trade?

Copy-trading high-PnL wallets on RH often means:

- buying **after** them
- paying worse entry / exit
- inheriting their already-moved market

This bot **scans the same venue class and applies the same rules**, but does not follow their addresses.

Speed alone is not edge. Filter quality + exit discipline + LP risk control matter more than shaving 50ms off a REST loop under rate limits.

---

## Project layout

```text
rh-sniper/
├── rh_sniper.py      # main bot
├── README.md
├── LICENSE           # MIT
├── .env.example
└── .gitignore
```

No extra Python deps — only stdlib + local `gmgn-cli`.

---

## Safety

- Dry-run by default
- Never commit API keys / private keys
- Start with tiny size and low `--max-positions`
- Expect bans if you hammer weight-heavy routes
- You are solely responsible for funds and compliance in your jurisdiction

---

## License

MIT © ArchdevilForge

---

## Disclaimer

This software interacts with decentralized markets and third-party APIs. Tokens can go to zero, become unsellable, or be rugged. Authors and contributors are not liable for losses. Use at your own risk.
