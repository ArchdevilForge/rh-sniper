#!/usr/bin/env python3
"""Offline paper_ev2 buckets — entry-time fields only (no look-ahead gates).

Usage:
  python3 scripts/paper_ev2_buckets.py data/paper_ev2/trades.paper_ev2.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def cat_reason(reason: str) -> str:
    r = reason or ""
    if r.startswith("tp1"):
        return "tp"
    if r.startswith("lp_drop"):
        return "lp_drop"
    if r.startswith("max_hold"):
        return "max_hold"
    if r.startswith("hard_sl"):
        return "hard_sl"
    return "other"


def age_bucket(age: int | None) -> str | None:
    if age is None:
        return None
    if 30 <= age < 45:
        return "30-45"
    if 45 <= age < 60:
        return "45-60"
    if 60 <= age < 75:
        return "60-75"
    if 75 <= age <= 95:  # allow tiny clock skew past 90
        return "75-90"
    return "other"


def metrics(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "WR": None,
            "EV": None,
            "PF": None,
            "TP%": None,
            "lp_drop%": None,
            "max_hold%": None,
            "net": 0.0,
        }
    pnls = [r["pnl"] for r in rows]
    wins = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0)
    gl = sum(p for p in pnls if p <= 0)
    net = sum(pnls)
    cats = [r["cat"] for r in rows]
    return {
        "n": n,
        "WR": wins / n * 100,
        "EV": net / n,
        "PF": (gp / abs(gl)) if gl < 0 else (float("inf") if gp > 0 else None),
        "TP%": sum(1 for c in cats if c == "tp") / n * 100,
        "lp_drop%": sum(1 for c in cats if c == "lp_drop") / n * 100,
        "max_hold%": sum(1 for c in cats if c == "max_hold") / n * 100,
        "net": net,
    }


def fmt(m: dict) -> str:
    if m["n"] == 0:
        return f"n=0"
    pf = m["PF"]
    pf_s = "inf" if pf == float("inf") else (f"{pf:.3f}" if pf is not None else "n/a")
    return (
        f"n={m['n']:3d}  WR={m['WR']:5.1f}%  EV={m['EV']:+.6f}  PF={pf_s:>6}  "
        f"TP={m['TP%']:4.1f}%  lp_drop={m['lp_drop%']:5.1f}%  max_hold={m['max_hold%']:5.1f}%  "
        f"net={m['net']:+.6f}"
    )


def quantile_edges(vals: list[float], k: int = 4) -> list[float]:
    if not vals:
        return []
    s = sorted(vals)
    n = len(s)
    edges = []
    for i in range(1, k):
        idx = min(n - 1, max(0, int(round(i * n / k)) - 1))
        edges.append(s[idx])
    # unique monotone
    out = []
    for e in edges:
        if not out or e > out[-1]:
            out.append(e)
    return out


def assign_q(v: float, edges: list[float]) -> int:
    for i, e in enumerate(edges):
        if v <= e:
            return i
    return len(edges)


def load_trades(path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    buys, exits, ticks = [], [], []
    for line in path.open():
        o = json.loads(line)
        e = o.get("event")
        if e == "buy":
            buys.append(o)
        elif e == "paper_exit":
            exits.append(o)
        elif e == "paper_quote_tick":
            ticks.append(o)
    return buys, exits, ticks


def join_trades(buys: list[dict], exits: list[dict], ticks: list[dict]) -> list[dict]:
    # FIFO per token
    exit_q: dict[str, list[dict]] = defaultdict(list)
    for x in exits:
        exit_q[x["token"].lower()].append(x)
    tick_q: dict[str, list[dict]] = defaultdict(list)
    for t in ticks:
        tick_q[t["token"].lower()].append(t)

    rows = []
    for b in buys:
        tok = b["token"].lower()
        if not exit_q[tok]:
            continue
        x = exit_q[tok].pop(0)
        # consume ticks between buy and exit ts
        mfe = None
        first_exec = None
        tlist = tick_q[tok]
        keep = []
        for t in tlist:
            if t["ts"] < b["ts"]:
                keep.append(t)
                continue
            if t["ts"] > x["ts"]:
                keep.append(t)
                continue
            er = t.get("exec_ret_pct")
            if er is not None:
                if first_exec is None:
                    first_exec = er
                peak = t.get("peak_exec_ret")
                if peak is not None:
                    mfe = peak if mfe is None else max(mfe, peak)
                mfe = er if mfe is None else max(mfe, er)
        tick_q[tok] = keep

        m = re.search(r"age=(\d+)", b.get("why") or "")
        age = int(m.group(1)) if m else None
        mc = float(b.get("mc") or 0)
        liq = float(b.get("entry_liq") or 0)
        buy_eth = float(b.get("buy_eth") or 0.001)
        # entry friction proxy: first tick exec (POST-buy — diagnostic only, not a gate feature)
        # prefer explicit buy.age (post gate_audit_fields); fallback why=
        if b.get("age") is not None:
            try:
                age = int(b["age"])
            except (TypeError, ValueError):
                pass
        hz = bool(b.get("hazard_liq") or b.get("hazard_depth"))
        rows.append(
            {
                "symbol": b.get("symbol"),
                "token": tok,
                "ts": b["ts"],
                "age": age,
                "mc": mc,
                "liq": liq,
                "liq_mc": (liq / mc) if mc > 0 else None,
                "rank": int(b.get("client_rank") if b.get("client_rank") is not None else -1),
                "buy_eth": buy_eth,
                "pnl": float(x.get("pnl_eth_est") or 0),
                "reason": x.get("reason") or "",
                "cat": cat_reason(x.get("reason") or ""),
                "hazard": hz,
                "has_hazard_keys": ("hazard_liq" in b) or ("hazard_depth" in b),
                "first_exec": first_exec,  # diagnostic
                "mfe": mfe,  # diagnostic for max_hold / TP only
                "exit_ts": x["ts"],
            }
        )
    return rows


def half_split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    if not rows:
        return [], []
    mid = sorted(r["ts"] for r in rows)[len(rows) // 2]
    return [r for r in rows if r["ts"] < mid], [r for r in rows if r["ts"] >= mid]


def print_table(title: str, groups: dict[str, list[dict]], order: list[str] | None = None):
    print(f"\n## {title}")
    keys = order or list(groups.keys())
    for k in keys:
        rows = groups.get(k, [])
        m = metrics(rows)
        _, late = half_split(rows)
        ml = metrics(late)
        late_ev = f"{ml['EV']:+.6f}" if ml["n"] else "n/a"
        print(f"  {k:12s}  {fmt(m)}  late_EV={late_ev} (n={ml['n']})")


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/paper_ev2/trades.paper_ev2.jsonl")
    buys, exits, ticks = load_trades(path)
    rows = join_trades(buys, exits, ticks)
    print(f"source={path}")
    print(f"buys={len(buys)} exits={len(exits)} ticks={len(ticks)} joined={len(rows)}")
    m_all = metrics(rows)
    print(f"ALL  {fmt(m_all)}")
    early, late = half_split(rows)
    print(f"EARLY {fmt(metrics(early))}")
    print(f"LATE  {fmt(metrics(late))}")

    # R1: age
    by_age: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_age[age_bucket(r["age"]) or "unknown"].append(r)
    print_table(
        "Age buckets (entry why age=)",
        by_age,
        ["30-45", "45-60", "60-75", "75-90", "other", "unknown"],
    )
    # combined 30-60 vs 60-90
    g3060 = [r for r in rows if r["age"] is not None and 30 <= r["age"] < 60]
    g6090 = [r for r in rows if r["age"] is not None and 60 <= r["age"] <= 95]
    print_table("Age combined", {"30-60": g3060, "60-90": g6090}, ["30-60", "60-90"])

    # R2: entry quality quantiles
    for field, label in [("mc", "entry MC"), ("liq", "entry liq"), ("liq_mc", "liq/MC"), ("rank", "client_rank")]:
        vals = [r[field] for r in rows if r.get(field) is not None and r[field] >= 0]
        edges = quantile_edges([float(v) for v in vals], k=4)
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            v = r.get(field)
            if v is None or v < 0:
                groups["na"].append(r)
                continue
            q = assign_q(float(v), edges)
            # label range
            lo = "min" if q == 0 else f"{edges[q-1]:g}"
            hi = f"{edges[q]:g}" if q < len(edges) else "max"
            groups[f"Q{q+1}({lo}..{hi})"].append(r)
        order = sorted(groups.keys())
        print_table(f"Quantiles: {label} edges={edges}", groups, order)

    # R3 hazard: data availability / discrimination when keys present
    print("\n## Hazard shadow")
    with_keys = [r for r in rows if r.get("has_hazard_keys")]
    if not with_keys:
        print("  buy events: no hazard_liq / hazard_depth keys on buys")
        print("  VERDICT: cannot estimate P(lp_drop|hazard) — logging gap (deploy gate_audit_fields)")
    else:
        h1 = [r for r in with_keys if r["hazard"]]
        h0 = [r for r in with_keys if not r["hazard"]]

        def _rate(xs, pred):
            return sum(1 for r in xs if pred(r)) / len(xs) if xs else None

        p1 = _rate(h1, lambda r: r["cat"] == "lp_drop")
        p0 = _rate(h0, lambda r: r["cat"] == "lp_drop")
        tp_kill = _rate(h1, lambda r: r["cat"] == "tp")
        print(f"  buys_with_keys={len(with_keys)} hazard1={len(h1)} hazard0={len(h0)}")
        print(f"  P(lp_drop|h=1)={p1}  P(lp_drop|h=0)={p0}  TP_rate|h=1={tp_kill}")
        print_table("Hazard flag (entry)", {"hazard=1": h1, "hazard=0": h0}, ["hazard=1", "hazard=0"])

    # Diagnostic only: max_hold MFE (not an entry gate)
    mh = [r for r in rows if r["cat"] == "max_hold" and r["mfe"] is not None]
    if mh:
        mfes = sorted(r["mfe"] for r in mh)
        def pct(p):
            return mfes[min(len(mfes) - 1, int(p * (len(mfes) - 1)))]
        print("\n## Diagnostic: max_hold executable MFE (post-buy; NOT for entry gates)")
        print(
            f"  n={len(mh)}  p10={pct(0.1):.2f}%  p50={pct(0.5):.2f}%  "
            f"p90={pct(0.9):.2f}%  mean={sum(mfes)/len(mfes):.2f}%"
        )
        print(f"  MFE<0: {sum(1 for x in mfes if x < 0)}  MFE in [3,8): {sum(1 for x in mfes if 3 <= x < 8)}  MFE>=8: {sum(1 for x in mfes if x >= 8)}")

    # exit mix
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["cat"]].append(r)
    print_table("By exit cat (label only; not a gate)", by_cat, ["tp", "lp_drop", "max_hold", "hard_sl", "other"])

    # Decision helpers
    print("\n## Decision inputs")
    m3060, m6090 = metrics(g3060), metrics(g6090)
    print(f"  30-60 PF={m3060['PF']} EV={m3060['EV']} n={m3060['n']}")
    print(f"  60-90 PF={m6090['PF']} EV={m6090['EV']} n={m6090['n']}")
    late3060 = metrics(half_split(g3060)[1])
    late6090 = metrics(half_split(g6090)[1])
    print(f"  30-60 late EV={late3060['EV']} n={late3060['n']}")
    print(f"  60-90 late EV={late6090['EV']} n={late6090['n']}")

    # recommend
    print("\n## Pre-registered decision")
    pf3060 = m3060["PF"] or 0
    if pf3060 == float("inf"):
        pf3060 = 99
    toxic_6090 = (m6090["EV"] is not None and m3060["EV"] is not None and m6090["EV"] < m3060["EV"] - 1e-6)
    near_pf1 = pf3060 >= 0.95
    if near_pf1 and toxic_6090 and m3060["n"] >= 30:
        print("  → SUGGEST paper_ev3_age60 (30-60 near PF1 and 60-90 worse)")
    elif m3060["n"] >= 20 and (pf3060 < 0.9 or (m3060["EV"] is not None and m3060["EV"] < 0)):
        print("  → DO NOT run age60; 30-60 also weak — old counterfactual not supported")
        print("  → hazard unmeasurable this run → fix buy-event hazard logging OR change opportunity set / pre-entry momentum")
    else:
        print("  → inconclusive; need more n or fields")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
