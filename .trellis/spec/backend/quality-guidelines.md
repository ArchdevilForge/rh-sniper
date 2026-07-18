# Quality Guidelines

---

## Forbidden patterns

| Pattern | Why |
|---------|-----|
| Live trading while paper PF < 1 and EV/trade < 0 | Capital protection |
| Changing TP + hold + age + hazard in one experiment | Uninterpretable |
| Entry filter using `exit_reason` or post-buy MFE | Look-ahead bias |
| Buy log without hazard audit keys when hazard_mode ≠ off | Phase3 unmeasurable (paper_ev2 lesson) |
| Overwriting `trades.paper_ev2.jsonl` mid-experiment | Breaks OOS time split |
| Treating stdout `day_pnl` as bankroll truth | Use jsonl `pnl_eth_est` sum |
| New dependency for offline tables | stdlib only (`scripts/paper_ev2_buckets.py`) |

---

## Required patterns

- Single-variable paper renames: `paper_ev3_age60`, `paper_ev3_hazard`, …  
- Soft reject for transient gate failures; hard seen-ban for structural fails  
- Executable-quote paper exits (Phase2) — TP/SL/MFE same quote path  
- hazard_mode: `off` \| `shadow` \| `enforce` only  

---

## Self-checks before claim “done”

```bash
python3 scripts/test_paper_exec.py
python3 scripts/hazard_report.py --self-check
# optional offline
python3 scripts/paper_ev2_buckets.py path/to/trades.jsonl
```
