# paper_ev2 offline buckets — results

> Generated: 2026-07-18  
> Script: `scripts/paper_ev2_buckets.py`  
> Source: `data/paper_ev2/trades.paper_ev2.jsonl` (from rn2)  
> Handoff rules: `docs/HANDOFF_PAPER_EV2_DILEMMA.md`

## Reproduce baseline

| | handoff (~207) | this join (209) |
|---|---:|---:|
| WR | 11.1% | 11.0% |
| net ETH | -0.0078 | **-0.0079** |
| PF | 0.41 | **0.40** |
| TP / lp_drop / max_hold | 17 / 73 / 106 | 17 / 74 / 107 |

Match is good (2 more closed trades since handoff snapshot).

```bash
python3 scripts/paper_ev2_buckets.py data/paper_ev2/trades.paper_ev2.jsonl
```

## No look-ahead field list

**Allowed as entry features (this run):**

- `age` from buy `why` (`age=NNs`)
- `mc`, `entry_liq`, `liq/mc`, `client_rank`, `lp`, `buy_eth`, `scan_ts` delta if derived carefully

**Forbidden as historical entry gates:**

- `paper_exit.reason` / exit cat
- any `paper_quote_tick` (first_exec, MFE, peak)
- post-buy liq drop

**Diagnostic only (reported, not gated):** max_hold MFE from ticks.

---

## Table 1 — Age segments (most important)

| age | n | WR | EV/笔 | PF | TP% | lp_drop% | max_hold% | late EV (n) |
| --- | -: | -: | ---: | -: | --: | -------: | --------: | ---: |
| **30–45** | 48 | **31.2%** | -1.8e-5 | **0.84** | 22.9 | 33.3 | 33.3 | -4.6e-5 (24) |
| 45–60 | 18 | 5.6% | -8.8e-5 | 0.05 | 5.6 | 50.0 | 27.8 | -8.4e-5 (9) |
| 60–75 | 110 | 5.5% | -3.8e-5 | 0.15 | 3.6 | 36.4 | 57.3 | -4.9e-5 (55) |
| 75–90 | 33 | 3.0% | -3.9e-5 | 0.09 | 3.0 | 27.3 | 69.7 | -3.9e-5 (17) |

### Combined (pre-registered contrast)

| age | n | WR | EV/笔 | PF | TP% | lp_drop% | max_hold% | late EV |
| --- | -: | -: | ---: | -: | --: | -------: | --------: | ---: |
| **30–60** | 66 | 24.2% | -3.7e-5 | **0.65** | 18.2 | 37.9 | 31.8 | **-5.6e-5** |
| **60–90** | 143 | 4.9% | -3.8e-5 | **0.13** | 3.5 | 34.3 | 60.1 | -4.7e-5 |

### Answers to handoff questions

1. **30–60 本轮是否仍正 EV / 接近 PF≥1？**  
   **否。** PF=0.65，EV=-3.7e-5，后半段 EV 更差（-5.6e-5）。

2. **60–90 是否贡献大部分亏损？**  
   **金额上是**（net -0.0055 vs 30–60 的 -0.0024），因 **n 大**（143 vs 66）。  
   **单笔 EV 几乎一样**（-3.8e-5 vs -3.7e-5）。60–90 更差的是 **PF/WR/TP 率**，不是「唯一有毒桶」。

3. **删掉 60–90 后 30–60 是否仍 PF≪1？**  
   **是。** PF 0.65，且 late 仍负。

4. **旧 virtuals+age30–60 反事实？**  
   **本轮不支持。** 更细看：仅 **30–45** 接近打平（PF 0.84），**45–60 极毒但 n=18**；合并 30–60 被 45–60 与波动拖累。后半段 30–45 仍负 → **不能**声称 OOS 正 EV。

---

## Table 2 — Entry quality (equal-frequency quartiles)

### entry MC

| bucket | n | WR | EV | PF | TP% | lp_drop% | max_hold% | late EV |
| --- | -: | -: | ---: | -: | --: | -------: | --------: | ---: |
| Q1 ≤5462 | 52 | 3.8 | -2.9e-5 | 0.20 | 3.8 | 13.5 | **80.8** | -2.9e-5 |
| Q2 | 52 | 9.6 | -1.5e-5 | 0.58 | 5.8 | 23.1 | 71.2 | -0.4e-5 |
| Q3 | 53 | 7.5 | -2.4e-5 | 0.58 | 5.7 | **56.6** | 32.1 | +1.1e-5 |
| Q4 ≥6428 | 52 | **23.1** | **-8.3e-5** | 0.32 | 17.3 | 48.1 | 21.2 | **-1.7e-4** |

高 MC：更高 TP **也**更高尾亏（PF 仍差）。无单调可砍正门。

### entry liq

