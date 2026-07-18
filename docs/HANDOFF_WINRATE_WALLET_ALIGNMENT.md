# Handoff: 提高胜率 + 贴近高 PnL 钱包打法

> 用途：把这份文档原样发给「链上 meme / sniper / 量化策略」方向的人（研究员、逆向交易员、同赛道 bot 作者、顾问）。  
> 目标不是求交易信号，而是求：**入口选择、出场结构、过滤规则、如何正确对标钱包** 的可执行意见。  
> 日期：2026-07-17 · 代码 commit：`9d1f304` · 环境：`rn2` paper

---

## 0. 30 秒电梯稿（开场就念这段）

我在 Robinhood chain 上做 **策略复刻型 meme sniper**（不是跟单 copy-trade）。  
参考了 3 个高 PnL 钱包风格（`adff` 秒级 scalp / `7a23` probe+分批 / `417c` 更大仓+长 hold），用 GMGN API 扫 trench、过滤后买卖。

**现状：**

- 宽松 paper（paper100，~23h，911 笔）：胜率 **15.4%**，累计 **-0.0193 ETH（约 -36% bankroll）**
- 反事实：只做 `virtuals` 且入场 age 30–60s → 样本内可到 **WR≈28.7%、单笔 EV≈+4.2e-5 ETH**
- 已按此收紧上线 paper_ev：virtuals-only + age 30–90s + hold 60s + TP 8%；跑 ~2h 仅 9 笔，仍全负或接近，**n 太小未验证**

**我要求助的核心问题：**

1. 对标钱包时，我该对齐 **哪些可观察特征**，而不是瞎抄参数？  
2. 在 Robinhood / GMGN 数据延迟下，**真实可达成的胜率区间**大概是多少？  
3. 我现在是「摩擦+rug 主导的负 EV scalp」——要贴近钱包，应优先改 **入场、出场，还是选币/选池**？  
4. 请帮我做一次 **pre-mortem**：按我现在的架构，最可能永远打不过那些钱包的 3 个原因是什么？

---

## 1. 我是谁 / 我想要什么 / 我不要什么

| | 内容 |
|---|---|
| **我** | 自己写并运维 bot（Python + `gmgn-cli`），能改代码、能跑 paper/live、能拉钱包成交 |
| **目标 A** | 提高 **可验证胜率**（不是口头“感觉准”） |
| **目标 B** | 行为上更贴近那几个高 PnL 钱包的 **可复现打法**（风格复刻，不是地址镜像） |
| **成功标准（建议对方一起改；旧版 WR≥25% 或 EV>0 已废弃）** | 主 KPI=**样本外净 EV/笔>0** + profit factor>1.1；WR 只作解释变量。并与目标钱包在 ≤3 个对标指标上收敛（见 §16 看板） |
| **不要** | 内幕盘口、代持喊单、保证收益、纯情绪鼓励 |
| **可提供** | 完整 trade log（jsonl）、state、服务器访问（只读）、代码仓库、参数表 |
| **约束** | API 有 401/429；执行有延迟；paper≠live；资金小（paper bankroll 0.053 ETH） |

---

## 2. 系统一句话架构

```
GMGN trenches (new/completed/near_completion)
  → LP allowlist + age/MC/liq/top10/honeypot/creator/fake_heat
  → buy quote + sell quote must exist
  → optional probe
  → buy (fixed size or risk%)
  → exits: TP ladder / hard SL / max_hold / lp_drop / creator_dump
```

- **链**：Robinhood  
- **数据/下单**：GMGN OpenAPI via `gmgn-cli`  
- **代码**：`rh-sniper`（本地 `/home/xeron/Coding/Robinhood`，服务器 `rn2:/root/Coding/rh-sniper`）  
- **模式**：默认 dry-run；paper 用 `--paper-positions` 模拟持仓与 quote 退出  
- **原则**：Strategy replica — **not copy-trading**

---

## 3. 对标钱包（我理解的画像）

> 说明：以下是 README/代码注释里的逆向画像，**不是**官方标签。完整地址在私有笔记/GMGN；文档里用前缀。

