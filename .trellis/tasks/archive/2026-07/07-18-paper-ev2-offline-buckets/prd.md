# paper_ev2 offline buckets + gate decision

## Goal

对 `paper_ev2`（virtuals + age30–90 + TP8/60s + hazard shadow）做**无 look-ahead** 离线分桶，产出一张结论表，决定下一刀是：

- `paper_ev3_age60`（仅 `fresh-max-age` 90→60），或  
- `paper_ev3_hazard`（shadow→enforce），或  
- **两者都不做**：承认当前入口无边，改候选排序/入场前动量确认  

**不改 TP / hold / lp_drop 阈值，不开 live。**

## Context

- Handoff：`docs/HANDOFF_PAPER_EV2_DILEMMA.md`  
- 数据：`rn2:/root/Coding/rh-sniper/trades.paper_ev2.jsonl`（+ scans/state）  
- 基线：~207 笔，WR 11.1%，净 -0.0078 ETH，PF 0.41  
- 旧反事实：virtuals∩age30–60 样本内曾似正 EV；本轮 30–90 未兑现  

## Requirements

### R1 — 禁 look-ahead

入场规则/反事实**只用买入前字段**。禁止用：

- `exit_reason` 当 filter  
- 买后 mon / paper_quote_tick  
- 买后 MFE/MAE、买后 liq drop  

「首 mon drop≥25%」仅可报损失上限，**不得**当历史 entry gate。

### R2 — 三张表

1. **age 分段**：30–45 / 45–60 / 60–75 / 75–90（七项指标 + 后半段 EV）  
2. **入场质量等频分桶**：mc、liq、liq/mc、rank、friction（及可得的 hazard/top10 等）  
3. **hazard shadow 区分力**：P(lp_drop|h=1) vs h=0；precision/recall/拒绝率/误杀 TP/后半段  

每桶：`n / WR / EV/笔 / PF / TP率 / lp_drop率 / max_hold率`（+ 后半段 EV）

### R3 — 决策树（预注册）

```
age 分段后：
  30–60 ≈PF≥1 且 60–90 有毒 → 建议 paper_ev3_age60
  30–60 也明显负 → 旧反事实失效；查 hazard
    hazard 达标 → paper_ev3_hazard
    无预测力 → 不改 TP/hold；改机会集/动量确认
```

hazard 近似门槛：lp_drop recall≥40%；危险组率≥安全组 2×；拒绝≲50%；TP 误杀 < lp_drop 捕获；后半段同向。

### R4 — 交付物

- `research/offline_buckets.md`：三张表 + 决策  
- 更新 handoff § 决策结果指针  
- 可选：`scripts/paper_ev2_buckets.py` 可复跑  

## Acceptance Criteria

- [x] 从 jsonl 复现 trades 数与净 EV 量级（与 handoff 一致）  
- [x] age 四段表填完，并明确回答：30–60 是否仍接近 PF1；60–90 是否主亏  
- [x] 至少一张入场质量分桶表（等频，n 标注）  
- [x] hazard：若字段缺失则**显式写「无法评估 / 缺字段」**，不得假装有区分力  
- [x] 最终三选一建议 + 禁止项列表（不降 TP、不缩 hold、不调 poll）  
- [x] 无 look-ahead 的字段清单写在 research 里  

结果：`research/offline_buckets.md` · 脚本：`scripts/paper_ev2_buckets.py`  
决策：**不 age60、不 enforce hazard、不改 TP/hold**；修 buy 日志 + 机会集/买前动量。

## Out of scope

- 改生产 cmdline / 重启 rn2 paper（除非决策明确要求且用户确认）  
- 动 TP、max_hold、lp_drop_pct  
- live 资金  
- 重做 Phase1–3  

## Dependencies

- 只读 rn2 paper_ev2 日志  
- 代码改动仅限分析脚本（可选）  
