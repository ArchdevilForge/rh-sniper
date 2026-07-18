# Phase3: lp_drop entry hazard filters

## Goal

在入场前降低  

`P(lp_drop within 60s | accepted)`  

并降低 lp_drop 亏损金额；**不要求**消灭同块原子 rug。  
硬依赖 Phase2：标签与「过滤是否伤害非 rug EV」必须用 executable-quote 度量。

## Problem

paper100 中 ~94 笔 lp_drop 贡献约 **-0.0146 ETH**（约总亏损 3/4）。  
当前主要靠 `lp_drop_pct` **出场**救火；入场只有静态 min_liq / top10 等点估计。

## Requirements

### R1 — Labels（shadow / offline）

对每个通过基础 route 的候选，观察入场后 30/60/120s：

```text
y30, y60, y120 ∈ {0,1}
```

正例需满足 **至少两项**（防 API 抖动）：

- liq 连续 ≥2 快照下降超阈值  
- 全仓 sell quote 深度同步恶化  
- 可退出价值相对入场骤降  
- （可选）链上池余额/LP 减少 — 若成本高可二期  

### R2 — Pre-entry features

#### A. Liquidity dynamics (5–15s, 3–5 snaps)

Log + optional reject：

- slope, max single drop, n_down_snaps, liq/mc path  
- 「价涨但可退出深度降」标志  

初始可调规则（必须 OOS 校准，不锁死）：

```text
reject if any snap drop >8%
or 10s slope < -0.5%/s
or ≥2 of 3 snaps down
```

#### B. Depth ladder（复用 Phase2 API）

Hard reject 候选阈值（起步，可 flag 化）：

```text
full_exit_roundtrip_loss > 5%
or impact_100 - impact_50 > 4%
or two quotes differ > 5%
or stress_200 missing
```

#### C. Pool/creator fields

From trenches/token security when present：

```text
rug_ratio, bundler, insider, private_vault, top70_sniper,
creator_balance, creator_created_count / graduation ratio, holders
```

**缺失值单独特征**，禁止当 0。

### R3 — Modes

- `hazard_mode=off|shadow|enforce`  
  - shadow：只打标/记分，不拒绝  
  - enforce：拒绝并 `reason=hazard:*`  

### R4 — Experiment protocol

- 时间切分：前 N 天定规则，后 M 天验证；**禁止**同日 token 随机拆分  
- 分 LP 报告（virtuals / bankr / …）  
- 并行 A/B：同候选流，A=无 hazard，B=hazard（shadow 评分即可）  

### R5 — Success metrics（同时满足）

1. `lp_drop within 60s` 发生率 ↓ ≥50%（enforce vs baseline，OOS）  
2. lp_drop 亏损金额 ↓ ≥50%  
3. 保留 ≥30%–50% 原始候选（或 gate 通过量）  
4. 被拒绝组 lp_drop 率 **显著高于** 接受组  
5. 非 lp_drop 交易 EV 不明显恶化（阈值：下降不超过 20%）  

### R6 — First ship combo（文档要求的最小集）

> 完整候选日志（Phase1）+ 统一 executable-quote paper（Phase2）+ **10s liquidity/depth shadow observation**

本任务交付 shadow observation + 可切换 enforce 的规则钩子 + 报告脚本。

## Acceptance Criteria

- [ ] `hazard_mode` CLI 可用；shadow 默认安全  
- [ ] 入场前 multi-snap liq + depth ladder 写入日志  
- [ ] offline 报告：按日 y60 rate accept vs reject  
- [ ] fixture 证明：模拟下降 liq 序列 → hazard reject  
- [ ] handoff 更新：Phase3 状态与「仍不能声称消灭 rug」  

## Non-goals

- 训练 ML 模型  
- 重新开放 bankr 实盘  
- 用 WR 作为成功主指标  

## Dependencies

- **Blocked by** `07-17-exec-quote-paper` for EV side-effect measurement  
- Prefers `07-17-opp-set-funnel` scan log for denominator stability  

## Success / fail signals

- **Success:** 拒绝组 y60 ≫ 接受组 y60，且接受组成交量未塌到噪声  
- **Fail:** 只是少做交易，条件 lp_drop 概率不降  
