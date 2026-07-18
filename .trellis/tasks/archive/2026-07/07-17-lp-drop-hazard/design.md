# Design: lp_drop hazard

## Placement

`pre_entry_gate` after basic LP/MC/age, **before or after** buy quote:

Recommended order:

1. cheap static filters  
2. multi-snap liq observation (adds latency — only for candidates that passed cheap filters)  
3. buy quote  
4. sell ladder 25/50/100/200  
5. creator/rug fields  
6. return ok  

## Latency budget

- 3 snaps × ~1–2s = 3–6s extra per candidate  
- Compensate: lower max_gates or only observe when age in window  

## Config

```python
hazard_mode: str = "off"  # off|shadow|enforce
hazard_snap_n: int = 3
hazard_snap_gap_sec: float = 2.0
hazard_max_single_drop_pct: float = 8.0
hazard_max_full_exit_loss_pct: float = 5.0
# ...
```

## Reporting

`scripts/hazard_report.py` joins:

- gate accepts/rejects with hazard features  
- later mon events / paper exits with lp_drop  

## Note on atomic rugs

Document explicitly: same-block pull cannot be prevented by REST polling; success is conditional rate reduction.
