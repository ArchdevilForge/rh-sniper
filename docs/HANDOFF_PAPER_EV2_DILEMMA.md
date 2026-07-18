# Handoff: paper_ev2 当前困境

> 日期：2026-07-18 · 环境：`rn2` · 代码基线：`9d1f304`（本地另有未提交改动）  
> 关联长文：`docs/HANDOFF_WINRATE_WALLET_ALIGNMENT.md`（策略对标 / 成功标准 / 钱包画像）  
> 本文：**事实 → 收紧结论 → 离线方法（禁 look-ahead）→ 决策树**。下一会话直接按 §6 产出结论表，不要先改 cmdline。

---

## 0. 收紧后的结论（开场就念）

**207+ 笔已经足够否定「当前 `virtuals + age30–90 + TP8/60s` 具有明显正 EV」这一版本，但还不足以证明应改 TP 或 hold。下一步必须找出一个买入前可观测、样本外仍有效的负 EV 子集。**

### 离线分桶结论（2026-07-18，任务 `07-18-paper-ev2-offline-buckets`）

完整表：`.trellis/tasks/07-18-paper-ev2-offline-buckets/research/offline_buckets.md`  
复跑：`python3 scripts/paper_ev2_buckets.py data/paper_ev2/trades.paper_ev2.jsonl`

| 决策项 | 结果 |
|---|---|
| 30–60 是否接近 PF≥1？ | **否** PF=0.65，late EV 仍负 |
| 60–90 是否主亏？ | 金额大（n=143），**单笔 EV 与 30–60 几乎相同** |
| **paper_ev3_age60** | **禁止启动**（砍 60–90 救不回 30–60） |
| hazard shadow 区分力 | **本 log 不可测**（buy 未落盘 hazard_*；reject 全在 hazard 前） |
| **paper_ev3_hazard enforce** | **不做**直到日志修好并重采 |
| 降 TP / 缩 hold | **禁止**（max_hold MFE p50=0%，不是差 2 个点） |
| 相对最好 age 切片 | **30–45** PF=0.84 仍微负 late — 仅可另开单变量对照 |
| 其它线索 | `client_rank>0` TP%=0；极低 liq→死盘，高 liq→lp_drop |

**下一工程刀：** (1) ~~buy 事件落盘 hazard_*/sell_ladder~~ **已实现** `gate_audit_fields` → buy/shadow/reject（需部署 rn2 后重采才能测区分力）(2) 机会集/rank0 或买前动量确认 — 不是 age60 复辟。

补充：

- 主因**不是** bot 跑太慢（`poll=1s`，mon ~6s；能涨时 4–5s 已 TP）。
- `max_hold` 51.2% + `lp_drop` 35.3% = **86.5%** 交易落在死盘或撤池分布。
- `tp1 + hard_sl` 仅 28 笔，按分类合计约 **+0.0021 ETH、PF≈1.7** → 有右尾，但买错了分布。
- `exit_reason` 是**事后结果**，不是入场规则；禁止用它直接当 filter 反事实。
- Phase1–3 测量管线已完成；**本轮 paper 未证实过滤正 EV**。

---

## 1. 现在机器上在跑什么

| 项 | 值 |
|---|---|
| 主机 | `rn2` → `racknerd-cccd74a` |
| 进程 | `rh-sniper run -p adff --paper-positions`（PID 以服务器为准） |
| 工作目录 | `/root/Coding/rh-sniper` |
| 实时日志 | `/root/logs/rh-sniper.paper_ev2.out` |
| state / trades | `state.paper_ev2.json` / `trades.paper_ev2.jsonl` / `scans.paper_ev2.jsonl` |
| 启动 | 2026-07-17 14:09 左右 |
| 模式 | **dry-run paper**，非 live |

### 关键参数

