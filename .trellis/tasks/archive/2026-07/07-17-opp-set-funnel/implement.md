# Implement: opportunity-set funnel

## Steps

1. Add `log_scan_event` + `SCAN_LOG_PATH` resolution (mirror STATE/LOG).  
2. Thread `client_rank` through candidates.  
3. Rewrite gate-tick block to collect scan rows then flush.  
4. CLI `--shadow-collect`: set `max_positions=0` or hard-skip buy; still gate.  
5. `run_shadow_collect.sh` on rn2-friendly PATH.  
6. `coverage_report.py` + fixture under `tests/` or `scripts/fixtures/`.  
7. Self-check in `if __name__` or tiny assert script.  

## Verify

```bash
# unit-ish
python scripts/coverage_report.py --fixture scripts/fixtures/coverage_mini.jsonl

# dry shadow once
RH_SNIPER_SCAN_LOG=/tmp/scans.jsonl rh-sniper run --once -p adff --shadow-collect
```

## Done when

PRD acceptance boxes checkable with evidence paths in task notes.
