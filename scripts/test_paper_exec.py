#!/usr/bin/env python3
"""Self-check: executable-quote paper inventory + partial fills (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rh_sniper.engine import (  # noqa: E402
    Config,
    _ensure_paper_inventory,
    _paper_exec_exit,
    _paper_partial_or_close,
    gate_audit_fields,
    hazard_from_depth,
    hazard_from_liq_path,
)


def test_partial_and_inventory() -> None:
    cfg = Config(wallet="0x0", tp1=8, tp1_pct=50, tp2=20, tp2_pct=50, tp3=0, tp3_pct=0, hard_sl_pct=15, use_trailing=False)
    meta = {
        "buy_eth": 0.001,
        "quote_out": "1000",
        "initial_tokens": "1000",
        "remaining_tokens": "1000",
        "remaining_cost_basis": 0.001,
        "realized_eth": 0.0,
        "sold_tokens": "0",
        "tp1_filled": False,
        "tp2_filled": False,
        "tp3_filled": False,
        "peak_executable_return": 0.0,
    }
    st = {"paper_realized_est": 0.0, "day_realized_est": 0.0}

    # +10% executable on full remaining
    out_full = 0.0011
    reason, ratio = _paper_exec_exit(cfg, meta, 10.0)
    assert reason and reason.startswith("tp1")
    assert ratio == 50.0
    closed = _paper_partial_or_close(
        cfg, "0xabc", meta, "T", reason, ratio, out_full, st, quote_ok=True, exec_ret_pct=10.0,
    )
    assert closed is None  # still open after 50%
    assert int(meta["remaining_tokens"]) == 500
    assert abs(float(meta["remaining_cost_basis"]) - 0.0005) < 1e-12
    assert meta["tp1_filled"] is True
    assert st["paper_realized_est"] > 0

    # second leg full clear
    reason2, ratio2 = _paper_exec_exit(cfg, meta, 25.0)
    assert reason2 and reason2.startswith("tp2")
    out2 = 0.0005 * 1.25  # remaining cost * 1.25
    closed2 = _paper_partial_or_close(
        cfg, "0xabc", meta, "T", reason2, 100.0, out2, st, quote_ok=True, exec_ret_pct=25.0,
    )
    assert closed2 is not None
    assert closed2["event"] == "paper_exit"
    assert closed2.get("inventory_ok") is True
    assert int(meta["remaining_tokens"]) == 0
    init = int(meta["initial_tokens"])
    sold = int(meta["sold_tokens"])
    assert init == sold


def test_hard_sl() -> None:
    cfg = Config(wallet="0x0", hard_sl_pct=15, tp1=8, tp1_pct=100, use_trailing=False)
    meta = {"tp1_filled": False, "tp2_filled": False, "tp3_filled": False, "peak_executable_return": 0.0}
    reason, ratio = _paper_exec_exit(cfg, meta, -20.0)
    assert reason and reason.startswith("hard_sl")
    assert ratio == 100.0


def test_max_client_rank() -> None:
    from rh_sniper.engine import pre_entry_gate

    cfg = Config(wallet="0x0", max_client_rank=0)
    ok, reason, _ = pre_entry_gate(cfg, {"address": "0xabc", "_client_rank": 2})
    assert ok is False and reason.startswith("client_rank:")
    # missing rank is not rejected (unknown)
    # would proceed past rank check into snapshot — skip full gate


def test_gate_audit_fields() -> None:
    snap = {
        "age": 44,
        "hazard_liq": "liq_drop_9.0pct",
        "hazard_depth": None,
        "liq_path": [{"ts": 1, "liq": 100, "mc": 5e3, "price": 1}],
        "sell_ladder": {"q100": 0.00097, "q100_ok": True, "q50": 0.00049, "planned_tokens": 1, "junk": "x"},
    }
    a = gate_audit_fields(snap)
    assert a["age"] == 44
    assert a["hazard_liq"] == "liq_drop_9.0pct"
    assert a["sell_ladder"]["q100"] == 0.00097
    assert "junk" not in a["sell_ladder"]
    assert a["liq_path"][0]["liq"] == 100


def test_hazard_liq() -> None:
    cfg = Config(wallet="0x0", hazard_max_single_drop_pct=8.0)
    path = [
        {"ts": 1, "liq": 100.0},
        {"ts": 3, "liq": 90.0},  # -10%
    ]
    assert hazard_from_liq_path(cfg, path) is not None
    path2 = [
        {"ts": 1, "liq": 100.0},
        {"ts": 3, "liq": 99.0},
    ]
    assert hazard_from_liq_path(cfg, path2) is None


def test_hazard_depth() -> None:
    cfg = Config(wallet="0x0", hazard_max_full_exit_loss_pct=5.0, hazard_max_impact_spread_pct=4.0, hazard_max_quote_jitter_pct=5.0)
    ladder = {"q100": 0.0009, "q100_ok": True, "q50": 0.00048, "q50_ok": True, "q200_ok": True}
    # buy 0.001, full exit 0.0009 => 10% loss
    h = hazard_from_depth(cfg, ladder, 0.001)
    assert h and "full_exit_loss" in h


def test_ensure_inventory() -> None:
    meta = {"buy_eth": 0.002, "quote_out": "42"}
    _ensure_paper_inventory(meta)
    assert meta["remaining_tokens"] == "42"
    assert meta["remaining_cost_basis"] == 0.002


if __name__ == "__main__":
    test_ensure_inventory()
    test_hard_sl()
    test_partial_and_inventory()
    test_gate_audit_fields()
    test_max_client_rank()
    test_hazard_liq()
    test_hazard_depth()
    print("test_paper_exec OK")
