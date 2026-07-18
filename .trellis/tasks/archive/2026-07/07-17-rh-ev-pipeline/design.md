# Design: EV pipeline parent

## Order

```
[1] Opportunity set funnel + shadow collector
        ↓ (full candidate stream exists)
[2] Executable-quote paper (partial + inventory)
        ↓ (MFE/MAE/EV/labels trustworthy)
[3] lp_drop entry hazard filters + OOS report
```

## Shared log philosophy

- JSONL append-only, one event type per line  
- Fields stable; missing = explicit null, never silent 0 for risk fields  
- Paths via env: `RH_SNIPER_LOG`, optional `RH_SNIPER_SCAN_LOG` for high-volume scan lines  

## Code touch map (expected)

| Area | Files |
|---|---|
| Funnel | `engine.py` `fetch_candidates` / main loop gate section |
| Paper measurement | `engine.py` `_paper_price_exit` / `_paper_close_position` / `monitor_positions` / `buy` dry path |
| Hazard | `engine.py` `pre_entry_gate` + new helpers; CLI flags |
| Ops | `run_paper_100.sh`, optional `run_shadow_collect.sh` |
| Docs | `docs/HANDOFF_…`, short README pointer |

## Non-goals for design

- Changing adff/7a23/417c economic defaults mid-pipeline except flags needed for experiments  
- Server-side GMGN filter perfection (use if easy; not blocker)  
