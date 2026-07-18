# Design: executable-quote paper

## Core loop change in `monitor_positions` (paper branch)

```
for each position:
  sq = quote(token -> NATIVE, remaining_tokens)
  if fail:
    unpriced_streak += 1
    log paper_quote_tick quote_ok=false
    continue  # or route_risk after N
  exec_ret = out_eth / remaining_cost_basis - 1
  peak = max(peak, exec_ret)
  reason = match_exit(cfg, exec_ret, peak, held, lp_drop...)
  if partial reason:
    sell_tokens = floor(remaining * ratio)
    apply_partial(...)
  elif full reason:
    close_all(...)
```

## Mapping profile TP scales

Existing `tp1` is percent gain (e.g. 8 means +8%).  
Use: `if exec_ret * 100 >= tp1 and not tp1_filled`.

## Cost basis

On buy dry-run: `remaining_cost_basis = buy_eth`, `remaining_tokens = int(quote_out)`.  
On partial sell of fraction f:  
`realized += out_eth_for_sold`  
`remaining_cost_basis *= (1-f)` **or** reduce by pro-rata cost — pick **pro-rata cost** and document.

## Files

- `engine.py`: replace `_paper_price_exit` with `_paper_exec_exit`  
- tests: `tests/test_paper_exec.py` or script self-check with monkeypatched `quote`

## Migration

- New paper state file recommended when deploying (`state.paper_exec.json`) so old positions without remaining_tokens aren't half-migrated.  
- Or on load: if missing remaining_tokens, derive from quote_out once.