| Profile | 风格标签 | 观察到的卖出习惯（逆向） | 我们编码的默认 |
|---|---|---|---|
| **adff**（荒大宝-style） | 高频、薄利、固定小仓 | 中位约 **1.1–1.3x**，常 **100% 清仓** | 原：TP+12% 全清 / hold 25s / SL15；**现 EV 版**：TP+8% / hold 60s / age 30–90s |
| **7a23**（0xDavid-style） | probe + 中仓 + 分批 | 先卖 ~30%，再阶梯，留 runner | TP 25/50/100 卖 30/30/25 + trail；hold 300s；默认 probe 0.001 |
| **417c** | 更大仓 + 长 hold | 先卖 ~25%，多段卖，可持 runner 数小时 | TP 30/80/150 卖 25/30/25 + trail；hold 3600s |

### 我认为钱包「可能真有边」的来源（待请教验证）

1. **选池/选 launchpad 的隐性质量**（我们可能选错分布）  
2. **入场时机**（不是越早越好；我们 paper 显示 age 0–15s 最亏）  
3. **出场结构**（他们触达 TP 的路径 vs 我们大量 max_hold 摩擦离场）  
4. **不交易的纪律**（拒单率/日交易上限/时段）  
5. **信息或执行优势**（更低延迟、私有信号、人工干预）——若是这个，纯 bot 复制会有上限

---

## 4. 当前参数（EV 版 paper，正在跑）

启动：`run_paper_100.sh` → state `state.paper_ev.json` / log `trades.paper_ev.jsonl`

| 参数 | 值 | 为什么这样设 |
|---|---|---|
| profile | adff | 先打高频 scalp 这条线 |
| allowed_lps | **virtuals only** | paper100：virtuals +EV，bankr 深 -EV |
| fresh-min-age / max | **30 / 90 s** | 30–60s 桶 WR 最高；0–15s 最差 |
| buy-eth | 0.001 | ~$1/笔，堆样本量 |
| bankroll | 0.053 ETH | ~$100 paper |
| max-hold | **60 s** | 原 25s 几乎打不到 TP |
| tp-ladder | **8:100** | 降 TP 提高触达 |
| hard-sl | 15% | 保持 adff 紧止损 |
| lp-drop | 25% | 防抽池 |
| unindexed liq | **关** | 与 lp_drop 亏损相关 |
| fake-heat | 关（paper 脚本） | 旧脚本为吞吐量关掉；可讨论是否应开 |
| reheat | 关 | adff first-wave only |

代码默认 SAFE_LP（无 bankr）：`pons, noxa, trench, virtuals, flap`  
CLI 可覆盖：`--allowed-lps`、`--fresh-min-age`、`--tp-ladder` 等。

---

## 5. 证据：paper 实验结果（请基于此批评，勿空谈）

### 5.1 paper100（宽松闸门，高成交）

- 时长 ≈ **23h**（2026-07-16 11:39 → 07-17 11:01）  
- **911 买 / 911 卖**  
- **WR 15.4%** · 累计 **PnL -0.019303 ETH** · bankroll **-36.4%**  
- 单笔 EV ≈ **-2.12e-5 ETH**  
- 盈亏比 avgW/|avgL| ≈ **3.33** → 打平约需 WR **≈23%**  
- 出场：绝大多数 **max_hold_***；TP 极少；**lp_drop ~94 笔吃掉约 -0.0146 ETH（≈总亏损 3/4）**

**分层（关键）：**

| 切片 | n | WR | EV/笔 | 总 PnL |
|---|---:|---:|---:|---:|
| 全样本 | 911 | 15.4% | -2.1e-5 | -0.0193 |
| virtuals | 747 | 17.7% | **+1.1e-5** | **+0.0081** |
| bankr | 152 | 3.9% | **-1.7e-4** | **-0.0259** |
| age 0–15s | 274 | 6.9% | -4.3e-5 | -0.0117 |
| age 30–60s | 250 | **25.2%** | **+1.7e-5** | +0.0043 |
| virtuals ∩ age30–60 | 216 | **28.7%** | **+4.2e-5** | +0.0091 |