| bucket | n | WR | EV | PF | notes |
| --- | -: | -: | ---: | -: | --- |
| Q1 liq≲36 | 52 | 3.8 | -2.5e-5 | 0.10 | **92% max_hold** 死盘 |
| Q2 | 52 | 11.5 | **-0.3e-5** | **0.90** | 最不糟；late EV ≈0 |
| Q3 | 53 | 5.7 | -5.4e-5 | 0.08 | **62% lp_drop** |
| Q4 liq≳749 | 52 | 23.1 | -6.9e-5 | 0.48 | TP 高但 lp_drop 56% |

**模式：** 极低 liq → 死盘；中高 liq → 撤池。Q2 接近打平但 **未过 PF1**，且非预注册单变量，需 OOS 再验。

### liq/MC

与 liq 同构（相关）：Q1 死盘，Q3–Q4 高 lp_drop。

### client_rank

| rank bucket | n | WR | EV | PF | TP% |
| --- | -: | -: | ---: | -: | --: |
| rank 0 (best client order) | 128 | **17.2** | -3.5e-5 | 0.54 | 12.5 |
| rank ~1 | 40 | 2.5 | -4.4e-5 | 0.07 | 2.5 |
| rank ≥1 tail | 41 | **0.0** | -4.1e-5 | 0.00 | **0.0** |

**rank>0 几乎无 TP。** 候选：`client_rank==0 only` 作为**未来**单变量（本任务未预注册跑 paper）。即使 rank0，PF 仍 0.54。

---

## Table 3 — Hazard shadow

| check | result |
|---|---|
| buy 事件 hazard_liq / hazard_depth / sell_ladder | **字段不存在** |
| reject 上 hazard_* | **4433/4433 null** |
| reject 原因 | 100% 在 hazard 之前（low_liq/top10/mc） |
| gate_result 含 hazard | **0** |

**结论：本轮无法估计** \(P(\mathrm{lp\_drop}\mid\mathrm{hazard})\)。  
shadow 在 `pre_entry_gate` 内对 **通过 cheap filter 的币**会算 hazard，但 **buy 成功路径没把 snap 的 hazard 写入 trades jsonl**；失败路径又几乎到不了 hazard。

**要启用 hazard 决策，先修日志（最小）：**  
在 `event=buy`（及 shadow_signal）落盘：`hazard_liq`, `hazard_depth`, `liq_path`, `sell_ladder` 摘要。  
然后再跑一段 shadow-only 或当前 paper 累积 n 后重做 Table 3。

---

## Diagnostic — max_hold MFE（禁止当 entry gate）

| | |
|---|---|
| n | 107 |
| p50 MFE | **0.0%** |
| p90 MFE | **0.0%** |
| MFE ∈ [3,8) | 1 |
| MFE ≥ 8 | 0 |

→ **死盘，不是「差一点到 TP8」。禁止降 TP。** 缩短 hold 也不减少已发生的买入摩擦。

---

## Time stability

| slice | n | WR | EV | PF |
| --- | -: | -: | ---: | -: |
| early half | 104 | 10.6 | -2.6e-5 | 0.42 |
| late half | 105 | 11.4 | **-5.0e-5** | 0.39 |

后半段更差 → 无「越跑越好」；任何门控必须看 late EV。

---

## Pre-registered decision tree result

```text
age 分段完成
│
├─ 30–60 PF=0.65 ≪ 1，late EV 负
│    → 旧反事实失效
│    → 禁止启动 paper_ev3_age60 作为「恢复正 EV」实验
│      （注：60–90 更烂，但砍掉也救不回 30–60）
│
└─ hazard shadow
     → 本 log 无预测力可测（缺字段）
     → 不 enforce
     → 不改 TP/hold
     → 下一步：修 buy 日志 和/或 改机会集排序 + 入场前动量确认
```

### 额外观察（未预注册，仅假设候选）

| 假设 | 证据 | 动作 |
|---|---|---|
| age **30–45 only** | PF 0.84，仍微负 late | 可**另开**预注册对照，不得与多旋钮一起改 |
| client_rank==0 only | rank>0 TP%=0 | 同上，单变量 paper |
| liq Q2 窗 | PF 0.90 | 弱；易过拟合，先当研究 |

### 明确禁止（本结论下）

- 降 TP / 缩 max_hold / 改 lp_drop%  
- 调快 poll  
- live  
- 用买后 MFE/首 mon 做历史 entry 反事实  
- 多旋钮同时改  

### 推荐下一工程刀（按序）

1. **P0 日志**：buy（+reject 若过了 timing）落盘 hazard_* / sell_ladder 摘要 → 否则 Phase3 shadow 不可审计。  
2. **P1 机会集**：限制 `client_rank==0` 或提高 rank0 权重；评估 trenches 排序是否该变。  
3. **P1 入场前动量确认**（买前多快照，不是买后）：与 hazard liq path 合流。  
4. 仅当用户要试：单变量 `fresh-max-age=45` 或 `fresh 30–45` 对照（预期改善 WR，**不保证** PF≥1）。

---

## One-line verdict

> **当前 `virtuals+age30–90+TP8/60s` 负 EV 成立；30–60 救不回；hazard 本 run 不可测；下一刀是 buy 日志 + 机会集/买前确认，不是 TP/hold，也不是 age60「复辟」。**
