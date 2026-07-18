# Logging Guidelines (rh-sniper)

> Structured JSONL contracts for paper/live measurement. English.

---

## Scope / Trigger

Update this file when adding/changing trade, scan, or gate audit fields.

Paths (env override):

| Env | Default |
|-----|---------|
| `RH_SNIPER_LOG` | `trades.live.jsonl` / `trades.dry.jsonl` |
| `RH_SNIPER_SCAN_LOG` | `scans.{live\|shadow\|dry}.jsonl` |
| `RH_SNIPER_STATE` | `state.{live\|dry}.json` |

Paper experiments use explicit names e.g. `trades.paper_ev2.jsonl` via env/cmdline wrappers.

---

## Signatures

```python
log_event(obj: dict) -> None       # append one JSON line to LOG_PATH; injects ts
log_scan_event(obj: dict) -> None  # SCAN_LOG_PATH
gate_audit_fields(snap: dict | None) -> dict
compact_sell_ladder(ladder: dict | None) -> dict | None
compact_liq_path(path: list | None, max_n: int = 5) -> list | None
```

---

## Contracts — trade events (`event` field)

### Required on every `buy` and `shadow_signal`

Must include **`gate_audit_fields(snap)`** (spread with `**`):

| Field | Type | Meaning |
|-------|------|---------|
| `age` | int \| null | entry age seconds |
| `hazard_liq` | str \| null | liq-path hazard reason or null if clean/skipped |
| `hazard_depth` | str \| null | sell-ladder depth hazard or null |
| `hazard_liq_err` | str \| null | observe path error |
| `liq_path` | list \| null | compact `[{ts,liq,mc}, …]` |
| `sell_ladder` | dict \| null | compact q25/50/100/200 + ok flags |

Also typical: `token`, `symbol`, `mc`, `entry_liq`/`liq`, `lp`, `client_rank`, `scan_ts`, `mode`, `why`.

### `reject`

Same audit fields **when snap reached that stage** (may be null if rejected before hazard).  
Plus: `reason`, `soft`, `gate_started_ts`.

### `paper_exit` / ticks

Post-buy only. **Never** use as historical entry gates (look-ahead).

| Event | Role |
|-------|------|
| `paper_quote_tick` | exec_ret_pct, peak_exec_ret — MFE diagnostic |
| `paper_exit` | reason, pnl_eth_est, paper_total_est |

### `scan_candidate` (scan log)

Funnel: `was_selected_for_gate`, `gate_result`, `client_rank`, `age`, `mc`, `liq`.

---

## Validation & Error Matrix

| Situation | Behavior |
|-----------|----------|
| hazard_mode=off | hazard_* may be absent/null; still OK to emit keys as null via gate_audit_fields |
| reject before timing/mc | hazard_* null — expected |
| accept buy, shadow mode | hazard may be non-null but **must not block**; still log |
| accept buy, enforce | hazard non-null → reject reason `hazard:…`, not buy |
| Missing keys on buy | **Bug** — offline cannot compute P(lp_drop\|hazard) |

---

## Good / Base / Bad

**Good** — buy line contains `"hazard_liq": null, "hazard_depth": null, "sell_ladder": {"q100": …}`  
**Base** — reject `low_liq` with all hazard null  
**Bad** — successful buy with no `hazard_liq`/`hazard_depth` keys at all (paper_ev2 gap)

---

## Tests Required

- `scripts/test_paper_exec.py::test_gate_audit_fields` — compact ladder drops junk keys  
- `scripts/hazard_report.py --self-check` — shadow discrimination join when keys present  
- Offline: `scripts/paper_ev2_buckets.py` prints measurable hazard table only if keys exist  

---

## Wrong vs Correct

| Wrong | Correct |
|-------|---------|
| Log hazard only on reject | Log audit fields on **buy + shadow_signal + reject** |
| Use first mon drop as entry counterfactual | Report loss ceiling only; gates use pre-buy fields |
| Full sell_ladder with error blobs | `compact_sell_ladder` numeric legs |
| Trust log `day_pnl` for bankroll EV | Sum `paper_exit.pnl_eth_est` / jsonl |

---

## What NOT to log

- Private keys, JWT, full raw GMGN responses with PII  
- Entire token security payloads every tick (scan already high volume)