**摩擦地板：** max_hold 亏损中位 ≈ **-2.6%/笔**（相对 0.001 名义）。  
无信息交易的期望先扣这笔，再谈“选币 alpha”。

### 5.2 paper_ev（收紧后，进行中）

- 时长 ≈ **2h+**（07-17 11:25 起）  
- **9 买 / 9 卖**，空仓  
- **WR 0%** · PnL ≈ **-0.00041 ETH（约 -$0.41）** · bankroll ≈ **-0.8%**  
- 出场混有 max_hold 与 lp_drop；出现过至少 1 次 tp1  
- 含义：**过滤有效减少了自杀式成交量**，但尚未积累足够 +EV 样本；不能因为 9 笔全负就否定反事实

### 5.3 Live

- 曾被挡：`insufficient_native bal≈0.00056 need>=0.02`  
- 尚未有可信 live 样本

---

## 6. 我已经试过 / 排除过的方向

| 已做 | 结果 |
|---|---|
| 复制 adff：25s hold + 12% 全清 | TP 几乎摸不到 → 退化成付费超时离场 |
| 放松过滤堆成交（paper100） | 样本大，但稳定 -EV |
| 禁 bankr + age 窗 + 降 TP + 加 hold | 样本内反事实转正；样本外 n 不足 |
| 401 冷却 + paper quote 失败 mark-to-market | 避免脏 PnL / 刷接口 |
| 纯提高交易频率 | 负 EV 下只会加速亏 |

**刻意没做（想听你是否该做）：**

- 跟单目标钱包每一笔  
- ML 打分 / 复杂特征  
- 同时改 10 个参数无 A/B  
- 在 bankr 上加大 size“搏回归”

---

## 7. 我卡住的具体问题（请逐条答）

### Q1. 对标方法论

要把 bot 贴近 `adff/7a23/417c`，你建议对齐哪些 **可观测统计量**？  
例如（请增删排序）：

- 入场时 token age / MC / liq / top10 / launchpad  
- 持仓时间分布  
- 首次减仓的倍数与仓位比例  
- 日交易次数、同时持仓数  
- 胜率 vs 盈亏比 vs 利润因子  
- 时段（UTC/CN）  
- 是否做 reheat / 是否碰某 LP  

**请给：最小指标看板（≤8 项）+ 每项的目标区间或对比方法。**

### Q2. 胜率该不该作为主 KPI？

在 meme scalp 里，钱包可能是 **低胜率 + 高盈亏比**。  
我现在 WR 15%、盈亏比 3.3，数学上打平要 ~23% WR。  

请判断：

- 我应该优先抬 WR，还是抬 **单笔 EV / 利润因子**？  
- 对 adff 这种“薄利全清”，合理 WR 锚点大概在哪？  
- 若对标钱包真实 WR 也只有 ~20%，我该如何定义“贴近”？

### Q3. 入场：早 vs 晚

数据说 age 0–15s 最亏、30–60s 最好。  
但“抢新”叙事很强，钱包也可能更早。

请回答：

- 在 GMGN 索引延迟下，**paper 的 age 和钱包真实入场 age 是否可比**？  
- 若钱包更早仍赚钱，缺的是延迟、池质量，还是卖点不同？  
- 你会如何设计实验区分「太早」vs「选错盘」？

### Q4. 出场结构

adff 路径上 TP 触达率极低，大量 max_hold。  
可选：降 TP / 加 hold / 分批（改走 7a23）/ 波动率自适应。

请给：

- 在「中位持仓只有几十秒」的市场上，你倾向哪套出场？  
- max_hold 应看作硬风控还是 alpha 破坏者？  
- lp_drop 占亏损大头时，入场侧怎么防，而不是只靠出场救？

### Q5. 选池 / LP

virtuals 样本内唯一明显 +EV；bankr 是毒。  

请给：