```
-p adff --paper-positions
--bankroll-eth 0.053 --buy-eth 0.001
--poll 1.0 --gate-every 1 --max-gates 12
--min-mc 1000 --max-mc 50000 --min-liq 30
--fresh-min-age 30 --fresh-max-age 90
--max-top10 0.70 --max-top10-fresh 0.95
--soft-retry-sec 2 --no-unindexed-liq
--allowed-lps virtuals --no-fake-heat
--lp-drop-pct 25 --min-liq-hold 0
--max-hold-sec 60 --hard-sl 15 --tp-ladder 8:100
--scan-log --hazard-mode shadow
```

旧日志已停更：`paper.out` / `paper100.out` / `paper_ev.out`。旧 pid 勿信。

---

## 2. 核心数字（paper_ev2，~2026-07-18 01:50）

| 指标 | 数值 |
|---|---|
| 成交 | **207** |
| 胜 / 负 | 23 / 184 |
| 胜率 | **11.1%** |
| 毛利 / 毛亏 | +0.0053 / -0.0131 ETH |
| **净盈亏** | **-0.0078 ETH**（约 -14.7% bankroll） |
| 均笔 | -3.8e-5 ETH |
| Profit factor | **0.41** |
| 日志 `day_pnl` | **不可靠**；以 `[paper_exit] total≈` / jsonl 为准 |

### 出场结构

| 原因 | n | 占比 | 贡献 PnL |
|---|---:|---:|---:|
| max_hold (~60s) | 106 | **51.2%** | -0.0030 ETH |
| lp_drop | 73 | **35.3%** | **-0.0068 ETH（金额主亏）** |
| tp1 | 17 | 8.2% | **+0.0051 ETH（几乎全部盈利）** |
| hard_sl | 11 | 5.3% | -0.0030 ETH |
| **max_hold + lp_drop** | **179** | **86.5%** | 主导亏损 |
| tp1 + hard_sl（方向性） | 28 | 13.5% | 约 +0.0021，PF≈1.7 |

含义：

> 少数有动量的标的能覆盖正常方向性止损；**绝大多数买入不属于这个动量分布，或属于撤池分布。**

极值：RACE +160.9% / REPIN +65% / AGORA +47%；SONIC·HAN 近全灭、GRID hard_sl -85%。

---

## 3. 已读懂的机制（不是处方）

### 3.1 不是速度问题

- mon p50≈6s；BORU/RACE 在 4–5s 触 TP。
- 「首 mon drop≥25%」≈24% 交易：只能估**可避免损失上限**，**不能**当历史 entry gate（look-ahead）。
- 去掉瞬间 rug 后 WR 仍 ~11% → 加速不救胜率。

### 3.2 概率排序（当前判断）

1. **选币 / 状态确认不足（最高）** — 86.5% 进 dead-or-rug。
2. **旧 virtuals+age30–60 反事实过拟合或 regime 漂移（次高）** — 样本内 ~28.7% WR → 本轮 11.1%；差太大，除非 60–90 极端有毒，否则不像「只是 age 上沿配错」。
3. **paper friction 放大 max_hold** — 可能，但非全部。若 106 笔 max_hold 全当 0 盈亏：  
   `-0.0078 + 0.0030 = -0.0048 ETH` 仍负；金额杀手仍是 lp_drop + hard_sl。
4. **TP/hold 错配** — 存在可能，**当前不是首要可证伪假设**。

### 3.3 与旧反事实的落差

长文：virtuals + age 30–60 样本内 WR≈28%、微正 EV。  
本轮：virtuals + **30–90** + 207 笔 → WR 11%、PF 0.41。  
**必须用 age 分段表回答是否只是 60–90 有毒**（见 §4.1）。

---

## 4. 离线报告怎么做（下一会话主产物）

**只用下单前已知字段。** 禁止：

- `exit_reason` 当入场规则
- 买后首 mon / 任意 mon 结果
- 买后最高/最低价、买后 liq drop
- 最终持仓时间

数据源优先：`trades.paper_ev2.jsonl`（+ 买入时刻 scan/shadow 字段若有）。日志只作交叉验证。

