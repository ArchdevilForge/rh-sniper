# Phase1: opportunity-set funnel + shadow collector

## Goal

能量化：**钱包买入前，bot 是否有机会检查到该 token**。  
没有完整候选日志，就无法证明「在复刻钱包」还是「活在截断列表里」。

## Problem

当前只记 buy/reject。下列情况不可区分：

- trenches API 从未返回 token  
- 返回了但被 client sort/top-N 挤掉  
- 在列表中但未轮到 `pre_entry_gate`（max_gates / 买一笔 break）  
- gate 拒绝  
- 过 gate 但未成交（仓位/时段/exposure）

## Requirements

### R1 — Scan 日志（每次 trenches 拉取）

对 `fetch_candidates` 产出的**每一个** token（或至少 top-K + 被截断计数）写 JSONL 事件，字段至少：

```text
event=scan_candidate
scan_ts, tick, category, token, symbol
server_order (enumerate within category if available)
client_rank (after local sort)
age, open_ts, create_ts, lp
mc, liq, vol_1h, swaps_1h (if present)
was_selected_for_gate: bool
not_selected_reason: null | "beyond_max_gates" | "already_seen" | "soft_cooldown" | "has_position" | "bought_break" | ...
```

高基数时允许：

- 默认写 compact scan log：`RH_SNIPER_SCAN_LOG`（默认 `scans.jsonl` 或 `scans.<mode>.jsonl`）  
- 全量字段可 `RH_SNIPER_SCAN_VERBOSE=1`

### R2 — Gate 日志增强

现有 reject/buy 保留，并保证：

```text
gate_started_ts
gate_finished_ts
client_rank
scan_ts (join key)
reason (existing)
```

### R3 — Shadow collector 模式

- CLI 或脚本：`--shadow-collect` / `run_shadow_collect.sh`  
- **不下单、不建 paper 仓**（或强制 max_positions=0）  
- 仍跑 trenches + gate 检查 + 写 scan/reject 日志  
- 可 24h 挂 rn2，与 paper_ev 并行  

### R4 — Coverage 报告脚本

离线脚本（stdlib 即可）输入：

- scan/reject/buy logs  
- 可选：钱包买入 CSV/jsonl（`wallet_buy_ts, token`）

输出漏斗：

| 层 | 指标 |
|---|---|
| S0 | 钱包买入笔数 |
| S1 | `api_seen_rate` — 买入前 scan 中出现 |
| S2 | `rank_visible_rate` — client_rank 在可 gate 深度内 |
| S3 | `gate_reached_rate` — 曾 `was_selected_for_gate` 或有 gate 事件 |
| S4 | `pass_rate` — gate ok |
| S5 | `execution_rate` — 实际 buy（shadow 下可 N/A） |

阈值解释（文档化，非硬编码失败）：

- ≥70% comparable coverage → 可谈参数对齐  
- 40–70% → 仅共同机会集条件对标  
- <40% → 主问题是数据源/排序/调度  

### R5 — 不回填幻觉

历史 paper100 **若无 scan 日志则标注不可精确补算**；不伪造 coverage。

## Acceptance Criteria

- [ ] paper/shadow 运行时产生 scan JSONL，字段满足 R1  
- [ ] gate 事件可 join 到 scan（token + 时间窗）  
- [ ] shadow 模式跑 ≥1 分钟无 buy 事件  
- [ ] `scripts/coverage_report.py`（或 `rh_sniper/tools/...`）对合成 fixture 输出漏斗表  
- [ ] 文档说明：无钱包导出时只报 bot 内漏斗（S2–S5 结构）  
- [ ] 最小 self-check：构造 3 个假 scan + 1 wallet buy → 断言 S1/S3  

## Non-goals

- 改变选币经济逻辑（除日志与 shadow 开关）  
- 计算最终 EV  
- 完整钱包链上重建（输入格式约定即可）  

## Success / fail signals

- **Success:** 能回答「过去 N 小时有多少候选从未被 gate」  
- **Fail:** 只有 reject 日志、无法区分 unseen vs unscheduled  