- 只做 virtuals 是否过度拟合最近 regime？  
- 如何低成本监控 LP 边的漂移（何时重新开放 bankr/noxa）？  
- 除 LP 名外，还有哪些 **池级特征** 值得做硬过滤？

### Q6. Paper 可信度

Paper 用 quote 估 PnL，存在：

- 买到的价不是真实冲击价  
- 卖 quote 401/失败时我们已改 mark-to-market  
- 无排队/MEV/部分成交  

请评估：我的 paper 结论 **哪些可以信、哪些必须 live 小仓才信**？  
最小 live 验证协议怎么设计（仓位、天数、停机条件）？

### Q7. 若你只能改 3 件事

假设目标是 2 周内看到样本外 paper EV>0，且行为更像目标钱包：  
**只允许改 3 个杠杆**，你会改哪 3 个？为什么？预期如何度量？

---

## 8. 请用这个格式回复我（降低各说各话）

```text
1) 诊断（1 段）：我现在主要死在 ____，不是 ____。
2) 对标看板：指标列表 + 如何从钱包交易流算出来。
3) 优先改动 Top3：每项 = 改什么 / 怎么验 / 成功标准 / 失败信号。
4) 不要做的清单：3–5 条。
5) 胜率预期：在我的延迟与数据条件下，合理 WR 与 EV 区间。
6) 开放问题：你还需要我补哪些原始数据。
```

---

## 9. 我能立刻提供的附件清单

请对方勾选需要的：

- [ ] `trades.paper100.jsonl`（911 笔全量，~6MB）  
- [ ] `trades.paper_ev.jsonl`（收紧后，持续增长）  
- [ ] `state.paper100.json` / `state.paper_ev.json`  
- [ ] 服务器 stdout：`/root/logs/rh-sniper.paper_ev.out`  
- [ ] 代码：`rh_sniper/engine.py`（gate/exit/profile）  
- [ ] 目标钱包在 GMGN 的近期成交导出（若我有权限拉）  
- [ ] 按 LP / age / hour / exit_reason 的汇总 CSV（可再生成）  
- [ ] 只读 SSH 或屏幕共享看 live 扫描

**生成汇总的一键命令（服务器）：**

```bash
cd /root/Coding/rh-sniper
export RH_SNIPER_LOG=trades.paper_ev.jsonl RH_SNIPER_STATE=state.paper_ev.json
.venv/bin/rh-sniper stats
# 分层可用 python 读 jsonl（已有脚本逻辑，可再导出 csv）
```

---

## 10. 风险与诚实边界（写给对方，也写给我自己）

1. **钱包 PnL 有生存者偏差**；公开高光地址可能含人工、私有流、或不可持续 regime。  
2. **策略复刻 ≠ 同分布成交**；我们扫的是 trenches 公共面。  
3. **提高胜率可能降低期望**（拒掉波动大的真赢家）。要同时看 EV。  
4. **样本内反事实不是样本外保证**；virtuals∩30–60 可能过拟合这两天。  
5. Meme 可归零；任何建议默认 **研究/paper 优先，live 极小仓**。

---

## 11. 可选：发给不同角色时的侧重点

### 11.1 链上 meme 老手 / 交易员

请多看 §3、§7 Q3–Q5。重点问：

- 你自己做 RH 新盘时，**绝对不买**的 5 条规则是什么？  
- 你会不会在 age 30–60s 才进？为什么？  
- 看到 lp 开始掉，你的手脚顺序是什么？

### 11.2 量化 / 统计交易

请多看 §5、§7 Q2/Q6/Q7。重点问：

- 在往返摩擦 ~2.5–5% 时，选币 alpha 的最小可检测效应要多大？  
- 如何做 walk-forward，避免我用同一 911 笔调参自嗨？  
- WR 与 EV 的联合置信区间怎么报？

### 11.3 Bot / 执行工程师

请多看 §2、§4、§7 Q6。重点问：

- GMGN quote 与真实 swap 的偏差你怎么建模？  
- 401/索引延迟下，软拒绝与硬拒绝怎么分层？  
- 条件单 TP 与本地轮询 exit，谁更接近钱包成交路径？

