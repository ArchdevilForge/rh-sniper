# Design: opportunity-set funnel

## Approach (minimal)

1. In `fetch_candidates`, after sort, attach `client_rank` (0-based).  
2. Main loop: when iterating cands, log every cand once per tick as `scan_candidate` (or batch write).  
3. Mark `was_selected_for_gate` only when `pre_entry_gate` is called.  
4. On early `break` after buy, remaining cands in that tick get `not_selected_reason=bought_break` if we still want completeness — **optional cost**. Prefer: log all cands at start of gate phase with selected flags filled after loop.  

### Preferred sequence per gate tick

```
cands = fetch_candidates()
log all as scan_candidate (selected=false, reason=pending)
for tok in cands:
  if skip: update reason; continue
  if checked >= max_gates: mark rest beyond_max_gates; break
  gate...
  mark selected=true / result
  if buy: mark remaining bought_break; break
flush scan log
```

To avoid rewriting, use two-phase in-memory list then write once.

## Config

```python
scan_log_enabled: bool = True
scan_log_path: via RH_SNIPER_SCAN_LOG
shadow_collect: bool = False  # forces no buy / no paper positions
```

## Files

- `rh_sniper/engine.py` — logging hooks  
- `rh_sniper/cli.py` — `--shadow-collect`, maybe `--no-scan-log`  
- `scripts/coverage_report.py` or `rh_sniper/coverage.py`  
- `run_shadow_collect.sh`  

## Risk

Scan volume high → disk. Mitigation: default compact fields; rotate by day in path hint; document.
