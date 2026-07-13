#!/usr/bin/env python3
"""Robinhood sniper — strategy replica, NOT copy-trade.

Entry rules reverse-engineered from high-PnL RH wallets:
  safe_lp + mc_in_range + min_liq + (fresh OR reheat) + can_sell
  fixed size, ladder TP/SL, LP-pull emergency dump.

Default dry-run. --live submits real swaps.

API budget (leaky bucket rate=20/s capacity=20):
  fast loop  ~1.0s: trenches(3) + mon liq-only(1/pos)
  slow gate  every N fast loops: hard-check at most K candidates (info+sec+quote≈4 each)
  swap: event-driven only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

NATIVE = "0x0000000000000000000000000000000000000000"
# Runtime artifacts stay next to the process cwd so clones don't dirty the repo tree by default
# when users run from elsewhere; still gitignored if created beside the script.
STATE_PATH = Path(os.environ.get("RH_SNIPER_STATE", Path(__file__).with_name("state.json")))
LOG_PATH = Path(os.environ.get("RH_SNIPER_LOG", Path(__file__).with_name("trades.jsonl")))
SAFE_LP = ("noxa", "bankr", "trench", "virtuals", "flap")


def sh(args: list[str], timeout: int = 60) -> dict | list | None:
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip()
        raise RuntimeError(f"cmd failed ({p.returncode}): {' '.join(args)}\n{err[:500]}")
    out = (p.stdout or "").strip()
    return json.loads(out) if out else None


def fnum(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


@dataclass
class Config:
    wallet: str
    chain: str = "robinhood"
    profile: str = "adff"
    buy_eth: float = 0.03
    slippage: int = 30
    emergency_slippage: int = 50
    poll_sec: float = 1.0  # fast loop: scan + light mon
    gate_every: int = 2  # hard-check candidates every N fast loops
    max_gates_per_tick: int = 2  # hard-checks per gate tick (each ~weight 4)
    mon_security_every: int = 3  # full security on positions every N fast loops
    # age windows
    fresh_max_age_sec: int = 600  # brand-new / just opened
    reheat_max_age_sec: int = 7 * 24 * 3600  # allow older noxa if reheat
    reheat_min_vol_1h: float = 8000.0
    reheat_min_swaps_1h: int = 30
    # size / risk filters from reverse eng
    min_mc: float = 3000.0
    max_mc: float = 15000.0
    min_liquidity: float = 1500.0
    max_top10: float = 0.40
    max_rug: float = 0.25
    min_holders: int = 5
    max_positions: int = 3
    daily_loss_usd: float = 100.0
    # LP rug
    lp_drop_pct: float = 35.0
    min_liq_hold: float = 800.0
    max_hold_sec: int = 300
    require_can_sell: bool = True
    only_safe_lp: bool = True
    # ladder
    tp1: float = 15
    tp1_pct: float = 50
    tp2: float = 40
    tp2_pct: float = 30
    tp3: float = 100
    tp3_pct: float = 20
    sl: float = 20
    live: bool = False
    once: bool = False
    paper_positions: bool = True


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"seen": {}, "positions": {}, "day": time.strftime("%Y-%m-%d"), "day_realized_est": 0.0, "buys_today": 0}


def save_state(st: dict) -> None:
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))


def log_event(obj: dict) -> None:
    with LOG_PATH.open("a") as f:
        f.write(json.dumps({"ts": int(time.time()), **obj}, ensure_ascii=False) + "\n")


def condition_orders(cfg: Config) -> str:
    orders = [
        {"order_type": "profit_stop", "side": "sell", "price_scale": str(int(cfg.tp1)), "sell_ratio": str(int(cfg.tp1_pct))},
        {"order_type": "profit_stop", "side": "sell", "price_scale": str(int(cfg.tp2)), "sell_ratio": str(int(cfg.tp2_pct))},
        {"order_type": "profit_stop", "side": "sell", "price_scale": str(int(cfg.tp3)), "sell_ratio": str(int(cfg.tp3_pct))},
        {"order_type": "loss_stop", "side": "sell", "price_scale": str(int(cfg.sl)), "sell_ratio": "100"},
    ]
    return json.dumps(orders, separators=(",", ":"))


def eth_to_wei(eth: float) -> str:
    return str(int(eth * 1e18))


def estimate_mc(token_row: dict, info: dict | None = None) -> float:
    """Prefer trenches usd_market_cap; else price * supply from info."""
    mc = fnum(token_row.get("usd_market_cap") or token_row.get("market_cap"))
    if mc > 0:
        return mc
    if not info:
        return 0.0
    price_obj = info.get("price")
    price = fnum(price_obj.get("price")) if isinstance(price_obj, dict) else fnum(price_obj)
    supply = fnum(info.get("circulating_supply") or info.get("total_supply"))
    if price > 0 and supply > 0:
        return price * supply
    # RH memes often 1B supply — last resort only if price known from trench
    return 0.0


def activity_1h(info: dict | None, token_row: dict) -> tuple[float, int]:
    """Return (volume_1h, swaps_1h)."""
    vol = fnum(token_row.get("volume_1h") or token_row.get("volume_24h") and 0)
    swaps = int(token_row.get("swaps_1h") or token_row.get("swaps_24h") or 0)
    if info:
        price = info.get("price") if isinstance(info.get("price"), dict) else {}
        vol = fnum(price.get("volume_1h") or price.get("volume_5m") or vol)
        swaps = int(price.get("swaps_1h") or price.get("swaps_5m") or swaps)
        # if only 24h present, don't treat as reheat signal alone
    return vol, swaps


def token_snapshot(cfg: Config, address: str, token_row: dict | None = None, with_security: bool = True) -> dict:
    """info always; security optional (saves weight on fast mon ticks)."""
    token_row = token_row or {}
    info = sh(["gmgn-cli", "token", "info", "--chain", cfg.chain, "--address", address, "--raw"])
    sec: dict = {}
    if with_security:
        try:
            sec = sh(["gmgn-cli", "token", "security", "--chain", cfg.chain, "--address", address, "--raw"]) or {}
        except Exception as e:
            sec = {"_error": str(e)[:200]}

    liq = fnum((info or {}).get("liquidity"))
    pool = (info or {}).get("pool") or {}
    if not liq:
        liq = fnum(pool.get("liquidity") or token_row.get("liquidity"))

    can_sell = sec.get("can_sell")
    sellable = can_sell in (True, 1, "1", "yes", "YES", None)
    honeypot = sec.get("is_honeypot") in (True, 1, "1", "yes", "YES") or sec.get("honeypot") in (True, 1, "1", "yes")
    if sec.get("can_not_sell") in (True, 1, "1", "yes"):
        sellable = False
    if honeypot:
        sellable = False

    top10 = fnum(sec.get("top_10_holder_rate"))
    if not top10 and isinstance((info or {}).get("stat"), dict):
        top10 = fnum((info or {})["stat"].get("top_10_holder_rate"))
    if not top10:
        top10 = fnum(token_row.get("top_10_holder_rate"))

    created = int((info or {}).get("creation_timestamp") or token_row.get("created_timestamp") or 0)
    opened = int((info or {}).get("open_timestamp") or token_row.get("open_timestamp") or 0)
    now = int(time.time())
    open_age = (now - opened) if opened > 0 else None
    create_age = (now - created) if created > 0 else None
    age = open_age if open_age is not None else create_age

    mc = estimate_mc(token_row, info)
    vol_1h, swaps_1h = activity_1h(info, token_row)
    lp = (
        (info or {}).get("launchpad")
        or (info or {}).get("launchpad_platform")
        or token_row.get("launchpad")
        or token_row.get("launchpad_platform")
        or ""
    ).lower()

    return {
        "liquidity": liq,
        "can_sell": sellable,
        "honeypot": honeypot,
        "buy_tax": fnum(sec.get("buy_tax")),
        "sell_tax": fnum(sec.get("sell_tax")),
        "top10": top10,
        "launchpad": lp,
        "symbol": (info or {}).get("symbol") or token_row.get("symbol"),
        "mc": mc,
        "vol_1h": vol_1h,
        "swaps_1h": swaps_1h,
        "created": created,
        "opened": opened,
        "open_age": open_age,
        "create_age": create_age,
        "age": age,
        "raw_sec": {k: sec.get(k) for k in ("can_sell", "can_not_sell", "is_honeypot", "buy_tax", "sell_tax")},
        "with_security": with_security,
    }


def classify_entry(cfg: Config, snap: dict) -> tuple[str | None, str]:
    """Return (mode, reason). mode in {fresh, reheat} or None if reject."""
    age = snap.get("age")
    create_age = snap.get("create_age")
    open_age = snap.get("open_age")

    # fresh: just opened or just created
    fresh_age = open_age if open_age is not None else create_age
    if fresh_age is not None and fresh_age <= cfg.fresh_max_age_sec:
        # also allow open_age negative-ish? opened in future clock skew: treat as fresh
        return "fresh", f"age={fresh_age}s"

    # pre-open bonding: created recently but open_timestamp 0/old
    if open_age is None and create_age is not None and create_age <= cfg.fresh_max_age_sec * 2:
        return "fresh", f"preopen_create_age={create_age}s"

    # reheat: older token with real 1h activity (二次启动)
    if age is not None and age <= cfg.reheat_max_age_sec:
        if snap["vol_1h"] >= cfg.reheat_min_vol_1h or snap["swaps_1h"] >= cfg.reheat_min_swaps_1h:
            return "reheat", f"age={age}s vol1h={snap['vol_1h']:.0f} swaps1h={snap['swaps_1h']}"

    return None, f"stale age={age} vol1h={snap.get('vol_1h')} swaps1h={snap.get('swaps_1h')}"


def pre_entry_gate(cfg: Config, token: dict) -> tuple[bool, str, dict]:
    """Hard rules: safe_lp + mc_range + min_liq + (fresh|reheat) + can_sell + quote."""
    addr = token["address"]
    lp = (token.get("_lp") or token.get("launchpad") or token.get("launchpad_platform") or "").lower()
    if cfg.only_safe_lp and not any(x in lp for x in SAFE_LP):
        return False, f"unsafe_lp:{lp or 'unknown'}", {}

    # cheap trench-level MC prefilter if present
    mc0 = fnum(token.get("usd_market_cap") or token.get("market_cap"))
    if mc0 > 0 and (mc0 < cfg.min_mc * 0.5 or mc0 > cfg.max_mc * 2):
        return False, f"mc_trench_out:{mc0:.0f}", {}

    try:
        snap = token_snapshot(cfg, addr, token)
    except Exception as e:
        return False, f"snapshot_fail:{e}", {}

    # merge lp from snap if trench missing
    lp = snap["launchpad"] or lp
    if cfg.only_safe_lp and not any(x in lp for x in SAFE_LP):
        return False, f"unsafe_lp_live:{lp or 'unknown'}", snap

    if snap["honeypot"]:
        return False, "honeypot", snap
    if cfg.require_can_sell and snap["raw_sec"].get("can_sell") in (False, 0, "0", "no"):
        return False, "can_sell=false", snap
    if snap["liquidity"] < cfg.min_liquidity:
        return False, f"low_liq:{snap['liquidity']:.0f}", snap
    if snap["sell_tax"] > 10 or snap["buy_tax"] > 10:
        return False, f"tax:{snap['buy_tax']}/{snap['sell_tax']}", snap
    if snap["top10"] > cfg.max_top10 > 0:
        return False, f"top10:{snap['top10']}", snap

    mc = snap["mc"]
    if mc <= 0:
        return False, "mc_unknown", snap
    if mc < cfg.min_mc or mc > cfg.max_mc:
        return False, f"mc_out:{mc:.0f} not_in[{cfg.min_mc:.0f},{cfg.max_mc:.0f}]", snap

    mode, why = classify_entry(cfg, snap)
    if not mode:
        return False, f"timing:{why}", snap
    snap["entry_mode"] = mode
    snap["entry_why"] = why

    try:
        sh(
            [
                "gmgn-cli",
                "order",
                "quote",
                "--chain",
                cfg.chain,
                "--from",
                cfg.wallet,
                "--input-token",
                NATIVE,
                "--output-token",
                addr,
                "--amount",
                eth_to_wei(cfg.buy_eth),
                "--slippage",
                str(cfg.slippage),
                "--raw",
            ]
        )
    except Exception as e:
        return False, f"no_buy_route:{e}", snap

    return True, f"ok:{mode}", snap


def fetch_candidates(cfg: Config) -> list[dict]:
    """Pull trenches wide; hard filters happen in pre_entry_gate (MC/reheat need live info)."""
    data = sh(
        [
            "gmgn-cli",
            "market",
            "trenches",
            "--chain",
            cfg.chain,
            "--type",
            "new_creation",
            "--type",
            "completed",
            "--type",
            "near_completion",
            "--limit",
            "50",
            "--raw",
        ]
    )
    now = int(time.time())
    out: list[dict] = []
    if not isinstance(data, dict):
        return out
    for cat, items in data.items():
        for t in items or []:
            addr = (t.get("address") or "").lower()
            if not addr.startswith("0x"):
                continue
            lp = (t.get("launchpad") or t.get("launchpad_platform") or "").lower()
            if cfg.only_safe_lp and lp and not any(x in lp for x in SAFE_LP):
                continue
            created = int(t.get("created_timestamp") or 0)
            opened = int(t.get("open_timestamp") or 0)
            create_age = (now - created) if created else None
            open_age = (now - opened) if opened else None
            age = open_age if open_age is not None else create_age
            if age is None:
                continue
            # keep fresh OR potentially reheat (older but not ancient beyond reheat window)
            is_fresh = age <= cfg.fresh_max_age_sec or (create_age is not None and create_age <= cfg.fresh_max_age_sec)
            is_reheat_cand = age <= cfg.reheat_max_age_sec and (
                fnum(t.get("volume_1h") or t.get("volume_24h")) >= cfg.reheat_min_vol_1h * 0.25
                or int(t.get("swaps_1h") or t.get("swaps_24h") or 0) >= max(5, cfg.reheat_min_swaps_1h // 3)
                or fnum(t.get("liquidity")) >= cfg.min_liquidity
            )
            if not (is_fresh or is_reheat_cand):
                continue
            if fnum(t.get("rug_ratio")) > cfg.max_rug:
                continue
            mc = fnum(t.get("usd_market_cap") or t.get("market_cap"))
            # soft MC band — hard band in gate after live price
            if mc > 0 and (mc < cfg.min_mc * 0.3 or mc > cfg.max_mc * 3):
                continue
            t["_age"] = age
            t["_cat"] = cat
            t["_lp"] = lp
            t["_fresh"] = is_fresh
            out.append(t)
    # prefer fresh, then higher volume, then younger
    out.sort(key=lambda x: (0 if x.get("_fresh") else 1, -fnum(x.get("volume_1h") or x.get("volume_24h")), x.get("_age", 1e18)))
    return out


def buy(cfg: Config, token: str, symbol: str) -> dict:
    amount = eth_to_wei(cfg.buy_eth)
    cond = condition_orders(cfg)
    if not cfg.live:
        q = sh(
            [
                "gmgn-cli",
                "order",
                "quote",
                "--chain",
                cfg.chain,
                "--from",
                cfg.wallet,
                "--input-token",
                NATIVE,
                "--output-token",
                token,
                "--amount",
                amount,
                "--slippage",
                str(cfg.slippage),
                "--raw",
            ]
        )
        return {"mode": "dry-run", "symbol": symbol, "token": token, "amount_wei": amount, "quote_ok": bool(q)}
    res = sh(
        [
            "gmgn-cli",
            "swap",
            "--chain",
            cfg.chain,
            "--from",
            cfg.wallet,
            "--input-token",
            NATIVE,
            "--output-token",
            token,
            "--amount",
            amount,
            "--slippage",
            str(cfg.slippage),
            "--condition-orders",
            cond,
            "--sell-ratio-type",
            "buy_amount",
            "--raw",
        ],
        timeout=90,
    )
    return {"mode": "live", "symbol": symbol, "token": token, "result": res}


def emergency_sell(cfg: Config, token: str, symbol: str, reason: str) -> dict:
    if not cfg.live:
        return {"mode": "dry-run", "event": "emergency_sell", "symbol": symbol, "token": token, "reason": reason}
    res = sh(
        [
            "gmgn-cli",
            "swap",
            "--chain",
            cfg.chain,
            "--from",
            cfg.wallet,
            "--input-token",
            token,
            "--output-token",
            NATIVE,
            "--percent",
            "100",
            "--slippage",
            str(cfg.emergency_slippage),
            "--raw",
        ],
        timeout=90,
    )
    return {"mode": "live", "event": "emergency_sell", "symbol": symbol, "token": token, "reason": reason, "result": res}


def monitor_positions(cfg: Config, st: dict, with_security: bool = False) -> None:
    """Fast mon = liq only (weight 1/pos). Occasional security for can_sell/honeypot."""
    pos = st.get("positions") or {}
    if not pos:
        return
    dead = []
    for addr, meta in list(pos.items()):
        sym = meta.get("symbol") or "?"
        entry_liq = fnum(meta.get("entry_liq"))
        bought_at = int(meta.get("ts") or 0)
        held = int(time.time()) - bought_at if bought_at else 0
        try:
            snap = token_snapshot(cfg, addr, with_security=with_security)
        except Exception as e:
            print(f"[mon_err] {sym}: {e}", flush=True)
            continue
        liq = snap["liquidity"]
        drop = ((entry_liq - liq) / entry_liq * 100.0) if entry_liq > 0 else 0.0
        reason = None
        if with_security and (snap["honeypot"] or snap["raw_sec"].get("can_sell") in (False, 0, "0", "no")):
            reason = "unsellable_or_honeypot"
        elif entry_liq > 0 and drop >= cfg.lp_drop_pct:
            reason = f"lp_drop_{drop:.0f}pct"
        elif liq > 0 and liq < cfg.min_liq_hold:
            reason = f"liq_floor_{liq:.0f}"
        elif held >= cfg.max_hold_sec:
            reason = f"max_hold_{held}s"
        print(
            f"[mon] {sym} held={held}s liq={liq:.0f} entry={entry_liq:.0f} drop={drop:.1f}% "
            f"sec={int(with_security)} can_sell={snap['can_sell']}",
            flush=True,
        )
        if not reason:
            meta["last_liq"] = liq
            meta["last_check"] = int(time.time())
            continue
        print(f"[RUG_EXIT] {sym} reason={reason}", flush=True)
        try:
            res = emergency_sell(cfg, addr, sym, reason)
            log_event({**res, "entry_liq": entry_liq, "liq": liq, "drop_pct": drop, "held": held})
            dead.append(addr)
        except Exception as e:
            log_event({"event": "emergency_sell_error", "token": addr, "symbol": sym, "error": str(e)[:300]})
            print(f"[RUG_EXIT_ERR] {sym}: {e}", flush=True)
    for a in dead:
        st["positions"].pop(a, None)


def prune_seen(st: dict, keep_sec: int = 86400) -> None:
    now = int(time.time())
    st["seen"] = {k: v for k, v in st["seen"].items() if now - int(v) < keep_sec}


def rollover_day(st: dict) -> None:
    day = time.strftime("%Y-%m-%d")
    if st.get("day") != day:
        st["day"] = day
        st["day_realized_est"] = 0.0
        st["buys_today"] = 0


def loop(cfg: Config) -> None:
    st = load_state()
    tick = 0
    # rough steady budget log: trenches3 + mon1*N + gate*(4*K)/gate_every
    est = 3 + cfg.max_positions + (4 * cfg.max_gates_per_tick) / max(cfg.gate_every, 1)
    print(
        f"[start] profile={cfg.profile} buy={cfg.buy_eth}ETH mc=[{cfg.min_mc:.0f},{cfg.max_mc:.0f}] "
        f"fresh<={cfg.fresh_max_age_sec}s reheat_vol>={cfg.reheat_min_vol_1h} min_liq={cfg.min_liquidity} live={cfg.live}",
        flush=True,
    )
    print(
        f"[pace] poll={cfg.poll_sec}s gate_every={cfg.gate_every} max_gates={cfg.max_gates_per_tick} "
        f"mon_sec_every={cfg.mon_security_every} ~weight/s≈{est / cfg.poll_sec:.1f} (cap 20)",
        flush=True,
    )
    print(
        f"[exits] TP {cfg.tp1}/{cfg.tp1_pct}+{cfg.tp2}/{cfg.tp2_pct}+{cfg.tp3}/{cfg.tp3_pct} SL -{cfg.sl}% "
        f"max_hold={cfg.max_hold_sec}s lp_drop={cfg.lp_drop_pct}%",
        flush=True,
    )
    while True:
        t0 = time.time()
        tick += 1
        rollover_day(st)
        prune_seen(st)

        # 1) FAST mon: liq every loop; security every mon_security_every
        do_sec = (tick % max(cfg.mon_security_every, 1) == 0) or cfg.once
        try:
            monitor_positions(cfg, st, with_security=do_sec)
        except Exception as e:
            print(f"[mon_loop_err] {e}", flush=True)
        save_state(st)

        open_n = len(st.get("positions") or {})
        if st.get("day_realized_est", 0) <= -abs(cfg.daily_loss_usd):
            print(f"[halt] daily loss limit: {st['day_realized_est']}", flush=True)
            if cfg.once:
                break
            time.sleep(max(0.0, cfg.poll_sec - (time.time() - t0)))
            continue

        # 2) FAST scan every loop (trenches weight=3)
        cands: list[dict] = []
        if open_n < cfg.max_positions:
            try:
                cands = fetch_candidates(cfg)
            except Exception as e:
                print(f"[err] trenches: {e}", flush=True)
                cands = []
            print(
                f"[scan] tick={tick} cands={len(cands)} open={open_n} buys_today={st.get('buys_today', 0)} "
                f"gate={'Y' if tick % max(cfg.gate_every, 1) == 0 or cfg.once else 'N'}",
                flush=True,
            )

            # 3) SLOW gate: hard-check only every gate_every ticks, max K candidates
            if cands and (tick % max(cfg.gate_every, 1) == 0 or cfg.once):
                checked = 0
                for t in cands:
                    if checked >= cfg.max_gates_per_tick:
                        break
                    addr = t["address"].lower()
                    if addr in st["seen"] or addr in (st.get("positions") or {}):
                        continue
                    sym = t.get("symbol") or "?"
                    checked += 1
                    ok, reason, snap = pre_entry_gate(cfg, t)
                    st["seen"][addr] = int(time.time())
                    if not ok:
                        log_event(
                            {
                                "event": "reject",
                                "token": addr,
                                "symbol": sym,
                                "reason": reason,
                                "mc": snap.get("mc"),
                                "liq": snap.get("liquidity"),
                                "age": snap.get("age"),
                                "lp": snap.get("launchpad") or t.get("_lp"),
                            }
                        )
                        print(
                            f"[reject] {sym} {reason} mc={snap.get('mc', 0):.0f} liq={snap.get('liquidity', 0):.0f}",
                            flush=True,
                        )
                        continue
                    print(
                        f"[signal] {sym} mode={snap.get('entry_mode')} mc=${snap.get('mc', 0):.0f} "
                        f"liq={snap.get('liquidity', 0):.0f} age={snap.get('age')} {snap.get('entry_why')} {addr[:12]}…",
                        flush=True,
                    )
                    try:
                        res = buy(cfg, t["address"], sym)
                        entry_liq = snap.get("liquidity") or fnum(t.get("liquidity"))
                        log_event(
                            {
                                "event": "buy",
                                **res,
                                "entry_liq": entry_liq,
                                "mc": snap.get("mc"),
                                "mode": snap.get("entry_mode"),
                                "why": snap.get("entry_why"),
                                "lp": snap.get("launchpad") or t.get("_lp"),
                            }
                        )
                        if cfg.live or cfg.paper_positions:
                            st.setdefault("positions", {})[addr] = {
                                "symbol": sym,
                                "ts": int(time.time()),
                                "buy_eth": cfg.buy_eth,
                                "entry_liq": entry_liq,
                                "entry_mc": snap.get("mc"),
                                "entry_mode": snap.get("entry_mode"),
                                "lp": snap.get("launchpad") or t.get("_lp"),
                                "mode": res.get("mode"),
                            }
                        st["buys_today"] = int(st.get("buys_today") or 0) + 1
                        save_state(st)
                        print(
                            f"[buy] {res.get('mode')} {sym} mc=${snap.get('mc', 0):.0f} liq={entry_liq:.0f}",
                            flush=True,
                        )
                        break  # one entry per gate tick
                    except Exception as e:
                        log_event({"event": "buy_error", "token": addr, "symbol": sym, "error": str(e)[:300]})
                        print(f"[buy_err] {sym}: {e}", flush=True)
                        save_state(st)
                        break
                else:
                    save_state(st)

        if cfg.once:
            break
        # keep loop cadence even if API was slow
        time.sleep(max(0.0, cfg.poll_sec - (time.time() - t0)))


def apply_profile(cfg: Config, name: str, buy_eth_cli: float) -> None:
    """Parameter packs from reversed wallets — style, not address mirror."""
    cfg.profile = name
    if name == "adff":
        # 荒大宝: ~$50, micro MC, ultra short
        cfg.buy_eth = 0.03 if buy_eth_cli == 0.03 else buy_eth_cli
        cfg.min_mc, cfg.max_mc = 3000, 15000
        cfg.fresh_max_age_sec = 600
        cfg.reheat_min_vol_1h = 5000
        cfg.reheat_min_swaps_1h = 20
        cfg.min_liquidity = 1200
        cfg.tp1, cfg.tp1_pct = 15, 50
        cfg.tp2, cfg.tp2_pct = 40, 30
        cfg.tp3, cfg.tp3_pct = 100, 20
        cfg.sl = 20
        cfg.max_hold_sec = 180
    elif name == "7a23":
        # 0xDavid: probe-ish mid size, $5-40k MC
        cfg.buy_eth = 0.06 if buy_eth_cli == 0.03 else buy_eth_cli
        cfg.min_mc, cfg.max_mc = 5000, 40000
        cfg.fresh_max_age_sec = 900
        cfg.reheat_min_vol_1h = 8000
        cfg.reheat_min_swaps_1h = 30
        cfg.min_liquidity = 2000
        cfg.tp1, cfg.tp1_pct = 20, 40
        cfg.tp2, cfg.tp2_pct = 60, 30
        cfg.tp3, cfg.tp3_pct = 150, 30
        cfg.sl = 25
        cfg.max_hold_sec = 300
    elif name == "417c":
        # heavier size, wider MC incl secondary heat
        cfg.buy_eth = 0.12 if buy_eth_cli == 0.03 else buy_eth_cli
        cfg.min_mc, cfg.max_mc = 8000, 50000
        cfg.fresh_max_age_sec = 1200
        cfg.reheat_min_vol_1h = 12000
        cfg.reheat_min_swaps_1h = 40
        cfg.min_liquidity = 3000
        cfg.tp1, cfg.tp1_pct = 25, 40
        cfg.tp2, cfg.tp2_pct = 80, 30
        cfg.tp3, cfg.tp3_pct = 200, 20
        cfg.sl = 30
        cfg.max_hold_sec = 600


def parse_args() -> Config:
    p = argparse.ArgumentParser(description="RH sniper: safe_lp+mc+fresh/reheat (dry-run default)")
    p.add_argument("--wallet", default=os.environ.get("GMGN_WALLET", "0x37e9f4a84693bce7f7729612ee91a94c91eef898"))
    p.add_argument("--buy-eth", type=float, default=0.03)
    p.add_argument("--slippage", type=int, default=30)
    p.add_argument("--poll", type=float, default=1.0, help="Fast loop seconds (scan+light mon)")
    p.add_argument("--gate-every", type=int, default=2, help="Hard-check candidates every N fast loops")
    p.add_argument("--max-gates", type=int, default=2, help="Max hard-checks per gate tick")
    p.add_argument("--mon-sec-every", type=int, default=3, help="Full security on positions every N loops")
    p.add_argument("--min-mc", type=float, default=None)
    p.add_argument("--max-mc", type=float, default=None)
    p.add_argument("--min-liq", type=float, default=None)
    p.add_argument("--fresh-max-age", type=int, default=None)
    p.add_argument("--reheat-min-vol", type=float, default=None)
    p.add_argument("--lp-drop-pct", type=float, default=35.0, help="Emergency sell if LP falls this percent from entry")
    p.add_argument("--min-liq-hold", type=float, default=800.0)
    p.add_argument("--max-hold-sec", type=int, default=None)
    p.add_argument("--max-positions", type=int, default=3)
    p.add_argument("--daily-loss-usd", type=float, default=100.0)
    p.add_argument("--allow-uniswap", action="store_true")
    p.add_argument("--live", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--profile", choices=["adff", "417c", "7a23"], default="adff")
    a = p.parse_args()
    cfg = Config(
        wallet=a.wallet,
        buy_eth=a.buy_eth,
        slippage=a.slippage,
        poll_sec=a.poll,
        gate_every=max(1, a.gate_every),
        max_gates_per_tick=max(1, a.max_gates),
        mon_security_every=max(1, a.mon_sec_every),
        lp_drop_pct=a.lp_drop_pct,
        min_liq_hold=a.min_liq_hold,
        max_positions=a.max_positions,
        daily_loss_usd=a.daily_loss_usd,
        only_safe_lp=not a.allow_uniswap,
        live=a.live,
        once=a.once,
    )
    apply_profile(cfg, a.profile, a.buy_eth)
    if a.min_mc is not None:
        cfg.min_mc = a.min_mc
    if a.max_mc is not None:
        cfg.max_mc = a.max_mc
    if a.min_liq is not None:
        cfg.min_liquidity = a.min_liq
    if a.fresh_max_age is not None:
        cfg.fresh_max_age_sec = a.fresh_max_age
    if a.reheat_min_vol is not None:
        cfg.reheat_min_vol_1h = a.reheat_min_vol
    if a.max_hold_sec is not None:
        cfg.max_hold_sec = a.max_hold_sec
    return cfg


def main() -> None:
    cfg = parse_args()
    if cfg.live:
        print("WARNING: --live spends real funds", flush=True)
    try:
        loop(cfg)
    except KeyboardInterrupt:
        print("\n[stop]", flush=True)


if __name__ == "__main__":
    main()