### 11.4 认识目标钱包本人或圈子（若有）

不要问“私有信号是什么”。问可公开方法论：

- 你更在意 **不亏的纪律** 还是 **抓爆的尾部**？  
- 单笔目标 R 倍数与最大持仓时间？  
- 哪些盘你看一眼就跳过？

---

## 12. 开场消息模板（可直接复制）

### 短版（聊天/推特）

```text
在做 RH chain meme sniper（策略复刻，非跟单）。
paper 911 笔 WR15% / -36% bankroll；切片后 virtuals+age30-60s 样本内可转正。
想请教：对标高PnL钱包该对齐哪些统计量？在GMGN延迟下合理胜率锚点？
入场早vs晚、出场max_hold vs TP，你更改哪边？
有完整jsonl和参数表，可发 handoff 文档。
```

### 长版（邮件/深度咨询）

```text
你好，我在 Robinhood 上运行自研 sniper bot（GMGN API），目标是复刻几类高 PnL 钱包的可观察打法，并提高可验证胜率/期望。

已完成两轮 paper：
1) 宽松高频：911 笔，WR 15.4%，-0.019 ETH
2) 按分层收紧（virtuals + age 窗 + 更长 hold + 更低 TP）：成交量骤降，样本外还在积累

我不是来要信号的，而是希望你基于附件数据批评：
- 我对钱包的画像是否歪
- 当前负EV主因是选币、时机还是出场
- 若只改 3 件事，优先顺序是什么

附件：HANDOFF 文档 + 可选 trade log。
你方便的话按文档第 8 节格式回复即可。
```

### 语音/会议 15 分钟议程

1. 2 min：电梯稿 + 我不要什么  
2. 4 min：paper 分层图（LP / age / 出场）  
3. 5 min：对方诊断 + Top3 改动  
4. 3 min：对标看板与下次数据约定  
5. 1 min：下一步实验（A/B 与停机条件）

---

## 13. 内部决策备忘（给自己，也可给顾问看）

**当前信念（带置信度）：**

| 信念 | 置信 |
|---|---|
| bankr 在本配置下 -EV | 高 |
| age 0–15s -EV | 高 |
| virtuals ∩ 中等 age 有边 | 中（缺样本外） |
| 25s@+12% 结构性触达失败 | 高 |
| paper 可直接外推 live | 低 |
| 再堆频率能救策略 | 极低 |

**两周实验协议（建议与顾问对齐后执行）：**

1. 冻结规则集 A（当前 EV 版）跑 paper ≥3 个活跃日  
2. 并行规则集 B（仅改 1 个杠杆，例如 hold 90s 或开 fake-heat）  
3. 每日记录：成交数、WR、EV/笔、lp_drop 损失占比、401 率  
4. 达标：A 或 B 样本外 EV/笔>0 且 lp_drop 损失占比下降  
5. 再谈 live：单笔 ≤0.001，日亏停机 ≤ bankroll 10%

---

## 14. 变更日志

| 日期 | 事件 |
|---|---|
| 2026-07-16 | paper100 启动（宽松 adff） |
| 2026-07-17 | paper100 止损分析；确认 bankr/age0-15/max_hold 问题 |
| 2026-07-17 | commit `9d1f304` EV filters；paper_ev 上线 |
| 2026-07-17 | 本文档创建 |

---

## 14b. Trellis 任务（实现队列）

已在仓库初始化 Trellis，按 **机会集 → 测量 → hazard** 建树：

| 任务 | 路径 | 状态 |
|---|---|---|
| 父 | `.trellis/tasks/07-17-rh-ev-pipeline/` | planning |
| Phase1 机会集漏斗 | `.trellis/tasks/07-17-opp-set-funnel/` | **completed** |
| Phase2 executable-quote paper | `.trellis/tasks/07-17-exec-quote-paper/` | **completed** |
| Phase3 lp_drop hazard | `.trellis/tasks/07-17-lp-drop-hazard/` | **completed**（默认 shadow） |

### 实现摘要（2026-07-17）

