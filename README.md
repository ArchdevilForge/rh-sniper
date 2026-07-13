# rh-sniper

Robinhood-chain meme sniper via [GMGN OpenAPI](https://gmgn.ai) (`gmgn-cli`).

**Strategy replica — not copy-trading.**

It encodes the common playbook reverse-engineered from high-PnL Robinhood wallets:

```
safe_lp + mc_in_range + min_liq + (fresh OR reheat)
  + can_sell + buy_quote + sell_quote
  + fake_heat/creator filters
  → optional probe buy/sell
  → sized buy (fixed / risk% / exposure cap)
  → PRINCIPAL-OUT exit: ~2x sell ~55% (cost + small profit)
    then pyramid TP + trailing remainder + hard SL
  → LP/creator dump emergency exit
```

Default mode is **dry-run** (quotes only). Real money requires explicit `--live`.

**v0.4 live hardening:** order confirmation polling, 429 backoff, dry/live state isolation (`state.dry.json` / `state.live.json`), optional PnL refresh, missing-strategy local exit.

> ⚠️ Meme trading can and will lose money. LP pulls, honeypots, lag, and rate limits are normal failure modes. This is research / automation tooling, not financial advice.

---

## Features

- **Entry filters** (not wallet mirroring)
  - Safe launchpads: `noxa` / `bankr` / `trench` / `virtuals` / `flap`
  - Market-cap band by profile
  - Fresh open window **or** reheat (1h volume / swaps)
  - `can_sell` / honeypot / tax / top10
  - **Buy quote + sell quote** (sell-side route must exist)
  - **Fake-heat filters** (wash-ish / LPI-ish liq-mc extremes)
  - **Creator spam / hold filters**
- **Probe mode** (`--probe-eth`)
  - Tiny buy+sell (or dual quote in dry-run) before full size
- **Sizing**
  - Fixed `--buy-eth` or `--risk-pct` of native balance (capped)
- **Exits**
  - Ladder take-profit + hard stop via condition-orders
  - **LP monitor** + creator inventory dump + max hold → market dump
  - Emergency slippage tier separate from normal entry slippage
- **Live safety**
  - `--live` blocked if gmgn config fails or RH native balance too low
  - Optional `--anti-mev` on swaps
- **Ops CLI**
  - `run` / `status` / `logs` / `stats` / `doctor` / `reset-state`
- **Rate-limit aware dual loop** (GMGN leaky bucket `rate=20/s`)
- **Profiles**: `adff` / `7a23` / `417c`

---

## Requirements

- Python **3.10+**
- [`uv`](https://github.com/astral-sh/uv) recommended (or pip)
- [`gmgn-cli`](https://www.npmjs.com/package/gmgn-cli) installed and configured
- GMGN API key (and private key for live swaps)
- Robinhood-chain wallet funded if using `--live`

```bash
npm install -g gmgn-cli
gmgn-cli config --check
```

---

## Install

```bash
git clone https://github.com/ArchdevilForge/rh-sniper.git
cd rh-sniper

uv venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e .

rh-sniper --help
rh-sniper doctor
```

CLI entrypoint: **`rh-sniper`** (Typer). Compat: `python rh_sniper.py`.

---

## Quick start

```bash
# single dry-run cycle (no funds moved)
rh-sniper run --once -p adff

# recommended: main session only CN 18:00–04:00, rest otherwise
rh-sniper run -p adff --active-hours-cn 18-4

# recommended dry-run with probe quotes + sell-side check
rh-sniper run -p 7a23 --active-hours-cn 18-4 --probe-eth 0.001

# live (real money) — start tiny; blocked if RH balance too low
rh-sniper run --live -p adff \
  --buy-eth 0.02 --probe-eth 0.001 \
  --max-positions 2 --daily-loss-usd 30

# size as 2% of native, hard-capped
rh-sniper run -p adff --risk-pct 2 --max-buy-eth 0.05

# ops
rh-sniper doctor
rh-sniper status
rh-sniper logs -n 30
rh-sniper logs -e reject
rh-sniper stats
rh-sniper reset-state --yes
```

Optional wallet override:

```bash
export GMGN_WALLET=0xYourWalletBoundToApiKey
rh-sniper run -p adff
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

| Profile | Size | MC band | Exit (HF reverse) | First take | Hard SL | Hold |
|---------|------|---------|-------------------|------------|---------|------|
| `adff` | fixed `0.03` ETH | $3k–$15k | **hf_full** | **+20% 卖 100%** | -25% | 120s |
| `7a23` | risk 1% + **probe** | $5k–$40k | **hf_scale** | **+25% 卖 30%** | -30% | 300s |
| `417c` | risk 1.25% | $8k–$50k | **hf_scale** | **+30% 卖 25%** | -35% | 3600s |

### HF reverse-engineering (aligned defaults)

| Wallet | First-sell mult | First-sell size | Style |
|--------|-----------------|-----------------|--------|
| `0xadff…` | ~**1.12x** | often **100% clear** | fixed ~$52, thin high-freq |
| `0x7a23…` | ~**1.17x** | often **~30%** then more | probe + mid size |
| `0x417c…` | ~**1.47x** | often **~25%** then multi-sell | larger size + residual bag |

Big multiples come from **scale-out + residual bag over hours**, not from never selling.

### Position management (aligned)

| Style | Rule |
|-------|------|
| `adff` | **Fixed size** (not % risk) — like $52 template |
| `7a23` | **1% bankroll** + default **probe 0.001 ETH** |
| `417c` | **1.25% bankroll**, higher concurrent notional |
| All | `--max-open-exposure-pct 15`, `--max-positions`, daily loss halt |
| Kelly | upper bound only; stay **≤1–2%/trade** |

### Selection (aligned)

- Chain: **Robinhood**
- Venue: **noxa / bankr / trench / virtuals / flap**
- MC band by profile (micro / small / wider reheat)
- Fresh **or** reheat volume
- **can_sell + buy/sell quote** (+ optional probe)
- Fake-heat + creator spam filters
- Skip naked Uni unless `--allow-uniswap`

```bash
rh-sniper run -p adff
rh-sniper run -p 7a23 --min-mc 8000 --max-mc 30000
rh-sniper run -p 417c --buy-eth 0.05
```

---

## Entry rules (hard gate)

A candidate must pass:

1. **safe_lp** — launchpad in allowlist (`--allow-uniswap` only if you accept naked pool risk)
2. **mc_in_range** — live market cap inside profile band
3. **min_liq** — liquidity floor
4. **timing** — `fresh` or `reheat`
5. **can_sell** / not honeypot / tax / top10
6. **fake_heat** — reject wash-ish volume / extreme liq-mc ratios / one-way buy volume
7. **creator** — optional spam / still-holding filters
8. **buy quote** must route
9. **sell quote** must route (token → native on ~50% of estimated out)
10. optional **probe** — tiny buy+sell (live) or dual quote (dry-run)

Then: sized buy + ladder condition orders.

## Risk system (why most snipers die)

| Failure | Mitigation in rh-sniper |
|---------|-------------------------|
| LP pull | entry liq floor + live LP drop dump |
| Honeypot / unsellable | `can_sell` + **sell quote** + optional **probe** |
| Fake heat (wash / LPI) | vol/price + liq/mc filters |
| Creator serial rugs | `max_creator_open_count`, hold filter, creator dump mon |
| Oversize | `risk_pct` + caps + `max_positions` + daily loss halt |
| Live with empty wallet | `doctor` + live preflight |
| Rate-limit ban | dual-speed loop |
| MEV | `--anti-mev` on swaps |

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
rh-sniper run --poll 1 --gate-every 2 --max-gates 2 --mon-sec-every 3

# more aggressive (still not full 200ms hard-check spam)
rh-sniper run --poll 0.5 --gate-every 3 --max-gates 1
```

**Do not** set `--poll 0.2` with high `--max-gates` — you will 429 / ban.

---

## CLI reference

Built with **Typer** for subcommand management:

| Command | Purpose |
|---------|---------|
| `rh-sniper run` | Start sniper (dry-run default) |
| `rh-sniper status` | Open positions / counters |
| `rh-sniper logs` | Tail `trades.jsonl` |
| `rh-sniper stats` | Reject/buy/probe/exit summary |
| `rh-sniper doctor` | Check `gmgn-cli` + config + RH balance |
| `rh-sniper reset-state` | Clear local state |
| `rh-sniper version` | Version |

### `run` options

```text
-p / --profile adff|7a23|417c
-w / --wallet 0x...
--buy-eth 0.03
--risk-pct 0            # 2 = 2% of bankroll; 0 = use buy-eth
--use-default-risk      # use profile default risk% when risk-pct=0
--bankroll-eth 0        # 0 = native balance
--max-buy-eth 0
--max-open-exposure-pct 15
--probe-eth 0           # >0 enables probe path
--exit-mode principal|sniper|wide
--hard-sl 35            # e.g. 55 for deep SL
--tp-ladder 100:55,200:25,400:10
--trail-activate 100 --trail-dd 20
--no-trailing
--require-sell-quote / --no-sell-quote
--anti-mev / --no-anti-mev
--fake-heat / --no-fake-heat
--max-creator-open-count 20
--reject-creator-hold
--min-wallet-eth 0.01   # live gate
--slippage 30
--poll 1.0
--gate-every 2 --max-gates 2 --mon-sec-every 3
--min-mc / --max-mc --min-liq
--lp-drop-pct 35 --min-liq-hold 800 --max-hold-sec
--max-positions 3 --daily-loss-usd 100
--allow-uniswap --live --once
--active-hours-cn 18-4   # default: CN 18:00–04:00 only
--offhours-mode sleep    # rest off-hours (still monitors open positions)
--offhours-poll 60
--tz-offset 8
```

### Session (recommended)

Default **`--active-hours-cn 18-4`** = China time **18:00 → next day 04:00** (主力时间).
Outside the window: **no new entries**, long sleep; **open positions still monitored** for LP/SL exits.

```bash
# only main night session
rh-sniper run -p adff --active-hours-cn 18-4

# 24h (disable session filter)
rh-sniper run -p adff --active-hours-cn all

# custom multi windows
rh-sniper run -p 7a23 --active-hours-cn 18-4,8-12
```

### Example: your researched stack

```bash
# HF night session + probe
rh-sniper run -p 7a23 --active-hours-cn 18-4 --probe-eth 0.001

# larger size runners overnight window
rh-sniper run -p 417c --active-hours-cn 18-4 --use-default-risk
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
├── rh_sniper/           # package
│   ├── cli.py           # Typer CLI (run/status/logs/doctor/...)
│   ├── engine.py        # strategy loop + gates
│   └── __init__.py
├── rh_sniper.py         # thin compat launcher
├── pyproject.toml       # uv/pip install → `rh-sniper` entrypoint
├── README.md
├── LICENSE              # MIT
├── .env.example
└── .gitignore
```

Python deps: **typer** (+ rich). Trading data path still goes through local **`gmgn-cli`**.

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
