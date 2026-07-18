# RH sniper: opportunity set → measurement → hazard

## Goal

把反馈栈按固定顺序落地，使 paper/对标钱包结论可辩护：

1. **机会集** — 能量化「钱包成交中 bot 在买入前能检查到的比例」  
2. **测量** — paper 的 TP/SL/MFE/MAE 与 PnL 共用 **剩余仓位全量 sell quote**，并支持 partial  
3. **hazard** — 用入场前流动性动态 + stress quote + 池/创建者字段降低 `lp_drop` 条件发生率  

**顺序不可反转。** 机会集不清则参数对标无意义；测量错误则 EV/出场结论无意义。

## Context

- 代码：`rh_sniper/engine.py` / `cli.py`，commit `9d1f304`（可能未 push）  
- 证据：`docs/HANDOFF_WINRATE_WALLET_ALIGNMENT.md` §5 / §16  
- paper100：911 笔 WR 15.4% / -0.0193 ETH；切片 `virtuals∩age30-60` 仅样本内关联  
- paper_ev：收紧后成交骤降，n 小，不能当 OOS 证明  
- 公开结构：trenches `--limit 50` + 客户端排序 + 每 tick 有限 gate + 买一笔 break  

## Requirements

1. 父任务只协调顺序与验收；实现落在三个子任务。  
2. 子任务完成顺序：**opp-set-funnel → exec-quote-paper → lp-drop-hazard**。  
3. 每个子任务必须有：日志 schema、可跑的 self-check / 小测试、成功/失败信号。  
4. 不在本父任务内：live 真金加仓、ML 打分、跟单地址镜像。  
5. 参数拧 TP/hold/age **禁止**作为本栈完成前的主线工作。

## Acceptance Criteria

- [ ] 子任务 1 完成：可计算 wallet/bot coverage 漏斗（至少 S1–S4 可 offline join）  
- [ ] 子任务 2 完成：paper 库存守恒；TP/SL 触发与估值同源 executable quote；partial 状态可跑  
- [ ] 子任务 3 完成：hazard 规则可 shadow/enforce；有时间切分 OOS 报告模板  
- [ ] handoff §16.9 所需「候选/拒绝漏斗」日志在生产 paper 路径默认开启  
- [ ] README 或 docs 增加「禁止结论清单」指针（测量未完成前）  

## Out of scope

- 保证正 EV / 保证胜率  
- 重写整个 GMGN 客户端  
- 同时对齐 7a23/417c 的 paper 结论（依赖子任务 2）  

## Dependencies

| 子任务 | 依赖 |
|---|---|
| `07-17-opp-set-funnel` | 无 |
| `07-17-exec-quote-paper` | 建议在 funnel 日志已开后并行开发，但 **验收对标** 依赖 funnel 样本 |
| `07-17-lp-drop-hazard` | **硬依赖** exec-quote-paper（标签与 EV 副作用必须用 executable quote） |

## Notes

- 主 KPI 仍是净 EV / PF / lp_drop 亏损占比；WR 只作解释变量。  
- paper_ev 的 `daily-loss-usd 999999` 等于关掉日停机；hazard/测量完成后应恢复合理 halt。  