- `scan_candidate` → `RH_SNIPER_SCAN_LOG` / `scans.*.jsonl`
- `--shadow-collect` 只 gate+log 不下单；`run_shadow_collect.sh`
- paper 退出改为 **executable sell-quote** TP/SL + partial inventory
- `--hazard-mode off|shadow|enforce`：入场前 multi-snap liq + 25/50/100/200 sell ladder
- 脚本：`scripts/coverage_report.py`、`scripts/hazard_report.py`、`scripts/test_paper_exec.py`
- rn2 当前：`paper_ev2`（state/trades/scans.paper_ev2.*，hazard=shadow）


## 15. 联系与路径（按需填）

- 代码 commit：`9d1f304`（**可能尚未 push 到公开 origin**；公开仓最新或仍是 `044e805`）  
- 服务器：`rn2`（SSH host alias）  
- Paper 日志：`/root/Coding/rh-sniper/trades.paper_ev.jsonl`  
- 旧对照：`trades.paper100.jsonl`  
- 文档路径：`docs/HANDOFF_WINRATE_WALLET_ALIGNMENT.md`

---

## 16. 外部审阅吸收（2026-07-17）— 请优先读

> 以下为独立审阅意见，经本地 `9d1f304` 代码核对后吸收。**这比“再调 TP/hold”更优先。**

### 16.1 修正后的诊断（替换旧叙事）

旧叙事：「TP 太高 / hold 太短 → 胜率低 → 负 EV」。  
**更准确：**

1. **机会集选择失真** — bot 与钱包很可能不在同一候选宇宙  
2. **rug / lp_drop 在入场前未被识别** — 亏损结构像 hazard，不是方向猜错  
3. **paper 与钱包成交路径不可比** — 测量系统先坏，参数对齐无意义

### 16.2 代码结构事实（本地 `9d1f304` 已核）

| 事实 | 代码位置/行为 | 含义 |
|---|---|---|
| trenches 每类 `--limit 50` | `fetch_candidates` | 公共截断列表，不是全市场 |
| 客户端排序 | fresh 优先 → vol 降序 → age | **隐含选币函数**，文档以前没当策略写 |
| gate 后第一笔 buy 就 `break` | 主循环 | 不是“所有过过滤的都做”，是“排序后第一个过的” |
| paper TP 用 **token-info price** 触发 | `_paper_price_exit` | 触发源 |
| paper PnL 用 **sell quote** | `_paper_close_position` | 估值源 ≠ 触发源 → “标了 TP 仍净亏”可正常发生 |
| paper 无 partial / runner / trail 状态 | 任一 TP 触发即全仓 quote 平 | **paper 不能诚实测 7a23/417c**；live 才走 condition-orders 分批 |
| sell-quote 入场检查是 **50% 仓** | `pre_entry_gate` | 紧急/全平是 100% → 风险检查与真实退出尺寸不一致 |
| paper 日亏写入 `day_realized_est` | `_paper_close_position` 同步累加 USD | 审阅说“halt 没接上”**对 9d1f304 不成立**；但 paper_ev 脚本把 `--daily-loss-usd 999999` 等于关掉 |

### 16.3 Pre-mortem：永远打不过钱包的 3 个高概率原因

1. **机会集不同** — 钱包看链上事件/私有列表/人工；bot 看 GMGN 截断 trenches + 本地排序  
2. **执行层不同** — RH 按到 sequencer 先后排序、不能靠更高费插队；专用 RPC/直连 vs GMGN REST 索引延迟不是同一层  
3. **复制的是成交后统计，不是决策时信息集** — 混有人工、跨地址、幸存者偏差

### 16.4 对标看板（≤8 项，取代“抄参数”）

用 **pool-open 链上时间 + 交易回执** 建钱包 lifecycle；不要拿 GMGN UI 的 token age 当共同时间轴。

