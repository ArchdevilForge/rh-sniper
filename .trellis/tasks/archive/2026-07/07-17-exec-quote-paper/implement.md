# Implement: executable-quote paper

## Steps

1. Extend position dict on buy (paper) with inventory fields.  
2. Implement `_paper_sell_quote(remaining_tokens) -> (ok, out_eth, err)`.  
3. Replace price-based exit matcher.  
4. Implement `_paper_apply_partial` + full close.  
5. Log `paper_quote_tick` / partial events.  
6. Entry ladder quotes logged in `pre_entry_gate` (no hard reject yet unless free).  
7. Self-check with fake quote function.  
8. Update handoff §16.6 Top1 status notes when done.  

## Verify

```bash
python -c "from rh_sniper.engine import ..."  # inventory assert
# optional: short paper run, inspect paper_partial_exit lines
```

## Done when

PRD boxes + one recorded sample partial lifecycle in notes.
