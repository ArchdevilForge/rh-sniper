# Implement: lp_drop hazard

## Steps

1. Confirm Phase2 quote ladder helpers exist; reuse.  
2. Add snap loop helper `observe_liq_path(addr, n, gap)`.  
3. Wire `hazard_mode` in CLI + Config.  
4. Shadow: always log features; enforce: return `hazard:...`  
5. Label builder offline from mon logs or dedicated post-entry observer (can be paper mon).  
6. `hazard_report.py` + fixture.  
7. OOS protocol section in docs.  

## Verify

```bash
rh-sniper run --once -p adff --hazard-mode shadow
python scripts/hazard_report.py --log trades....jsonl
```

## Done when

PRD metrics can be computed on at least one multi-day log window (even if rates not yet green).