| # | 指标 | 怎么算 | 收敛标准（建议） |
|---|---|---|---|
| 1 | 机会集与拒单漏斗 | 每池：trenches 看见？排名？gate？拒绝原因？钱包是否成交？ | 先报「钱包成交中 bot 可观察率」；**<70% 禁止谈参数对齐** |
| 2 | LP/入场状态分布 | LP、log(MC)、log(liq)、liq/MC、top10、rug/bundler/insider | 类别差 ≤10pp；连续量中位/IQR 差 ≤20% |
| 3 | 链上入场延迟 | `tx inclusion − pool-open`；另记 GMGN first-seen 延迟 | 比 p25/p50/p75，不比均值 |
| 4 | 标准化仓位 | 买额/池 liq、买额/权益、冲击 | 中位与 p90 在钱包 0.5–2× |
| 5 | 首卖三元组 | 首卖延迟、首卖净倍数、首次卖出比例 | 时间/倍数中位差 ≤20%；比例差 ≤10pp |
| 6 | 库存生存曲线 | 买后 30/60/120/300s 剩余仓位；完全清仓时间 | 比整条曲线，不只比 max_hold |
| 7 | 活跃纪律 | 时/日交易数、同时持仓、间隔、时段 | 频率 0.5–2×；时段分布接近 |
| 8 | 净结果与风险来源 | 净 EV、PF、WR、W/L、p5/CVaR、lp_drop 率与亏损占比 | EV>0、PF>1.1；lp_drop 亏损占比 <25%；单笔赢家 <总利润 30% |

钱包 lot 用明确 FIFO 或加权成本；排除转账/跨地址补仓/未闭合库存。

### 16.5 数学：+8% 全清下 WR 不是主 KPI

摩擦中位约 **2.6%** 时，gross TP 8% → 正常赢家净约 **~5.4%**。打平 WR：

| 净平均亏损 | 打平 WR |
|---:|---:|
| 2.6% | 32.5% |
| 5% | 48.1% |
| 10% | 64.9% |
| 17.6%（15%SL+摩擦） | 76.5% |

含义：

- **adff 薄利全清**：经济上自洽的 WR 更像 **35%–60%** 起看（取决于亏损能否压在 2.6–5% 而非 SL/rug）  
- **7a23/417c 尾部**：WR 20–35% 可成立，但需净赢亏比 ~2–4× 且 **runner 被真实模拟**  
- 样本内 28.7% WR 套到 +8% 全清，若净均亏 >~2.2%，**仍不够正 EV**  
- 旧 911 笔的 3.33 盈亏比 **不能**外推到新出场结构

`virtuals∩30–60`：n=216，WR 28.7% 的 Wilson 95% 约 **23–35%**；paper_ev 0/9 的 95% 上界仍约 **34%** → **既不能否定也不能支持**。且 RH 主网很新，LP/参与者 regime 可能快变；同批数据搜最优切片 = 选择偏差风险。

### 16.6 优先改动 Top3（覆盖“再调参数”冲动）

#### Top1 — 先修测量系统，再调策略

- TP/SL/MFE/MAE 一律基于 **当前剩余仓位的全量可执行卖出 quote**，禁止 price 触发、quote 结算  
- 入场前记 25%/50%/100% 卖出 quote 冲击曲线（现只验 ~50%）  
- paper 实现 true partial、剩余数量、分段 realized、runner、trail HWM  
- 时间戳全链路：pool-open / GMGN first-seen / gate / buy quote / submit / receipt / exit trigger / sell quote / receipt  

**成功：** 库存守恒；无“无解释 TP 却净亏”；live matched 后 quote→fill 中位偏差 <1%、p90 <3%。  
**失败：** 大量 mark-to-market 顶替 quote，或触发源≠估值源依旧。

#### Top2 — lp_drop 改成入场 hazard，不是只靠出场救

- virtuals-only 可暂留作隔离，但其他 LP 继续 **shadow quote**（别断采样）  
- 硬特征建议：入场前 5–15s 多快照拒下降 liq；全仓 + 2× stress sell quote；rug/bundler/insider/creator 等池级字段  
- 尽量用 GMGN 服务端过滤稳定机会集，而不是拉 50 再吃隐含排序  

