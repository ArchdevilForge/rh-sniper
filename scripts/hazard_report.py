#!/usr/bin/env python3
"""Summarize hazard-related rejects and lp_drop exits from trade logs."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def _hazard_flagged(e: dict) -> bool:
    return bool(e.get("hazard_liq") or e.get("hazard_depth"))


def report(path: Path) -> dict:
    from datetime import datetime

    events = load_jsonl(path)
    rejects = [e for e in events if e.get("event") == "reject"]
    buys = [e for e in events if e.get("event") == "buy"]
    shadows = [e for e in events if e.get("event") == "shadow_signal"]
    exits = [e for e in events if e.get("event") in ("paper_exit", "emergency_sell")]
    hazard_rej = [e for e in rejects if str(e.get("reason") or "").startswith("hazard:")]
    lp_exits = [e for e in exits if "lp_drop" in str(e.get("reason") or "")]

    # FIFO join buy → exit by token for shadow discrimination (needs buy hazard fields)
    exit_q: dict[str, list[dict]] = defaultdict(list)
    for x in exits:
        tok = str(x.get("token") or "").lower()
        if tok:
            exit_q[tok].append(x)
    joined = []
    for b in buys:
        tok = str(b.get("token") or "").lower()
        if not tok or not exit_q[tok]:
            continue
        x = exit_q[tok].pop(0)
        joined.append({
            "hazard": _hazard_flagged(b),
            "lp_drop": "lp_drop" in str(x.get("reason") or ""),
            "tp": str(x.get("reason") or "").startswith("tp"),
            "pnl": float(x.get("pnl_eth_est") or 0),
        })

    buys_with_hz_field = sum(1 for b in buys if "hazard_liq" in b or "hazard_depth" in b)
    h1 = [j for j in joined if j["hazard"]]
    h0 = [j for j in joined if not j["hazard"]]

    def rate(rows, key):
        return (sum(1 for r in rows if r[key]) / len(rows)) if rows else None

    by_day: dict[str, dict] = defaultdict(
        lambda: {"rejects": 0, "hazard": 0, "lp_drop_exits": 0, "buys": 0}
    )
    for e in events:
        ts = int(e.get("ts") or 0)
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "?"
        ev = e.get("event")
        if ev == "reject":
            by_day[day]["rejects"] += 1
            if str(e.get("reason") or "").startswith("hazard:"):
                by_day[day]["hazard"] += 1
        elif ev == "buy":
            by_day[day]["buys"] += 1
        elif ev in ("paper_exit", "emergency_sell") and "lp_drop" in str(e.get("reason") or ""):
            by_day[day]["lp_drop_exits"] += 1

    disc = {
        "joined_buys": len(joined),
        "buys_with_hazard_keys": buys_with_hz_field,
        "P_lp_drop_hazard1": rate(h1, "lp_drop"),
        "P_lp_drop_hazard0": rate(h0, "lp_drop"),
        "n_hazard1": len(h1),
        "n_hazard0": len(h0),
        "tp_killed_if_hazard1": rate(h1, "tp"),
        "measurable": buys_with_hz_field > 0 and len(joined) > 0,
    }
    if not disc["measurable"]:
        disc["note"] = "buy events missing hazard_* keys — cannot score shadow discrimination"

    return {
        "events": len(events),
        "rejects": len(rejects),
        "buys": len(buys),
        "shadow_signals": len(shadows),
        "hazard_rejects": len(hazard_rej),
        "hazard_reasons": Counter(str(e.get("reason")) for e in hazard_rej).most_common(15),
        "lp_drop_exits": len(lp_exits),
        "lp_drop_pnl_eth": sum(float(e.get("pnl_eth_est") or 0) for e in lp_exits),
        "shadow_discrimination": disc,
        "by_day": dict(by_day),
    }


def self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.jsonl"
        rows = [
            {"ts": 1, "event": "reject", "reason": "hazard:liq_drop_10.0pct"},
            {"ts": 2, "event": "reject", "reason": "low_liq:0"},
            {
                "ts": 3,
                "event": "buy",
                "token": "0xa",
                "hazard_liq": "liq_drop_9pct",
                "hazard_depth": None,
            },
            {"ts": 4, "event": "paper_exit", "token": "0xa", "reason": "lp_drop_80pct", "pnl_eth_est": -0.001},
            {"ts": 5, "event": "buy", "token": "0xb", "hazard_liq": None, "hazard_depth": None},
            {"ts": 6, "event": "paper_exit", "token": "0xb", "reason": "max_hold_60s", "pnl_eth_est": -0.00002},
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        r = report(p)
        assert r["hazard_rejects"] == 1
        assert r["lp_drop_exits"] == 1
        assert abs(r["lp_drop_pnl_eth"] + 0.001) < 1e-12
        d = r["shadow_discrimination"]
        assert d["measurable"] is True
        assert d["n_hazard1"] == 1 and d["n_hazard0"] == 1
        assert d["P_lp_drop_hazard1"] == 1.0
        assert d["P_lp_drop_hazard0"] == 0.0
    print("hazard_report self_check OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=Path, help="trades jsonl")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()
    if args.self_check:
        self_check()
        return
    if not args.log:
        ap.error("--log or --self-check required")
    print(json.dumps(report(args.log), indent=2))


if __name__ == "__main__":
    main()
