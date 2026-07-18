#!/usr/bin/env python3
"""Opportunity-set coverage funnel from scan + trade logs (+ optional wallet buys)."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    if not path or not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def report(scan_path: Path, trade_path: Path | None, wallet_path: Path | None) -> dict:
    scans = [e for e in load_jsonl(scan_path) if e.get("event") == "scan_candidate"]
    trades = load_jsonl(trade_path) if trade_path else []
    wallets = load_jsonl(wallet_path) if wallet_path else []

    by_token_first: dict[str, dict] = {}
    for e in scans:
        tok = (e.get("token") or "").lower()
        if not tok:
            continue
        prev = by_token_first.get(tok)
        if prev is None or int(e.get("ts") or 0) < int(prev.get("ts") or 0):
            by_token_first[tok] = e

    selected = sum(1 for e in scans if e.get("was_selected_for_gate"))
    reasons: dict[str, int] = defaultdict(int)
    for e in scans:
        reasons[str(e.get("not_selected_reason") or e.get("gate_result") or "?")] += 1

    rejects = [e for e in trades if e.get("event") == "reject"]
    buys = [e for e in trades if e.get("event") == "buy"]
    shadows = [e for e in trades if e.get("event") == "shadow_signal"]

    out = {
        "scan_events": len(scans),
        "unique_tokens_scanned": len(by_token_first),
        "selected_for_gate": selected,
        "select_rate": (selected / len(scans)) if scans else 0.0,
        "not_selected_reasons": dict(sorted(reasons.items(), key=lambda x: -x[1])[:20]),
        "rejects": len(rejects),
        "buys": len(buys),
        "shadow_signals": len(shadows),
    }

    # wallet coverage if provided: list of {token, wallet_buy_ts}
    if wallets:
        s0 = len(wallets)
        s1 = s2 = s3 = s4 = s5 = 0
        for w in wallets:
            tok = (w.get("token") or "").lower()
            wts = int(w.get("wallet_buy_ts") or w.get("ts") or 0)
            seen = [
                e for e in scans
                if (e.get("token") or "").lower() == tok and int(e.get("ts") or 0) <= wts
            ]
            if not seen:
                continue
            s1 += 1
            # rank visible: any with client_rank < max_gates typical 12 — use was_selected or rank<20
            if any(e.get("was_selected_for_gate") or (e.get("client_rank") is not None and e["client_rank"] < 20) for e in seen):
                s2 += 1
            if any(e.get("was_selected_for_gate") for e in seen):
                s3 += 1
            if any(str(e.get("gate_result") or "").startswith("ok") for e in seen):
                s4 += 1
            if any(e.get("event") == "buy" for e in trades if (e.get("token") or "").lower() == tok):
                s5 += 1
        out["wallet"] = {
            "S0": s0,
            "S1_api_seen": s1,
            "S2_rank_visible": s2,
            "S3_gate_reached": s3,
            "S4_pass": s4,
            "S5_exec": s5,
            "api_seen_rate": s1 / s0 if s0 else 0.0,
            "gate_reached_rate": s3 / s0 if s0 else 0.0,
            "comparable_coverage_S3": s3 / s0 if s0 else 0.0,
        }
    return out


def self_check() -> None:
    """Synthetic funnel: 3 scans, 1 wallet buy that was gated."""
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as d:
        scan = Path(d) / "scans.jsonl"
        trade = Path(d) / "trades.jsonl"
        wallet = Path(d) / "wallet.jsonl"
        rows = [
            {"ts": 100, "event": "scan_candidate", "token": "0xa", "client_rank": 0, "was_selected_for_gate": True, "gate_result": "ok", "not_selected_reason": None},
            {"ts": 100, "event": "scan_candidate", "token": "0xb", "client_rank": 1, "was_selected_for_gate": False, "not_selected_reason": "beyond_max_gates"},
            {"ts": 100, "event": "scan_candidate", "token": "0xc", "client_rank": 2, "was_selected_for_gate": False, "not_selected_reason": "already_seen"},
        ]
        scan.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        trade.write_text(json.dumps({"ts": 101, "event": "buy", "token": "0xa"}) + "\n")
        wallet.write_text(json.dumps({"token": "0xa", "wallet_buy_ts": 200}) + "\n")
        r = report(scan, trade, wallet)
        assert r["scan_events"] == 3
        assert r["selected_for_gate"] == 1
        assert r["wallet"]["S1_api_seen"] == 1
        assert r["wallet"]["S3_gate_reached"] == 1
        # wallet buy on 0xd never seen
        wallet.write_text(
            json.dumps({"token": "0xa", "wallet_buy_ts": 200}) + "\n"
            + json.dumps({"token": "0xd", "wallet_buy_ts": 200}) + "\n"
        )
        r2 = report(scan, trade, wallet)
        assert r2["wallet"]["S0"] == 2
        assert abs(r2["wallet"]["api_seen_rate"] - 0.5) < 1e-9
    print("coverage_report self_check OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", type=Path, help="scans.jsonl")
    ap.add_argument("--trades", type=Path, default=None)
    ap.add_argument("--wallet", type=Path, default=None, help="wallet buys jsonl: token,wallet_buy_ts")
    ap.add_argument("--fixture", type=Path, default=None, help="legacy: treat as scan path")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()
    if args.self_check:
        self_check()
        return
    scan = args.scan or args.fixture
    if not scan:
        ap.error("--scan or --self-check required")
    r = report(scan, args.trades, args.wallet)
    print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
