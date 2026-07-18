# Phase2: executable-quote paper measurement

## Goal

让 paper 的触发、估值、MFE/MAE、partial 退出共用 **当前剩余 token 的全量可执行 sell quote**。  
修完之前：**禁止**用 paper 结论比较 TP 8 vs 12、adff vs 7a23/417c 分批、或「max_hold 破坏 alpha」。

## Problem (verified in code)

| 现状 | 后果 |
|---|---|
| `_paper_price_exit` 用 token-info **price** 触发 | 触达的是屏幕价，不是可执行收益 |
| `_paper_close_position` 用 sell **quote** 算 PnL | 触发源 ≠ 估值源 → TP 标签却净亏可发生 |
| 任一 TP 触发即全仓平 | 无法测 7a23/417c 分批 / runner / trail |
| 入场 sell-quote 检查约 **50%** 尺寸 | 与 100% 紧急退出不一致 |
| quote 失败曾可记 -100% 或 mark price | 假 PnL |

## Requirements

### R1 — 统一 executable return

每个 mon tick，对 `remaining_tokens` 请求 sell quote：

```text
executable_return = full_exit_quote_eth / remaining_cost_basis - 1
```

TP / hard SL / trailing 激活与回撤 / MFE / MAE **全部**基于该序列。

### R2 — Position state machine (paper)

仓位 meta 至少：

```text
initial_tokens
remaining_tokens
remaining_cost_basis   # ETH
realized_eth
tp1_filled, tp2_filled, tp3_filled  # bool or sold_ratio
peak_executable_return
entry_full_exit_quote_eth  # optional baseline
last_quote_ok
unpriced_streak
```

### R3 — Partial fills

当 `tpN_pct` 触发：

- 卖 `remaining_tokens * (tpN_pct/100)` 对应数量（或按配置比例）  
- 累加 `realized_eth`，扣减 `remaining_tokens` 与成本基础  
- **禁止**默认 100% 清仓，除非 profile 为 hf_full 且 tp1_pct=100  

Trailing：仅对剩余仓位；HWM = peak executable_return。

### R4 — Quote failure policy

- 不把失败自动记 -buy_eth  
- 不用 info price 假装可成交（可 log 参考，但不驱动 PnL）  
- `unpriced_interval` 事件；连续失败 → `route_risk` hazard 状态（可先只 log）  

### R5 — Inventory conservation

每笔生命周期结束：

```text
initial_tokens ≈ sum(sold_tokens) + remaining_tokens
```

误差必须为 0（整数 wei 级）。Self-check 强制。

### R6 — Entry quote ladder (prep for hazard)

`pre_entry_gate` 记录（不必全部 hard-reject 于本任务）：

```text
sell_quote_25 / 50 / 100 / stress_200 of planned size
full_exit_roundtrip_loss estimate
```

至少 **log**；100% stress hard-reject 可留给 Phase3，但 API 形状本任务定好。

### R7 — Event schema

```text
paper_quote_tick  — token, remaining, out_eth, exec_ret, peak
paper_partial_exit — tag tp1/tp2/…, sold_tokens, realized_delta, remaining
paper_exit — final (unchanged name ok) with quote_ok, exec path
```

## Acceptance Criteria

- [ ] paper TP 触发条件改为 executable_return 阈值（映射现有 tp1/tp2/tp3 百分比）  
- [ ] adff `8:100` 仍可全清；`7a23` 配置下可出现 partial 后剩余 >0 再二次退出  
- [ ] fixture/self-check：mock quote 序列 → 断言 partial 与库存守恒  
- [ ] 文档「禁止结论清单」更新：测量完成后哪些结论解禁  
- [ ] 旧 price 触发路径删除或 behind dead flag（默认关）  

## Non-goals

- 完美模拟 MEV/排队  
- Live condition-order 与 paper 字节级一致（方向一致即可）  
- 完成 hazard 拒绝规则  

## Success / fail signals

- **Success:** 不再出现「tp1 标签 + 大额净亏」除非 quote 明确恶化且被记录  
- **Fail:** 仍用 snap price 决定 exit reason  
