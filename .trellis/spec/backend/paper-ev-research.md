# Paper EV Research Contracts

> Offline evaluation rules after paper runs. Code-spec depth for research scripts + decision gates.

---

## Scope / Trigger

When analyzing `trades.*.jsonl` / proposing cmdline changes from paper results.

Primary artifacts:

- `docs/HANDOFF_PAPER_EV2_DILEMMA.md`
- `scripts/paper_ev2_buckets.py`
- `scripts/hazard_report.py`
- Task research: offline age/entry/hazard tables

---

## Signatures

```bash
python3 scripts/paper_ev2_buckets.py data/paper_ev2/trades.paper_ev2.jsonl
python3 scripts/hazard_report.py --log path/to/trades.jsonl
python3 scripts/hazard_report.py --self-check
```

Join rule: FIFO `buy` → `paper_exit` by `token` (lowercase).

---

## Contracts — allowed vs forbidden features

### Allowed entry features (pre-buy)

`age`, `mc`, `entry_liq`, `liq/mc`, `client_rank`, `lp`, `scan_ts` latency,  
`hazard_liq`, `hazard_depth`, `liq_path`, `sell_ladder` **from buy event**.

### Forbidden as historical entry gates (look-ahead)

- `paper_exit.reason` / exit category  
- `paper_quote_tick` / first mon / MFE / MAE  
- post-buy liquidity drop  

Post-buy MFE may be reported as **diagnostic** for TP/hold questions only.

---

## Metrics per bucket (required seven + late EV)

```text
n / WR / EV_per_trade / PF / TP% / lp_drop% / max_hold% / late_half_EV
```

Late half = trades with `buy.ts >= median(buy.ts)`.

Minimum n for a shippable gate: **≥30** (prefer ≥50), monotone or adjacent-bucket agreement, late EV same sign.

---

## Pre-registered decision tree (paper_ev2)

```text
age 30-45 / 45-60 / 60-75 / 75-90
  if 30-60 PF≈≥1 AND 60-90 toxic → optional paper_ev3_age60 only
  if 30-60 also clearly negative → do NOT run age60
    if hazard discrimination passes thresholds → optional enforce
    else → no TP/hold tweak; fix opportunity set / pre-entry momentum
```

### Hazard enforce thresholds (approx)

- lp_drop recall ≥40%  
- P(lp_drop\|h=1) ≥ 2× P(lp_drop\|h=0)  
- reject rate ≲50%  
- TP kill rate < lp_drop capture  
- late half same direction  

### paper_ev2 result (2026-07-18)

- ALL: n≈209, WR≈11%, PF≈0.40, net≈-0.0079 ETH  
- 30–60 PF=0.65 (not ≥1) → **no age60**  
- hazard keys missing on historical buys → **unmeasurable**; fixed by `gate_audit_fields` on buy  
- max_hold MFE p50=0% → **do not lower TP**  
- client_rank>0 TP%≈0 → single-var follow-up: `--max-client-rank 0` / `run_paper_ev3_rank0.sh`

---

## Validation & Error Matrix

| Claim | Required evidence |
|-------|-------------------|
| “Positive EV filter” | Bucket table + late EV > 0 + PF>1 |
| “age60 will fix” | 30–60 near PF1 and 60–90 worse |
| “hazard works” | buys_with_hazard_keys > 0 and discrimination metrics |
| “lower TP” | max_hold MFE mass in +3..+7%, not ~0% |

---

## Good / Base / Bad

**Good:** single-variable paper (`paper_ev3_rank0`, …) with frozen exits + new log names  
**Base:** offline report only, no cmdline change  
**Bad:** multi-knob retune after one negative paper; live while PF<1  

---

## Tests Required

- Buckets script reproduces net EV order of magnitude from jsonl  
- hazard_report self_check  
- After deploy: new buys contain hazard_* keys (spot-check one line)

---

## Wrong vs Correct

| Wrong | Correct |
|-------|---------|
| “WR 11% means bot too slow” | Structure: dead max_hold + lp_drop |
| Counterfactual on exit_reason | Only pre-buy fields |
| Enforce hazard without buy logs | Ship `gate_audit_fields` first, re-collect |
| Restart paper overwriting paper_ev2 | New log name for each experiment |