每个分桶统一七项：

```text
n / WR / EV/笔 / PF / TP率 / lp_drop率 / max_hold率
```

结论总表列：

```text
规则/分桶 | n | 保留率 | WR | EV/笔 | PF | TP率 | lp_drop率 | max_hold率 | 后半段EV
```

筛选「可上线 gate」时要同时满足：n≥30（最好≥50）、条件概率有单调或相邻桶同向、**时间后半段仍成立**。不要只挑收益最高的一格。

### 4.1 第一张必做表：age 分段（最重要）

历史正切片是 **30–60s**，当前实验扩到 **30–90s**。不要只比两个大桶：

| age | n | WR | EV/笔 | PF | lp_drop率 | max_hold率 | TP率 | 后半段EV |
| --- | -: | -: | ---: | -: | -------: | --------: | --: | ---: |
| 30–45 | | | | | | | | |
| 45–60 | | | | | | | | |
| 60–75 | | | | | | | | |
| 75–90 | | | | | | | | |

必须回答：

1. 本轮 30–60 是否仍正 EV / 接近 PF≥1？
2. 60–90 是否贡献大部分亏损？
3. 删掉 60–90 后，30–60 是否仍 PF≪1？

若 30–60 本轮也明显负 EV → **旧反事实判定为 regime-specific 或过拟合**，不是简单 age 上沿配置错误；**不要**因此启动 age60 对照。

### 4.2 第二张表：入场质量（等频分桶）

对**买入前**字段等频分桶（勿手拍阈值）：

- entry MC、entry liquidity、liq/MC、top10
- 买入 round-trip friction、100% sell quote impact
- creator / bundler / insider / rug 相关字段
- hazard shadow score 或各子规则
- trenches category、原始 rank、首次看见→买入延迟

找的是稳定负 EV 子集，不是曲线拟合最优格。

### 4.3 第三张表：hazard shadow 的真正价值

回答：

\[
P(\mathrm{lp\_drop}\mid\mathrm{hazard}=1)
\quad vs \quad
P(\mathrm{lp\_drop}\mid\mathrm{hazard}=0)
\]

并报告：precision、recall、candidate rejection rate、被拒绝组 EV、保留组 EV、TP 误杀率、**后半段是否同向**。

值得 enforce 的最低近似门槛：

- lp_drop recall ≥40%
- 危险组 lp_drop rate ≥ 安全组 2×
- 拒绝候选 ≲50%
- TP 误杀率明显低于 lp_drop 捕获率
- 时间后半段方向不反转

否则 hazard 只是「看起来复杂的减频器」。

### 4.4 若要动 TP/hold：先有分布，否则禁止

**不建议先降 TP。** 17 个 TP 贡献几乎全部利润；降 TP 可能截断 RACE/REPIN/AGORA 右尾。  
大量 max_hold 停在 `exec≈-2.6%`——不是差 2 个点到 8%，是**根本没启动**。降到 5% 救不了它们。

先算 max_hold 组的 **executable MFE**（买后、用可成交 quote）：

| max_hold 的 MFE | 解释 |
| --- | --- |
| 大多 <0% | 标的选择失败，降 TP 无效 |
| 集中在 +3%～+7% | 才考虑 TP 可能过高 |
| 曾超过 +8% 但没触发 | 测量/轮询触发 bug |

**不建议先缩短 hold。** 若亏损主要在买入瞬间摩擦，30s vs 60s 不减少单笔亏。仅当：30s 后条件 EV 显著负、30–60s 新 TP 很少、且 30s 卖价明显优于 60s 时，才缩短。

**不建议先改 lp_drop 阈值。** 15/25/35% 只改「何时确认池已坏」，不改「为何选中该池」。先查：触发前最后正常快照→drop 的时延；多阈值模拟退出价值；liq drop 与 full-exit quote 是否同步。quote 先崩则调阈值无效。