**成功：** lp_drop 发生率与亏损金额各降 ≥50%；其亏损占总亏损 <25%；非 lp_drop 子集 EV 不因过滤掉 >20%。  
**失败：** 成交变少但 lp_drop 条件概率不降 → 只是少做，不是识别 rug。

#### Top3 — 用钱包「首卖 hazard」定出场，别用 bot 样本猜 TP

- 一次只对齐 **adff**；paper 能 partial 前 **禁止** 当真测 7a23/417c  
- 从钱包真实成交重建首卖时间 / 净倍数 / 清仓比例  
- TP 用净可执行收益；max_hold 用钱包首卖/清仓分布与 time-to-MFE 的**预先声明分位**，禁止看完最近结果再从 25→60→90  
- 固定选币、同候选并行 A=钱包风格 full-clear vs B=当前 8%/60s；按日 walk-forward  

**成功：** 首卖三元组距离降 ≥30%；max_hold 出场 <40% 且净 EV>0；抬 WR 时 PF/EV 不降。  
**失败：** 赢家 MFE 多在 max_hold 后，或多数交易从未覆盖摩擦 → 问题仍在选池。

### 16.7 不要做的清单（更新）

1. 不要把 `virtuals∩30–60` 叫样本外边 — 只是待检假设  
2. 不要用「WR≥25% 或 EV>0」联合标准 — +8% 全清下 25% WR 仍可能深负 EV  
3. paper 不能正确分批前不要切 7a23/417c 做结论  
4. 不要因 bankr 偶发赢家重开或加仓 — 用 shadow cohort + 预先声明重开规则  
5. live 验证不要用 10% bankroll 日亏当停机 — 执行校准阶段过宽；paper_ev 的 999999 等于无日停机  
6. 不要在同一 911 笔上继续网格搜参当“发现”

### 16.8 两周决策标准（替换旧成功标准）

- OOS 净 EV > 0  
- 按活跃日分组后，**多数日期** EV>0  
- bootstrap **80% 下界** >0  
- 无单日/单笔贡献 > 总利润 50%  
- lp_drop 亏损占比 <25%

**Live 先验证执行，不验证 alpha：**

- 单仓；≤ research bankroll 0.25–0.5%（若最小额更高则继续 paper）  
- 先 20–30 笔 probe/小额 matched fills 测 quote→fill  
- 通过后再冻结规则 ≥50 笔 / ≥5 活跃日；alpha 判断最好 100–200 笔  
- 日亏停机 ~2%，累计 ~5%；任意无法退出/策略单缺失且本地退出失败 → 立刻停  
- 每笔 live 旁路同时间 paper 单，只比 matched trades

### 16.9 请顾问/协作者优先索要的数据（更新）

优先级从高到低：

1. `trades.paper100.jsonl` + `trades.paper_ev.jsonl`  
2. `9d1f304` 完整 patch / 推送 branch（公开仓可能仍是旧版）  
3. **全部候选与拒绝漏斗**（每轮排名、category、未 gate 的候选）— 只有成交日志不够  
4. 持仓期全仓 sell quote 序列 → executable MFE/MAE、time-to-MFE  
5. 目标钱包近期 tx：hash/block/logIndex/token/ETH/route/gas/转账  
6. `gmgn-cli` 版本、401/429 率、quote/swap 原始样例  
7. 每 token：pool-open tx、GMGN first-seen、首次可买/可卖 quote 时间  
8. 历史上试过的全部参数组合清单（修正多重试验）

**最先处理：paper100 全量 + 候选/拒绝漏斗 + 9d1f304 patch。**  这三项先判断 virtuals/age 是真选池边，还是截断列表+排序+paper 估值制造的表象。

### 16.10 给下一位读者的一句话

> 在修好「机会集日志 + executable-quote 测量 + paper partial」之前，继续拧 TP/hold/age 属于高方差娱乐；主战场是漏斗与 hazard，不是胜率口号。

---

*文档结束。发给别人时：先贴 §0 + §16 摘要 + §12 模板，再附全文；大数据按需另传。*