---

## 5. 唯一允许的对照实验（预注册，且有门槛）

在分桶出来之前，**最合理的预注册单变量**是：

```text
A: paper_ev2          原参数，fresh age 30–90（基线，勿覆盖）
B: paper_ev3_age60    仅改 fresh-max-age 90 → 60
```

原因：直接检验旧反事实；不改执行/退出；不伤 TP 右尾机制；入场可观测；结论好解释。

**仅当离线同时满足才启动 B：**

- 60–90 EV 明显低于 30–60
- 60–90 的 lp_drop 或 max_hold 率明显更高
- 30–60 至少接近 PF 1（不是同样 ~0.4）
- 时间后半段同向

若 30–60 本轮仍明显负 EV → **禁止 age60 实验**。改查 hazard：

```text
B: paper_ev3_hazard
仅 hazard-mode shadow → enforce，其余冻结
```

若 hazard 也无样本外区分力：

> 当前公共 trenches + virtuals **没有可验证 alpha**；应改机会集排序或增加**入场前**动量确认——**仍不是先改 TP/hold**。

一次只改一个变量；新日志文件；其他参数/时段结构一致。

---

## 6. 决策树（严格执行）

```text
先分 age 30–45 / 45–60 / 60–75 / 75–90
│
├─ 30–60 接近或高于 PF 1，且 60–90 明显有毒
│    → 单变量跑 paper_ev3_age60
│
├─ 30–60 也明显负 EV
│    → 旧反事实失效，不再调 age
│    → 检查 hazard shadow（§4.3）
│         ├─ 可接受误杀下捕获 lp_drop → paper_ev3_hazard（shadow→enforce）
│         └─ 无预测力 → 不改 TP/hold
│              → 改候选排序或入场前动量确认
│
└─ 并行：入场质量等频分桶（§4.2）找可砍负 EV 子集
```

**当前最重要产物不是新 cmdline，而是 §4 的结论表。**

---

## 7. 明确不要做

| 不要 | 除非 |
|---|---|
| 调快 poll 当优化 | 有证据 mon 漏掉 ≥8% MFE |
| 先降 TP / 缩 hold / 改 lp_drop% | 先有 MFE 或阈值时序表 |
| 多旋钮一起改 | — |
| 用买后首 mon drop 做历史 entry 反事实 | 仅可报「损失上限」 |
| 负 EV 上 live | 样本外 EV/笔>0 且 PF>1.1（见长文） |
| 重做 Phase1–3 脚手架 | — |

---

## 8. 已完成工作（Trellis，勿重复）

`07-17-rh-ev-pipeline` 及子任务均 completed：

| Phase | 内容 |
|---|---|
| 1 | opportunity-set funnel + shadow collector |
| 2 | executable-quote paper measurement |
| 3 | lp_drop entry hazard filters |

提交：`45cfe64` soft-reject retry · `044e805` first-wave gates · `9d1f304` EV filters。  
本地未提交：`cli.py` / `engine.py` / `run_paper_100.sh` 等 → 续工前 `git diff` 对齐 rn2。

---

## 9. 常用命令

```bash
ssh rn2 'ps aux | grep "[r]h-sniper"'
ssh rn2 'tail -f /root/logs/rh-sniper.paper_ev2.out'
ssh rn2 'ls -la /root/Coding/rh-sniper/trades.paper_ev2.jsonl \
  /root/Coding/rh-sniper/state.paper_ev2.json \
  /root/Coding/rh-sniper/scans.paper_ev2.jsonl'
```

离线优先拉 jsonl 到本地再分桶，避免在日志上用事后字段。

---

## 10. 一句话

> **209 笔否定了当前参数版正 EV；30–60 救不回；hazard 不可测；禁止 age60 / enforce / 动 TP。**  
> 下一刀：buy 日志补 hazard 字段 + 机会集/买前确认。详见 task research `offline_buckets.md`。
