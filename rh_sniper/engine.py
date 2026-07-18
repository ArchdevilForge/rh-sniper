#!/usr/bin/env python3
"""Robinhood sniper engine — HF reverse strategy + v0.4 live hardening."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

NATIVE = "0x0000000000000000000000000000000000000000"
# bankr removed: paper100 showed ~-0.17e-3 ETH/trade EV vs virtuals +EV
SAFE_LP = ("pons", "noxa", "trench", "virtuals", "flap")

# Paths resolved in configure_runtime() after live/dry known
STATE_PATH = Path(os.environ.get("RH_SNIPER_STATE", "state.json")).expanduser()
LOG_PATH = Path(os.environ.get("RH_SNIPER_LOG", "trades.jsonl")).expanduser()
SCAN_LOG_PATH = Path(os.environ.get("RH_SNIPER_SCAN_LOG", "scans.jsonl")).expanduser()


class RateLimitError(RuntimeError):
    def __init__(self, message: str, sleep_s: float = 60.0):
        super().__init__(message)
        self.sleep_s = sleep_s


class AuthError(RuntimeError):
    """GMGN 401 / auth failure — cool down instead of thrashing quotes."""
    def __init__(self, message: str, sleep_s: float = 120.0):
        super().__init__(message)
        self.sleep_s = sleep_s


def fnum(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _parse_rate_limit_sleep(text: str) -> float | None:
    if not text:
        return None
    low = text.lower()
    if "429" not in text and "rate_limit" not in low and "rate limit" not in low and "rate-limit" not in low:
        return None
    m = re.search(r"reset_at[\"']?\s*[:=]\s*(\d{10,})", text)
    if m:
        return max(5.0, min(300.0, int(m.group(1)) - time.time() + 1))
    m = re.search(r"x-ratelimit-reset[\"']?\s*[:=]\s*(\d{10,})", text, re.I)
    if m:
        return max(5.0, min(300.0, int(m.group(1)) - time.time() + 1))
    m = re.search(r"retry(?:ing)?(?: once)? in (\d+(?:\.\d+)?)s", text, re.I)
    if m:
        return max(5.0, float(m.group(1)))
    return 60.0


def _is_auth_error(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return (
        "http 401" in low
        or "code=401" in low
        or " error=401" in low
        or "unauthorized" in low
        or "invalid api" in low
        or "api key" in low and ("invalid" in low or "expired" in low)
    )


def sh(args: list[str], timeout: int = 60, retries: int = 1) -> dict | list | None:
    last_err = ""
    for attempt in range(max(1, retries + 1)):
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        blob = (err + "\n" + out).strip()
        if p.returncode == 0:
            return json.loads(out) if out else None
        last_err = blob
        if _is_auth_error(blob):
            raise AuthError(f"auth failed: {blob[:300]}", sleep_s=120.0)
        sleep_s = _parse_rate_limit_sleep(blob)
        if sleep_s is not None:
            if attempt < retries:
                print(f"[rate_limit] sleep {sleep_s:.0f}s then retry {attempt+1}/{retries}", flush=True)
                time.sleep(sleep_s)
                continue
            raise RateLimitError(f"rate limited: {blob[:300]}", sleep_s=sleep_s)
        raise RuntimeError(f"cmd failed ({p.returncode}): {' '.join(args)}\n{blob[:500]}")
    raise RuntimeError(f"cmd failed: {' '.join(args)}\n{last_err[:500]}")


@dataclass
class Config:
    wallet: str
    chain: str = "robinhood"
    profile: str = "adff"
    buy_eth: float = 0.03
    slippage: int = 30
    emergency_slippage: int = 50
    poll_sec: float = 1.0
    gate_every: int = 2
    max_gates_per_tick: int = 2
    mon_security_every: int = 3
    fresh_min_age_sec: int = 0  # skip ultra-fresh snipes; paper: 0-15s was -EV
    fresh_max_age_sec: int = 600
    reheat_max_age_sec: int = 7 * 24 * 3600
    reheat_min_vol_1h: float = 8000.0
    reheat_min_swaps_1h: int = 30
    min_mc: float = 3000.0
    max_mc: float = 15000.0
    bankr_max_mc: float = 35000.0  # bankr often prints >15k on open
    min_liquidity: float = 1500.0
    allowed_lps: tuple[str, ...] = ()  # empty = SAFE_LP; else intersect
    max_top10: float = 0.40
    max_top10_fresh: float = 0.70  # first-wave concentration is normal
    fresh_top10_age_sec: int = 45
    allow_unindexed_liq: bool = True  # liq==0 + fresh → trust buy quote
    soft_retry_sec: int = 5
    disable_reheat: bool = False  # adff first-wave only
    max_rug: float = 0.25
    min_holders: int = 5
    max_positions: int = 3
    daily_loss_usd: float = 100.0
    lp_drop_pct: float = 35.0
    min_liq_hold: float = 800.0
    max_hold_sec: int = 300
    require_can_sell: bool = True
    only_safe_lp: bool = True
    exit_mode: str = "hf_scale"
    tp1: float = 30
    tp1_pct: float = 25
    tp2: float = 80
    tp2_pct: float = 30
    tp3: float = 150
    tp3_pct: float = 25
    trail_activate_pct: float = 80
    trail_drawdown_pct: float = 25
    hard_sl_pct: float = 35
    sl: float = 35
    use_trailing: bool = True
    live: bool = False
    once: bool = False
    paper_positions: bool = False  # dry-run default: do NOT pollute positions
    require_sell_quote: bool = True
    probe_eth: float = 0.0
    risk_pct: float = 0.0
    max_buy_eth: float = 0.0
    min_wallet_eth: float = 0.01
    require_live_balance: bool = True
    anti_mev: bool = True
    max_liq_mc_ratio: float = 2.0
    min_liq_mc_ratio: float = 0.02
    max_creator_open_count: int = 20
    reject_creator_hold: bool = False
    fake_heat_min_vol_1h: float = 20000.0
    fake_heat_max_price_change_1h: float = 0.05
    enable_fake_heat: bool = True
    bankroll_eth: float = 0.0
    max_open_exposure_pct: float = 15.0
    default_risk_pct: float = 1.0
    use_default_risk: bool = False
    active_hours_cn: str = "18-4"
    offhours_mode: str = "sleep"
    offhours_poll_sec: float = 60.0
    timezone_offset_hours: int = 8
    # v0.4 hardening
    confirm_orders: bool = True
    order_confirm_timeout_s: float = 45.0
    order_confirm_poll_s: float = 2.0
    pnl_refresh_every: int = 15  # ticks
    local_exit_if_no_strategy: bool = True
    auth_cooldown_sec: float = 120.0
    # opportunity-set / measurement / hazard pipeline
    scan_log_enabled: bool = True
    shadow_collect: bool = False  # gate+log only; never buy
    hazard_mode: str = "off"  # off|shadow|enforce
    hazard_snap_n: int = 3
    hazard_snap_gap_sec: float = 2.0
    hazard_max_single_drop_pct: float = 8.0
    hazard_max_full_exit_loss_pct: float = 5.0
    hazard_max_impact_spread_pct: float = 4.0
    hazard_max_quote_jitter_pct: float = 5.0


def configure_runtime(cfg: Config) -> None:
    """Isolate dry/live state+log files unless env overrides."""
    global STATE_PATH, LOG_PATH, SCAN_LOG_PATH
    if os.environ.get("RH_SNIPER_STATE"):
        STATE_PATH = Path(os.environ["RH_SNIPER_STATE"]).expanduser()
    else:
        STATE_PATH = Path("state.live.json" if cfg.live else "state.dry.json")
    if os.environ.get("RH_SNIPER_LOG"):
        LOG_PATH = Path(os.environ["RH_SNIPER_LOG"]).expanduser()
    else:
        LOG_PATH = Path("trades.live.jsonl" if cfg.live else "trades.dry.jsonl")
    if os.environ.get("RH_SNIPER_SCAN_LOG"):
        SCAN_LOG_PATH = Path(os.environ["RH_SNIPER_SCAN_LOG"]).expanduser()
    else:
        tag = "live" if cfg.live else ("shadow" if cfg.shadow_collect else "dry")
        SCAN_LOG_PATH = Path(f"scans.{tag}.jsonl")
    # live always tracks positions; dry only if paper_positions
    if cfg.live:
        cfg.paper_positions = True
    if cfg.shadow_collect:
        cfg.live = False
        cfg.paper_positions = False
        cfg.max_positions = 0


def load_state() -> dict:
    if STATE_PATH.exists():
        st = json.loads(STATE_PATH.read_text())
        st.setdefault("soft_seen", {})
        return st
    return {
        "seen": {},
        "soft_seen": {},
        "positions": {},
        "day": time.strftime("%Y-%m-%d"),
        "day_realized_est": 0.0,
        "paper_realized_est": 0.0,
        "buys_today": 0,
        "session_start_realized": None,
    }


def save_state(st: dict) -> None:
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))


def log_event(obj: dict) -> None:
    with LOG_PATH.open("a") as f:
        f.write(json.dumps({"ts": int(time.time()), **obj}, ensure_ascii=False) + "\n")


def log_scan_event(obj: dict) -> None:
    with SCAN_LOG_PATH.open("a") as f:
        f.write(json.dumps({"ts": int(time.time()), **obj}, ensure_ascii=False) + "\n")


def condition_orders(cfg: Config) -> str:
    sl = int(cfg.hard_sl_pct or cfg.sl or 35)
    orders = []
    for scale, ratio in ((cfg.tp1, cfg.tp1_pct), (cfg.tp2, cfg.tp2_pct), (cfg.tp3, cfg.tp3_pct)):
        r = int(ratio)
        if r <= 0:
            continue
        orders.append({"order_type": "profit_stop", "side": "sell", "price_scale": str(int(scale)), "sell_ratio": str(r)})
    orders.append({"order_type": "loss_stop", "side": "sell", "price_scale": str(sl), "sell_ratio": "100"})
    sold = sum(int(x) for x in (cfg.tp1_pct, cfg.tp2_pct, cfg.tp3_pct))
    rem = max(0, 100 - sold)
    if cfg.use_trailing and rem > 0:
        orders.append({
            "order_type": "profit_stop_trace",
            "side": "sell",
            "price_scale": str(int(cfg.trail_activate_pct)),
            "sell_ratio": str(rem),
            "drawdown_rate": str(int(cfg.trail_drawdown_pct)),
        })
    elif rem > 0:
        for o in reversed(orders):
            if o.get("order_type") == "profit_stop":
                o["sell_ratio"] = str(int(o["sell_ratio"]) + rem)
                break
    return json.dumps(orders, separators=(",", ":"))


def eth_to_wei(eth: float) -> str:
    return str(int(eth * 1e18))


def quote(cfg: Config, input_token: str, output_token: str, amount_wei: str, slippage: int | None = None) -> dict:
    return sh([
        "gmgn-cli", "order", "quote",
        "--chain", cfg.chain, "--from", cfg.wallet,
        "--input-token", input_token, "--output-token", output_token,
        "--amount", amount_wei,
        "--slippage", str(slippage if slippage is not None else cfg.slippage),
        "--raw",
    ], retries=1) or {}


def extract_order_id(result: dict | None) -> str | None:
    if not isinstance(result, dict):
        return None
    for k in ("order_id", "orderId", "id"):
        if result.get(k):
            return str(result.get(k))
    # nested
    for nest in ("data", "result", "order"):
        n = result.get(nest)
        if isinstance(n, dict):
            for k in ("order_id", "orderId", "id"):
                if n.get(k):
                    return str(n.get(k))
    return None


def extract_strategy_id(result: dict | None) -> str | None:
    if not isinstance(result, dict):
        return None
    for k in ("strategy_order_id", "strategyOrderId"):
        if result.get(k):
            return str(result.get(k))
    for nest in ("data", "result"):
        n = result.get(nest)
        if isinstance(n, dict) and n.get("strategy_order_id"):
            return str(n.get("strategy_order_id"))
    return None


def wait_order(cfg: Config, order_id: str | None) -> dict:
    """Poll order get until confirmed/failed/timeout."""
    if not order_id or not cfg.confirm_orders:
        return {"status": "skipped", "order_id": order_id}
    deadline = time.time() + cfg.order_confirm_timeout_s
    last: dict = {}
    while time.time() < deadline:
        try:
            last = sh([
                "gmgn-cli", "order", "get",
                "--chain", cfg.chain,
                "--order-id", order_id,
                "--raw",
            ], retries=0) or {}
        except RateLimitError as e:
            raise
        except Exception as e:
            last = {"status": "query_error", "error": str(e)[:200]}
            time.sleep(cfg.order_confirm_poll_s)
            continue
        status = str(last.get("status") or last.get("state") or "").lower()
        # common success markers
        if status in ("confirmed", "successful", "success", "filled", "done"):
            return {**last, "status": "confirmed"}
        if status in ("failed", "fail", "expired", "error", "cancelled", "canceled"):
            return {**last, "status": "failed"}
        # numeric state sometimes 30=success per docs
        if str(last.get("state")) == "30" or last.get("status") == "successful":
            return {**last, "status": "confirmed"}
        time.sleep(cfg.order_confirm_poll_s)
    return {**(last or {}), "status": "timeout", "order_id": order_id}


def native_balance_eth(cfg: Config) -> float:
    info = sh(["gmgn-cli", "portfolio", "info", "--raw"], retries=1) or {}
    wallet = (cfg.wallet or "").lower()
    for w in info.get("wallets") or []:
        if (w.get("chain") or "").lower() != cfg.chain.lower():
            continue
        if wallet and (w.get("address") or "").lower() != wallet:
            continue
        for b in w.get("balances") or []:
            if (b.get("token_address") or "").lower() in ("", NATIVE.lower()):
                return fnum(b.get("balance"))
    for w in info.get("wallets") or []:
        if (w.get("chain") or "").lower() != cfg.chain.lower():
            continue
        for b in w.get("balances") or []:
            if (b.get("token_address") or "").lower() in ("", NATIVE.lower()):
                return fnum(b.get("balance"))
    # portfolio info may be empty even when wallet is tradeable — fall back to stats
    if wallet:
        try:
            stats = sh([
                "gmgn-cli", "portfolio", "stats",
                "--chain", cfg.chain, "--wallet", wallet, "--period", "7d", "--raw",
            ], retries=0) or {}
            if isinstance(stats, list) and stats:
                stats = stats[0]
            bal = fnum(stats.get("native_balance"))
            if bal > 0:
                return bal
        except Exception:
            pass
    return 0.0


def bankroll_eth(cfg: Config) -> float:
    if cfg.bankroll_eth and cfg.bankroll_eth > 0:
        return cfg.bankroll_eth
    return native_balance_eth(cfg)


def resolve_buy_eth(cfg: Config) -> float:
    risk = cfg.risk_pct
    if (not risk or risk <= 0) and cfg.use_default_risk and cfg.default_risk_pct > 0:
        risk = cfg.default_risk_pct
    if risk and risk > 0:
        bal = bankroll_eth(cfg)
        if bal <= 0:
            return max(cfg.buy_eth, 0.0)
        pct = risk / 100.0 if risk >= 1 else risk
        size = bal * pct
        cap = cfg.max_buy_eth if cfg.max_buy_eth > 0 else (cfg.buy_eth if cfg.buy_eth > 0 else size)
        if cap > 0:
            size = min(size, cap)
        return max(size, 0.0)
    return max(cfg.buy_eth, 0.0)


def exposure_ok(cfg: Config, st: dict, next_buy_eth: float) -> tuple[bool, str]:
    if cfg.max_open_exposure_pct <= 0:
        return True, "ok"
    br = bankroll_eth(cfg)
    if br <= 0:
        return True, "no_bankroll_skip_exposure"
    open_eth = sum(float(m.get("buy_eth") or 0) for m in (st.get("positions") or {}).values())
    pct = (open_eth + next_buy_eth) / br * 100.0
    if pct > cfg.max_open_exposure_pct:
        return False, f"exposure {pct:.1f}%>{cfg.max_open_exposure_pct}"
    return True, f"exposure {pct:.1f}%"


def live_preflight(cfg: Config) -> tuple[bool, str]:
    if not cfg.live:
        return True, "dry-run"
    p = subprocess.run(["gmgn-cli", "config", "--check"], capture_output=True, text=True)
    if p.returncode != 0:
        return False, f"gmgn_config_fail:{(p.stderr or p.stdout)[:200]}"
    if cfg.require_live_balance:
        bal = native_balance_eth(cfg)
        need = max(cfg.min_wallet_eth, resolve_buy_eth(cfg) * 1.2)
        if bal < need:
            return False, f"insufficient_native bal={bal:.6f} need>={need:.6f}"
    return True, "ok"


def refresh_day_pnl(cfg: Config, st: dict) -> None:
    """Best-effort day realized from portfolio stats 7d (delta from session start)."""
    if not cfg.live:
        return
    try:
        stats = sh([
            "gmgn-cli", "portfolio", "stats",
            "--chain", cfg.chain,
            "--wallet", cfg.wallet,
            "--period", "7d",
            "--raw",
        ], retries=0) or {}
        # batch may return list
        if isinstance(stats, list) and stats:
            stats = stats[0]
        realized = fnum(stats.get("realized_profit"))
        if st.get("session_start_realized") is None:
            st["session_start_realized"] = realized
        st["day_realized_est"] = realized - fnum(st.get("session_start_realized"))
        st["last_pnl_refresh"] = int(time.time())
        log_event({"event": "pnl_refresh", "realized_7d": realized, "day_realized_est": st["day_realized_est"]})
    except RateLimitError:
        raise
    except Exception as e:
        log_event({"event": "pnl_refresh_error", "error": str(e)[:200]})


def estimate_mc(token_row: dict, info: dict | None = None) -> float:
    mc = fnum(token_row.get("usd_market_cap") or token_row.get("market_cap"))
    if mc > 0:
        return mc
    if not info:
        return 0.0
    price_obj = info.get("price")
    price = fnum(price_obj.get("price")) if isinstance(price_obj, dict) else fnum(price_obj)
    supply = fnum(info.get("circulating_supply") or info.get("total_supply"))
    return price * supply if price > 0 and supply > 0 else 0.0


def activity_1h(info: dict | None, token_row: dict) -> tuple[float, int]:
    vol = fnum(token_row.get("volume_1h") or 0)
    swaps = int(token_row.get("swaps_1h") or token_row.get("swaps_24h") or 0)
    if info and isinstance(info.get("price"), dict):
        price = info["price"]
        vol = fnum(price.get("volume_1h") or price.get("volume_5m") or vol)
        swaps = int(price.get("swaps_1h") or price.get("swaps_5m") or swaps)
    return vol, swaps


def _explicit_unsellable(sec: dict, chain: str) -> bool:
    """GMGN RH often returns can_sell=0 before scan; trust sell quote there, not this flag."""
    if sec.get("can_not_sell") in (True, 1, "1", "yes", "YES"):
        return True
    cs = sec.get("can_sell")
    # ponytail: never use `cs in (False, ...)` — 0 == False in Python
    if cs is False or (isinstance(cs, str) and cs.lower() in ("false", "no")):
        return True
    if (chain or "").lower() == "robinhood" and cs in (0, "0", None):
        return False
    if cs in (0, "0"):
        return True
    return False


def fake_heat_reject(cfg: Config, snap: dict) -> str | None:
    if not cfg.enable_fake_heat:
        return None
    mc, liq = fnum(snap.get("mc")), fnum(snap.get("liquidity"))
    if mc > 0 and liq > 0:
        ratio = liq / mc
        if ratio > cfg.max_liq_mc_ratio:
            return f"liq_mc_high:{ratio:.2f}"
        if ratio < cfg.min_liq_mc_ratio:
            return f"liq_mc_low:{ratio:.4f}"
    vol = fnum(snap.get("vol_1h"))
    ret = snap.get("ret_1h")
    if vol >= cfg.fake_heat_min_vol_1h and ret is not None and abs(ret) <= cfg.fake_heat_max_price_change_1h:
        return f"washish vol1h={vol:.0f} ret1h={ret:.3f}"
    bv, sv = fnum(snap.get("buy_vol_1h")), fnum(snap.get("sell_vol_1h"))
    if bv >= cfg.fake_heat_min_vol_1h and sv < bv * 0.02:
        return f"one_way_buy bv={bv:.0f} sv={sv:.0f}"
    return None


def creator_reject(cfg: Config, snap: dict) -> str | None:
    if cfg.max_creator_open_count > 0:
        n = int(snap.get("creator_open_count") or 0)
        if n > cfg.max_creator_open_count:
            return f"creator_spam open_count={n}"
    if cfg.reject_creator_hold:
        st = (snap.get("creator_token_status") or "").lower()
        if "hold" in st and "close" not in st:
            return f"creator_hold:{st}"
        if fnum(snap.get("creator_token_balance")) > 0 and "close" not in st:
            return f"creator_bal:{snap.get('creator_token_balance')}"
    return None


def token_snapshot(cfg: Config, address: str, token_row: dict | None = None, with_security: bool = True) -> dict:
    token_row = token_row or {}
    info = sh(["gmgn-cli", "token", "info", "--chain", cfg.chain, "--address", address, "--raw"], retries=1)
    sec: dict = {}
    if with_security:
        try:
            sec = sh(["gmgn-cli", "token", "security", "--chain", cfg.chain, "--address", address, "--raw"], retries=0) or {}
        except Exception as e:
            sec = {"_error": str(e)[:200]}
    liq = fnum((info or {}).get("liquidity"))
    pool = (info or {}).get("pool") or {}
    if not liq:
        liq = fnum(pool.get("liquidity") or token_row.get("liquidity"))
    honeypot = sec.get("is_honeypot") in (True, 1, "1", "yes", "YES") or sec.get("honeypot") in (True, 1, "1", "yes")
    sellable = not _explicit_unsellable(sec, cfg.chain)
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
    dev = (info or {}).get("dev") or {}
    price = (info or {}).get("price") if isinstance((info or {}).get("price"), dict) else {}
    px = fnum(price.get("price"))
    px_1h = fnum(price.get("price_1h"))
    ret_1h = ((px - px_1h) / px_1h) if px_1h > 0 and px > 0 else None
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
        "creator_address": (dev.get("creator_address") or "").lower(),
        "creator_token_status": dev.get("creator_token_status") or "",
        "creator_token_balance": fnum(dev.get("creator_token_balance")),
        "creator_open_count": int(dev.get("creator_open_count") or 0),
        "price": px,
        "ret_1h": ret_1h,
        "buy_vol_1h": fnum(price.get("buy_volume_1h")),
        "sell_vol_1h": fnum(price.get("sell_volume_1h")),
    }


def mc_range_for_lp(cfg: Config, lp: str) -> tuple[float, float]:
    """LP-aware MC window. bankr often opens above virtuals band."""
    lo, hi = float(cfg.min_mc), float(cfg.max_mc)
    if "bankr" in (lp or "").lower() and cfg.bankr_max_mc > hi:
        hi = float(cfg.bankr_max_mc)
    return lo, hi


def allowed_lp_names(cfg: Config) -> tuple[str, ...]:
    if cfg.allowed_lps:
        return tuple(x.lower() for x in cfg.allowed_lps if x)
    return SAFE_LP


def lp_allowed(cfg: Config, lp: str | None) -> bool:
    if not cfg.only_safe_lp:
        return True
    low = (lp or "").lower()
    return any(x in low for x in allowed_lp_names(cfg))


def effective_max_top10(cfg: Config, age: int | float | None) -> float:
    """Loosen holder concentration for true first-wave prints."""
    base = float(cfg.max_top10 or 0)
    if base <= 0:
        return 0.0
    if age is not None and age <= cfg.fresh_top10_age_sec:
        return max(base, float(cfg.max_top10_fresh or base))
    return base


def should_defer_unindexed_liq(cfg: Config, liq: float, age: int | float | None) -> bool:
    """liq==0 is often GMGN index lag, not empty pool — prove via quote."""
    return bool(
        cfg.allow_unindexed_liq
        and liq <= 0
        and age is not None
        and age <= cfg.fresh_max_age_sec
    )


def soft_retry_wait(cfg: Config, age: int | float | None = None) -> int:
    base = max(1, int(cfg.soft_retry_sec or 5))
    if age is not None and age <= 60:
        return min(base, 3)
    return base


def classify_entry(cfg: Config, snap: dict) -> tuple[str | None, str]:
    age = snap.get("age")
    create_age = snap.get("create_age")
    open_age = snap.get("open_age")
    fresh_age = open_age if open_age is not None else create_age
    min_age = max(0, int(cfg.fresh_min_age_sec or 0))
    if fresh_age is not None and fresh_age < min_age:
        return None, f"too_fresh age={fresh_age}s < {min_age}s"
    if fresh_age is not None and min_age <= fresh_age <= cfg.fresh_max_age_sec:
        return "fresh", f"age={fresh_age}s"
    if open_age is None and create_age is not None and min_age <= create_age <= cfg.fresh_max_age_sec * 2:
        return "fresh", f"preopen_create_age={create_age}s"
    if cfg.disable_reheat or cfg.reheat_max_age_sec <= 0:
        return None, f"stale age={age} (reheat off) vol1h={snap.get('vol_1h')} swaps1h={snap.get('swaps_1h')}"
    if age is not None and age <= cfg.reheat_max_age_sec:
        if snap["vol_1h"] >= cfg.reheat_min_vol_1h or snap["swaps_1h"] >= cfg.reheat_min_swaps_1h:
            return "reheat", f"age={age}s vol1h={snap['vol_1h']:.0f} swaps1h={snap['swaps_1h']}"
    return None, f"stale age={age} vol1h={snap.get('vol_1h')} swaps1h={snap.get('swaps_1h')}"


# Soft rejects: first-wave often shows liq=0 before pool indexes. Retry, don't 24h-ban.
SOFT_REJECT_PREFIXES = (
    "low_liq:",
    "mc_unknown",
    "snapshot_fail:",
    "timing:",
    "buy_quote_zero_out",
    "no_sell_route:",
    "no_buy_route:",
    "top10_pending:",
    "auth:",
    "hazard:",
)
SOFT_RETRY_SEC = 5  # legacy default; prefer cfg.soft_retry_sec


def is_soft_reject(reason: str) -> bool:
    r = str(reason or "")
    if r == "mc_unknown":
        return True
    return any(r.startswith(p) for p in SOFT_REJECT_PREFIXES)


def observe_liq_path(
    cfg: Config, addr: str, token_row: dict | None = None, n: int = 3, gap: float = 2.0,
) -> list[dict]:
    """Take n liquidity snapshots spaced by gap seconds (first is immediate)."""
    path: list[dict] = []
    n = max(1, int(n))
    for i in range(n):
        if i:
            time.sleep(max(0.2, float(gap)))
        snap = token_snapshot(cfg, addr, token_row, with_security=False)
        path.append({
            "ts": int(time.time()),
            "liq": fnum(snap.get("liquidity")),
            "mc": fnum(snap.get("mc")),
            "price": fnum(snap.get("price")),
        })
    return path


def hazard_from_liq_path(cfg: Config, path: list[dict]) -> str | None:
    if len(path) < 2:
        return None
    liqs = [fnum(p.get("liq")) for p in path]
    if any(x <= 0 for x in liqs):
        return None  # unindexed — not enough signal
    drops = []
    for a, b in zip(liqs, liqs[1:]):
        if a > 0:
            drops.append((a - b) / a * 100.0)
    max_drop = max(drops) if drops else 0.0
    if max_drop >= cfg.hazard_max_single_drop_pct:
        return f"liq_drop_{max_drop:.1f}pct"
    n_down = sum(1 for d in drops if d > 0.5)
    if n_down >= 2:
        return f"liq_down_snaps_{n_down}"
    # slope %/s over whole window
    t0, t1 = path[0].get("ts") or 0, path[-1].get("ts") or 0
    dt = max(1.0, float(t1 - t0))
    slope = (liqs[0] - liqs[-1]) / liqs[0] * 100.0 / dt
    if slope > 0.5:  # losing >0.5%/s
        return f"liq_slope_{slope:.2f}pct_s"
    return None


def sell_quote_ladder(cfg: Config, addr: str, planned_tokens: int) -> dict:
    """25/50/100/200% of planned token amount sell quotes."""
    out: dict = {"planned_tokens": planned_tokens}
    if planned_tokens <= 0:
        out["err"] = "no_planned"
        return out
    for tag, mult in (("q25", 0.25), ("q50", 0.5), ("q100", 1.0), ("q200", 2.0)):
        amt = max(1, int(planned_tokens * mult))
        try:
            sq = quote(cfg, addr, NATIVE, str(amt), cfg.slippage)
            eth = int(sq.get("output_amount") or 0) / 1e18
            out[tag] = eth
            out[f"{tag}_ok"] = eth > 0
        except AuthError:
            raise
        except Exception as e:
            out[tag] = 0.0
            out[f"{tag}_ok"] = False
            out[f"{tag}_err"] = str(e)[:120]
    return out


def hazard_from_depth(cfg: Config, ladder: dict, buy_eth: float) -> str | None:
    if buy_eth <= 0:
        return None
    q100 = fnum(ladder.get("q100"))
    q50 = fnum(ladder.get("q50"))
    if ladder.get("q100_ok") and q100 > 0:
        loss = (buy_eth - q100) / buy_eth * 100.0
        if loss > cfg.hazard_max_full_exit_loss_pct:
            return f"full_exit_loss_{loss:.1f}pct"
    if ladder.get("q50_ok") and ladder.get("q100_ok") and q50 > 0 and q100 > 0:
        # scale 50% quote to full notionally: 2*q50 vs q100
        imp_spread = abs(2 * q50 - q100) / buy_eth * 100.0
        if imp_spread > cfg.hazard_max_impact_spread_pct:
            return f"impact_spread_{imp_spread:.1f}pct"
    if not ladder.get("q200_ok") and ladder.get("q100_ok"):
        return "stress_200_missing"
    # jitter between 100 and 50-scaled
    if ladder.get("q50_ok") and ladder.get("q100_ok") and q50 > 0:
        jitter = abs(2 * q50 - q100) / max(2 * q50, 1e-12) * 100.0
        if jitter > cfg.hazard_max_quote_jitter_pct:
            return f"quote_jitter_{jitter:.1f}pct"
    return None


def compact_sell_ladder(ladder: dict | None) -> dict | None:
    """JSONL-safe sell ladder: numeric legs only (no huge errs)."""
    if not ladder:
        return None
    out: dict = {}
    for k in ("planned_tokens", "q25", "q50", "q100", "q200",
              "q25_ok", "q50_ok", "q100_ok", "q200_ok", "err"):
        if k in ladder and ladder[k] is not None:
            out[k] = ladder[k]
    return out or None


def compact_liq_path(path: list | None, max_n: int = 5) -> list | None:
    if not path:
        return None
    out = []
    for p in path[:max_n]:
        out.append({
            "ts": p.get("ts"),
            "liq": p.get("liq"),
            "mc": p.get("mc"),
        })
    return out


def gate_audit_fields(snap: dict | None) -> dict:
    """Pre-entry fields that MUST land on buy/shadow/reject for offline EV.

    Without these on *accepted* buys, hazard shadow cannot be scored
    (paper_ev2 lesson: all rejects died before hazard; buys omitted fields).
    """
    snap = snap or {}
    return {
        "age": snap.get("age"),
        "hazard_liq": snap.get("hazard_liq"),
        "hazard_depth": snap.get("hazard_depth"),
        "hazard_liq_err": snap.get("hazard_liq_err"),
        "liq_path": compact_liq_path(snap.get("liq_path")),
        "sell_ladder": compact_sell_ladder(snap.get("sell_ladder")),
    }


def pre_entry_gate(cfg: Config, token: dict) -> tuple[bool, str, dict]:
    addr = token["address"]
    lp = (token.get("_lp") or token.get("launchpad") or token.get("launchpad_platform") or "").lower()
    if not lp_allowed(cfg, lp):
        return False, f"unsafe_lp:{lp or 'unknown'}", {}
    mc_lo, mc_hi = mc_range_for_lp(cfg, lp)
    mc0 = fnum(token.get("usd_market_cap") or token.get("market_cap"))
    if mc0 > 0 and (mc0 < mc_lo * 0.5 or mc0 > mc_hi * 2):
        return False, f"mc_trench_out:{mc0:.0f}", {}
    try:
        snap = token_snapshot(cfg, addr, token)
    except AuthError:
        raise
    except Exception as e:
        return False, f"snapshot_fail:{e}", {}
    lp = snap["launchpad"] or lp
    mc_lo, mc_hi = mc_range_for_lp(cfg, lp)
    if not lp_allowed(cfg, lp):
        return False, f"unsafe_lp_live:{lp or 'unknown'}", snap
    if snap["honeypot"]:
        return False, "honeypot", snap
    if cfg.require_can_sell and _explicit_unsellable(snap["raw_sec"], cfg.chain):
        return False, "can_sell=false", snap
    age = snap.get("age")
    min_age = max(0, int(cfg.fresh_min_age_sec or 0))
    if age is not None and age < min_age:
        return False, f"timing:too_fresh age={age}s < {min_age}s", snap
    liq = fnum(snap.get("liquidity"))
    if liq < cfg.min_liquidity:
        if should_defer_unindexed_liq(cfg, liq, age):
            snap["liq_deferred"] = True  # prove route via quote below
        else:
            return False, f"low_liq:{liq:.0f}", snap
    if snap["sell_tax"] > 10 or snap["buy_tax"] > 10:
        return False, f"tax:{snap['buy_tax']}/{snap['sell_tax']}", snap
    top10_lim = effective_max_top10(cfg, age)
    top10 = fnum(snap.get("top10"))
    if top10_lim > 0 and top10 > top10_lim:
        # 1.0 with tiny age is usually incomplete holder index, not a finished rug print
        if top10 >= 0.99 and age is not None and age <= 30:
            return False, f"top10_pending:{top10}", snap
        return False, f"top10:{top10}", snap
    fh = fake_heat_reject(cfg, snap)
    if fh:
        return False, f"fake_heat:{fh}", snap
    cr = creator_reject(cfg, snap)
    if cr:
        return False, cr, snap
    mc = snap["mc"]
    if mc <= 0:
        # first-wave often has mc=0 until GMGN indexes — same trust-as-quote path as liq=0
        if cfg.allow_unindexed_liq and age is not None and age <= cfg.fresh_max_age_sec:
            snap["mc_deferred"] = True
        else:
            return False, "mc_unknown", snap
    elif mc < mc_lo or mc > mc_hi:
        return False, f"mc_out:{mc:.0f} not_in[{mc_lo:.0f},{mc_hi:.0f}]", snap
    mode, why = classify_entry(cfg, snap)
    if not mode:
        return False, f"timing:{why}", snap
    snap["entry_mode"] = mode
    snap["entry_why"] = why
    # cheap filters passed — optional multi-snap liq path (hazard)
    if cfg.hazard_mode in ("shadow", "enforce") and cfg.hazard_snap_n > 1:
        try:
            path = observe_liq_path(cfg, addr, token, n=cfg.hazard_snap_n, gap=cfg.hazard_snap_gap_sec)
            snap["liq_path"] = path
            hz = hazard_from_liq_path(cfg, path)
            snap["hazard_liq"] = hz
            if hz and cfg.hazard_mode == "enforce":
                return False, f"hazard:{hz}", snap
        except AuthError:
            raise
        except Exception as e:
            snap["hazard_liq_err"] = str(e)[:120]
    buy_eth = resolve_buy_eth(cfg)
    if buy_eth <= 0:
        return False, "buy_size_zero", snap
    snap["buy_eth"] = buy_eth
    amount = eth_to_wei(buy_eth)
    try:
        bq = quote(cfg, NATIVE, addr, amount, cfg.slippage)
        snap["buy_quote_out"] = bq.get("output_amount")
    except AuthError:
        raise
    except Exception as e:
        return False, f"no_buy_route:{e}", snap
    out_amt = str(bq.get("output_amount") or "0")
    if out_amt in ("0", "", "None"):
        return False, "buy_quote_zero_out", snap
    planned = int(out_amt)
    ladder = sell_quote_ladder(cfg, addr, planned)
    snap["sell_ladder"] = ladder
    if cfg.require_sell_quote and not ladder.get("q50_ok") and not ladder.get("q100_ok"):
        return False, f"no_sell_route:{ladder.get('err') or 'ladder_fail'}", snap
    if cfg.hazard_mode in ("shadow", "enforce"):
        dh = hazard_from_depth(cfg, ladder, buy_eth)
        snap["hazard_depth"] = dh
        if dh and cfg.hazard_mode == "enforce":
            return False, f"hazard:{dh}", snap
    return True, f"ok:{mode}", snap


def fetch_candidates(cfg: Config) -> list[dict]:
    data = sh([
        "gmgn-cli", "market", "trenches",
        "--chain", cfg.chain,
        "--type", "new_creation", "--type", "completed", "--type", "near_completion",
        "--limit", "50", "--raw",
    ], retries=1)
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
            if lp and not lp_allowed(cfg, lp):
                continue
            created = int(t.get("created_timestamp") or 0)
            opened = int(t.get("open_timestamp") or 0)
            create_age = (now - created) if created else None
            open_age = (now - opened) if opened else None
            age = open_age if open_age is not None else create_age
            if age is None:
                continue
            min_age = max(0, int(cfg.fresh_min_age_sec or 0))
            # keep slightly-too-fresh candidates so gate can wait; drop ancient noise later
            if age < max(0, min_age - 15):
                continue
            is_fresh = (
                (min_age <= age <= cfg.fresh_max_age_sec)
                or (create_age is not None and min_age <= create_age <= cfg.fresh_max_age_sec)
            )
            is_reheat_cand = (not cfg.disable_reheat) and cfg.reheat_max_age_sec > 0 and age <= cfg.reheat_max_age_sec and (
                fnum(t.get("volume_1h") or t.get("volume_24h")) >= cfg.reheat_min_vol_1h * 0.25
                or int(t.get("swaps_1h") or t.get("swaps_24h") or 0) >= max(5, cfg.reheat_min_swaps_1h // 3)
                or fnum(t.get("liquidity")) >= cfg.min_liquidity
            )
            if not (is_fresh or is_reheat_cand):
                continue
            if fnum(t.get("rug_ratio")) > cfg.max_rug:
                continue
            mc = fnum(t.get("usd_market_cap") or t.get("market_cap"))
            mc_lo, mc_hi = mc_range_for_lp(cfg, lp)
            if mc > 0 and (mc < mc_lo * 0.3 or mc > mc_hi * 3):
                continue
            t["_age"] = age
            t["_cat"] = cat
            t["_lp"] = lp
            t["_fresh"] = is_fresh
            t["_server_order"] = len([x for x in out if x.get("_cat") == cat])
            out.append(t)
    out.sort(key=lambda x: (0 if x.get("_fresh") else 1, -fnum(x.get("volume_1h") or x.get("volume_24h")), x.get("_age", 1e18)))
    for i, t in enumerate(out):
        t["_client_rank"] = i
    return out


def buy(cfg: Config, token: str, symbol: str, buy_eth: float | None = None) -> dict:
    size = buy_eth if buy_eth is not None else resolve_buy_eth(cfg)
    amount = eth_to_wei(size)
    cond = condition_orders(cfg)
    if not cfg.live:
        q = quote(cfg, NATIVE, token, amount, cfg.slippage)
        return {
            "mode": "dry-run",
            "symbol": symbol,
            "token": token,
            "buy_eth": size,
            "amount_wei": amount,
            "quote_ok": bool(q),
            "quote_out": q.get("output_amount"),
            "order_status": "dry-run",
            "strategy_ok": True,
        }
    cmd = [
        "gmgn-cli", "swap", "--chain", cfg.chain, "--from", cfg.wallet,
        "--input-token", NATIVE, "--output-token", token, "--amount", amount,
        "--slippage", str(cfg.slippage), "--condition-orders", cond, "--sell-ratio-type", "buy_amount",
    ]
    if cfg.anti_mev:
        cmd.append("--anti-mev")
    cmd.append("--raw")
    result = sh(cmd, timeout=90, retries=0)
    oid = extract_order_id(result if isinstance(result, dict) else None)
    sid = extract_strategy_id(result if isinstance(result, dict) else None)
    conf = wait_order(cfg, oid)
    out = {
        "mode": "live",
        "symbol": symbol,
        "token": token,
        "buy_eth": size,
        "result": result,
        "order_id": oid,
        "strategy_order_id": sid,
        "order_status": conf.get("status"),
        "strategy_ok": bool(sid),
    }
    if conf.get("status") == "failed":
        out["error"] = "order_failed"
    if cfg.local_exit_if_no_strategy and not sid:
        out["warn"] = "no_strategy_order_id"
        log_event({"event": "strategy_missing", "token": token, "symbol": symbol, "order_id": oid})
    return out


def _ensure_paper_inventory(meta: dict) -> None:
    """Backfill inventory fields for positions opened before exec-quote paper."""
    if meta.get("remaining_tokens") is not None and meta.get("remaining_cost_basis") is not None:
        return
    tok = str(meta.get("quote_out") or meta.get("initial_tokens") or "0")
    try:
        tokens = int(tok)
    except Exception:
        tokens = 0
    buy_eth = fnum(meta.get("buy_eth"))
    meta.setdefault("initial_tokens", str(tokens))
    meta["remaining_tokens"] = str(tokens)
    meta["remaining_cost_basis"] = buy_eth
    meta.setdefault("realized_eth", 0.0)
    meta.setdefault("sold_tokens", "0")
    meta.setdefault("tp1_filled", False)
    meta.setdefault("tp2_filled", False)
    meta.setdefault("tp3_filled", False)
    meta.setdefault("peak_executable_return", 0.0)
    meta.setdefault("unpriced_streak", 0)


def _paper_sell_quote(cfg: Config, addr: str, token_amount: str) -> tuple[bool, float, str]:
    if not token_amount or token_amount in ("0", "None"):
        return False, 0.0, "zero_tokens"
    try:
        sq = quote(cfg, addr, NATIVE, str(token_amount), cfg.slippage)
        out_eth = int(sq.get("output_amount") or 0) / 1e18
        if out_eth <= 0:
            return False, 0.0, "zero_out"
        return True, out_eth, ""
    except AuthError:
        raise
    except Exception as e:
        return False, 0.0, str(e)[:200]


def _paper_exec_exit(
    cfg: Config, meta: dict, exec_ret_pct: float,
) -> tuple[str | None, float]:
    """Match TP/SL/trail on executable return % (full remaining exit). Returns (reason, sell_ratio_pct)."""
    sl = fnum(cfg.hard_sl_pct or cfg.sl)
    if exec_ret_pct <= -sl:
        return f"hard_sl_{exec_ret_pct:.1f}pct", 100.0
    for scale, ratio, tag, filled_key in (
        (cfg.tp1, cfg.tp1_pct, "tp1", "tp1_filled"),
        (cfg.tp2, cfg.tp2_pct, "tp2", "tp2_filled"),
        (cfg.tp3, cfg.tp3_pct, "tp3", "tp3_filled"),
    ):
        if ratio <= 0 or meta.get(filled_key):
            continue
        if exec_ret_pct >= float(scale):
            return f"{tag}_{exec_ret_pct:.1f}pct", float(ratio)
    if cfg.use_trailing:
        peak = fnum(meta.get("peak_executable_return"))
        act = fnum(cfg.trail_activate_pct)
        dd = fnum(cfg.trail_drawdown_pct)
        if peak * 100.0 >= act and dd > 0:
            draw = (peak - exec_ret_pct / 100.0) / max(peak, 1e-12) * 100.0
            if draw >= dd:
                return f"trail_dd_{draw:.1f}pct", 100.0
    return None, 0.0


def _paper_apply_realized(st: dict, pnl: float) -> None:
    st["paper_realized_est"] = fnum(st.get("paper_realized_est")) + pnl
    eth_usd = fnum(os.environ.get("RH_ETH_USD"), 1000.0) or 1000.0
    st["day_realized_est"] = fnum(st.get("day_realized_est")) + pnl * eth_usd


def _paper_partial_or_close(
    cfg: Config,
    addr: str,
    meta: dict,
    sym: str,
    reason: str,
    sell_ratio_pct: float,
    out_eth_full: float,
    st: dict,
    *,
    quote_ok: bool,
    quote_err: str = "",
    exec_ret_pct: float | None = None,
) -> dict | None:
    """Sell sell_ratio_pct of remaining tokens via pro-rata full-exit quote. None if still open."""
    _ensure_paper_inventory(meta)
    rem_tok = int(meta.get("remaining_tokens") or 0)
    rem_cost = fnum(meta.get("remaining_cost_basis"))
    if rem_tok <= 0 or rem_cost <= 0:
        return {"event": "paper_exit", "symbol": sym, "token": addr, "reason": reason, "pnl_eth_est": 0.0}
    ratio = max(0.0, min(100.0, float(sell_ratio_pct))) / 100.0
    if ratio <= 0:
        return None
    sell_tok = rem_tok if ratio >= 0.999 else max(1, int(rem_tok * ratio))
    sell_tok = min(sell_tok, rem_tok)
    frac = sell_tok / rem_tok
    out_eth = out_eth_full * frac if quote_ok else 0.0
    cost_sold = rem_cost * frac
    if not quote_ok:
        # unpriced: do not invent PnL; keep position and log
        meta["unpriced_streak"] = int(meta.get("unpriced_streak") or 0) + 1
        log_event({
            "event": "unpriced_interval",
            "symbol": sym,
            "token": addr,
            "reason": reason,
            "quote_err": quote_err or None,
            "unpriced_streak": meta["unpriced_streak"],
        })
        return None
    pnl = out_eth - cost_sold
    meta["realized_eth"] = fnum(meta.get("realized_eth")) + pnl
    meta["remaining_tokens"] = str(rem_tok - sell_tok)
    meta["remaining_cost_basis"] = rem_cost - cost_sold
    meta["sold_tokens"] = str(int(meta.get("sold_tokens") or 0) + sell_tok)
    meta["unpriced_streak"] = 0
    meta["last_quote_ok"] = True
    _paper_apply_realized(st, pnl)
    for tag, key in (("tp1", "tp1_filled"), ("tp2", "tp2_filled"), ("tp3", "tp3_filled")):
        if reason.startswith(tag):
            meta[key] = True
    closed = int(meta["remaining_tokens"] or 0) <= 0 or ratio >= 0.999
    base = {
        "mode": "dry-run",
        "symbol": sym,
        "token": addr,
        "reason": reason,
        "buy_eth": fnum(meta.get("buy_eth")),
        "sold_tokens": str(sell_tok),
        "remaining_tokens": meta["remaining_tokens"],
        "out_eth_est": out_eth,
        "pnl_eth_est": pnl,
        "exec_ret_pct": exec_ret_pct,
        "quote_ok": True,
        "paper_total_est": st.get("paper_realized_est"),
        "realized_eth_pos": meta.get("realized_eth"),
    }
    if closed:
        # inventory conservation check
        init = int(meta.get("initial_tokens") or 0)
        sold = int(meta.get("sold_tokens") or 0)
        rem = int(meta.get("remaining_tokens") or 0)
        base["event"] = "paper_exit"
        base["inventory_ok"] = (init == sold + rem) if init else True
        base["pnl_eth_est"] = fnum(meta.get("realized_eth"))  # full lifecycle realized
        log_event(base)
        return base
    base["event"] = "paper_partial_exit"
    log_event(base)
    return None  # still open


def emergency_sell(cfg: Config, token: str, symbol: str, reason: str) -> dict:
    if not cfg.live:
        return {"mode": "dry-run", "event": "emergency_sell", "symbol": symbol, "token": token, "reason": reason}
    cmd = [
        "gmgn-cli", "swap", "--chain", cfg.chain, "--from", cfg.wallet,
        "--input-token", token, "--output-token", NATIVE, "--percent", "100",
        "--slippage", str(cfg.emergency_slippage),
    ]
    if cfg.anti_mev:
        cmd.append("--anti-mev")
    cmd.append("--raw")
    result = sh(cmd, timeout=90, retries=0)
    oid = extract_order_id(result if isinstance(result, dict) else None)
    conf = wait_order(cfg, oid)
    return {
        "mode": "live",
        "event": "emergency_sell",
        "symbol": symbol,
        "token": token,
        "reason": reason,
        "result": result,
        "order_id": oid,
        "order_status": conf.get("status"),
    }


def probe_trade(cfg: Config, token: str, symbol: str) -> tuple[bool, str, dict]:
    if cfg.probe_eth <= 0:
        return True, "probe_off", {}
    amt = eth_to_wei(cfg.probe_eth)
    meta: dict = {"probe_eth": cfg.probe_eth, "symbol": symbol, "token": token}
    try:
        bq = quote(cfg, NATIVE, token, amt, cfg.slippage)
        out = str(bq.get("output_amount") or "0")
        if out in ("0", ""):
            return False, "probe_buy_quote_zero", meta
        quote(cfg, token, NATIVE, out, cfg.emergency_slippage)
    except Exception as e:
        return False, f"probe_quote_fail:{e}", meta
    if not cfg.live:
        meta["mode"] = "dry-run"
        return True, "probe_quote_ok", meta
    try:
        buy_cmd = ["gmgn-cli", "swap", "--chain", cfg.chain, "--from", cfg.wallet, "--input-token", NATIVE, "--output-token", token, "--amount", amt, "--slippage", str(cfg.slippage)]
        if cfg.anti_mev:
            buy_cmd.append("--anti-mev")
        buy_cmd.append("--raw")
        br = sh(buy_cmd, timeout=90, retries=0)
        meta["buy_result"] = br
        meta["buy_order"] = wait_order(cfg, extract_order_id(br if isinstance(br, dict) else None))
        sell_cmd = ["gmgn-cli", "swap", "--chain", cfg.chain, "--from", cfg.wallet, "--input-token", token, "--output-token", NATIVE, "--percent", "100", "--slippage", str(cfg.emergency_slippage)]
        if cfg.anti_mev:
            sell_cmd.append("--anti-mev")
        sell_cmd.append("--raw")
        sr = sh(sell_cmd, timeout=90, retries=0)
        meta["sell_result"] = sr
        meta["sell_order"] = wait_order(cfg, extract_order_id(sr if isinstance(sr, dict) else None))
        meta["mode"] = "live"
        if meta.get("sell_order", {}).get("status") == "failed":
            return False, "probe_sell_failed", meta
        return True, "probe_ok", meta
    except Exception as e:
        try:
            emergency_sell(cfg, token, symbol, "probe_fail_cleanup")
        except Exception:
            pass
        return False, f"probe_live_fail:{e}", meta


def monitor_positions(cfg: Config, st: dict, with_security: bool = False) -> None:
    pos = st.get("positions") or {}
    if not pos:
        return
    dead = []
    for addr, meta in list(pos.items()):
        is_paper = (meta.get("mode") == "dry-run" and not cfg.live)
        if is_paper and not cfg.paper_positions:
            continue
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
        sell_ratio = 100.0
        exec_ret_pct = None
        out_eth_full = 0.0
        quote_ok = False
        quote_err = ""
        if is_paper:
            _ensure_paper_inventory(meta)
            rem_tok = str(meta.get("remaining_tokens") or "0")
            rem_cost = fnum(meta.get("remaining_cost_basis"))
            quote_ok, out_eth_full, quote_err = _paper_sell_quote(cfg, addr, rem_tok)
            if quote_ok and rem_cost > 0:
                exec_ret = out_eth_full / rem_cost - 1.0
                exec_ret_pct = exec_ret * 100.0
                peak = max(fnum(meta.get("peak_executable_return")), exec_ret)
                meta["peak_executable_return"] = peak
                meta["last_exec_ret_pct"] = exec_ret_pct
                meta["last_quote_ok"] = True
                meta["unpriced_streak"] = 0
                log_event({
                    "event": "paper_quote_tick",
                    "symbol": sym,
                    "token": addr,
                    "remaining_tokens": rem_tok,
                    "out_eth": out_eth_full,
                    "exec_ret_pct": exec_ret_pct,
                    "peak_exec_ret": peak,
                    "quote_ok": True,
                })
                reason, sell_ratio = _paper_exec_exit(cfg, meta, exec_ret_pct)
            else:
                meta["last_quote_ok"] = False
                meta["unpriced_streak"] = int(meta.get("unpriced_streak") or 0) + 1
                log_event({
                    "event": "paper_quote_tick",
                    "symbol": sym,
                    "token": addr,
                    "remaining_tokens": rem_tok,
                    "quote_ok": False,
                    "quote_err": quote_err,
                    "unpriced_streak": meta["unpriced_streak"],
                })
        if with_security and (snap["honeypot"] or _explicit_unsellable(snap["raw_sec"], cfg.chain)):
            reason = "unsellable_or_honeypot"
            sell_ratio = 100.0
        elif entry_liq > 0 and drop >= cfg.lp_drop_pct:
            reason = f"lp_drop_{drop:.0f}pct"
            sell_ratio = 100.0
        elif liq > 0 and liq < cfg.min_liq_hold:
            reason = f"liq_floor_{liq:.0f}"
            sell_ratio = 100.0
        elif held >= cfg.max_hold_sec:
            reason = f"max_hold_{held}s"
            sell_ratio = 100.0
        # local exit if strategy missing and held long enough
        if (
            cfg.live
            and cfg.local_exit_if_no_strategy
            and meta.get("strategy_ok") is False
            and held >= min(60, cfg.max_hold_sec)
        ):
            reason = reason or "no_strategy_timeout"
            sell_ratio = 100.0
        entry_cbal = fnum(meta.get("creator_token_balance"))
        cbal = fnum(snap.get("creator_token_balance"))
        if with_security and entry_cbal > 0 and cbal < entry_cbal * 0.5:
            reason = reason or f"creator_dump {entry_cbal:.0f}->{cbal:.0f}"
            sell_ratio = 100.0
        print(
            f"[mon] {sym} held={held}s liq={liq:.0f} entry={entry_liq:.0f} drop={drop:.1f}% "
            f"sec={int(with_security)} can_sell={snap['can_sell']}"
            + (f" exec={exec_ret_pct:+.1f}%" if is_paper and exec_ret_pct is not None else ""),
            flush=True,
        )
        if not reason:
            meta["last_liq"] = liq
            meta["last_check"] = int(time.time())
            if with_security:
                meta["creator_token_balance"] = cbal
                meta["creator_token_status"] = snap.get("creator_token_status")
            continue
        print(f"[RUG_EXIT] {sym} reason={reason}", flush=True)
        try:
            if is_paper:
                # need full quote for full exits if we only had unpriced tick
                if not quote_ok:
                    quote_ok, out_eth_full, quote_err = _paper_sell_quote(
                        cfg, addr, str(meta.get("remaining_tokens") or "0")
                    )
                closed = _paper_partial_or_close(
                    cfg, addr, meta, sym, reason, sell_ratio, out_eth_full, st,
                    quote_ok=quote_ok, quote_err=quote_err, exec_ret_pct=exec_ret_pct,
                )
                if closed:
                    print(
                        f"[paper_exit] {sym} {closed.get('reason', reason)} "
                        f"pnl≈{closed.get('pnl_eth_est', 0):+.6f} ETH "
                        f"total≈{st.get('paper_realized_est', 0):+.6f} ETH",
                        flush=True,
                    )
                    dead.append(addr)
                else:
                    print(f"[paper_partial] {sym} {reason} rem={meta.get('remaining_tokens')}", flush=True)
            else:
                res = emergency_sell(cfg, addr, sym, reason)
                log_event({**res, "entry_liq": entry_liq, "liq": liq, "drop_pct": drop, "held": held})
                dead.append(addr)
        except AuthError:
            raise
        except Exception as e:
            log_event({"event": "emergency_sell_error", "token": addr, "symbol": sym, "error": str(e)[:300]})
            print(f"[RUG_EXIT_ERR] {sym}: {e}", flush=True)
    for a in dead:
        st["positions"].pop(a, None)


def prune_seen(st: dict, keep_sec: int = 86400) -> None:
    now = int(time.time())
    st["seen"] = {k: v for k, v in st["seen"].items() if now - int(v) < keep_sec}
    soft = st.get("soft_seen") or {}
    st["soft_seen"] = {k: v for k, v in soft.items() if now - int(v) < keep_sec}


def rollover_day(st: dict) -> None:
    day = time.strftime("%Y-%m-%d")
    if st.get("day") != day:
        st["day"] = day
        st["day_realized_est"] = 0.0
        st["buys_today"] = 0
        st["session_start_realized"] = None


def parse_active_hours_cn(spec: str) -> list[tuple[int, int]] | None:
    if not spec:
        return None
    s = spec.strip().lower()
    if s in ("", "all", "24h", "24", "*"):
        return None
    windows: list[tuple[int, int]] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            raise ValueError(f"bad active hours segment: {part}")
        a, b = part.split("-", 1)
        start, end = int(a), int(b)
        if not (0 <= start <= 23 and 0 <= end <= 23):
            raise ValueError(f"hours must be 0-23: {part}")
        windows.append((start, end))
    return windows or None


def hour_in_windows(hour: int, windows: list[tuple[int, int]] | None) -> bool:
    if not windows:
        return True
    for start, end in windows:
        if start == end:
            return True
        if start < end:
            if start <= hour < end:
                return True
        else:
            if hour >= start or hour < end:
                return True
    return False


def is_active_session(cfg: Config, now: datetime | None = None) -> tuple[bool, int, str]:
    tz = timezone(timedelta(hours=int(cfg.timezone_offset_hours)))
    now = now or datetime.now(tz=timezone.utc)
    local = now.astimezone(tz)
    hour = local.hour
    try:
        windows = parse_active_hours_cn(cfg.active_hours_cn)
    except Exception as e:
        return True, hour, f"bad_hours:{e}"
    active = hour_in_windows(hour, windows)
    label = f"CN{hour:02d} {'ACTIVE' if active else 'REST'} window={cfg.active_hours_cn or '24h'}"
    return active, hour, label


def loop(cfg: Config) -> None:
    st = load_state()
    tick = 0
    est = 3 + cfg.max_positions + (4 * cfg.max_gates_per_tick) / max(cfg.gate_every, 1)
    print(
        f"[start] profile={cfg.profile} buy={cfg.buy_eth}ETH mc=[{cfg.min_mc:.0f},{cfg.max_mc:.0f}] "
        f"bankr_mc<={cfg.bankr_max_mc:.0f} fresh={cfg.fresh_min_age_sec}-{cfg.fresh_max_age_sec}s "
        f"reheat={'OFF' if cfg.disable_reheat else cfg.reheat_min_vol_1h} "
        f"min_liq={cfg.min_liquidity} top10={cfg.max_top10}/{cfg.max_top10_fresh}@{cfg.fresh_top10_age_sec}s "
        f"unindexed_liq={cfg.allow_unindexed_liq} live={cfg.live}",
        flush=True,
    )
    print(
        f"[pace] poll={cfg.poll_sec}s gate_every={cfg.gate_every} max_gates={cfg.max_gates_per_tick} "
        f"mon_sec_every={cfg.mon_security_every} ~weight/s≈{est / cfg.poll_sec:.1f} (cap 20)",
        flush=True,
    )
    print(
        f"[exits] mode={cfg.exit_mode} TP {cfg.tp1}/{cfg.tp1_pct}+{cfg.tp2}/{cfg.tp2_pct}+{cfg.tp3}/{cfg.tp3_pct} "
        f"trail@{cfg.trail_activate_pct}% dd{cfg.trail_drawdown_pct}% SL -{cfg.hard_sl_pct}% "
        f"max_hold={cfg.max_hold_sec}s lp_drop={cfg.lp_drop_pct}%",
        flush=True,
    )
    print(
        f"[session] active_hours_cn={cfg.active_hours_cn or '24h'} offhours={cfg.offhours_mode} "
        f"tz=UTC+{cfg.timezone_offset_hours}",
        flush=True,
    )
    print(f"[runtime] state={STATE_PATH} log={LOG_PATH} scan={SCAN_LOG_PATH} paper_positions={cfg.paper_positions}", flush=True)
    print(
        f"[filters] lps={','.join(allowed_lp_names(cfg))} min_age={cfg.fresh_min_age_sec}s "
        f"max_age={cfg.fresh_max_age_sec}s unindexed_liq={cfg.allow_unindexed_liq} "
        f"shadow={cfg.shadow_collect} hazard={cfg.hazard_mode} scan_log={cfg.scan_log_enabled}",
        flush=True,
    )

    rate_limit_until = 0.0

    while True:
        t0 = time.time()
        tick += 1
        try:
            if time.time() < rate_limit_until:
                sleep_left = rate_limit_until - time.time()
                tag = "auth" if sleep_left >= cfg.auth_cooldown_sec * 0.8 else "rate_limit"
                print(f"[{tag}] cooling {sleep_left:.0f}s", flush=True)
                time.sleep(max(1.0, sleep_left))
                continue

            rollover_day(st)
            prune_seen(st)

            if cfg.live and (tick % max(cfg.pnl_refresh_every, 1) == 1 or cfg.once):
                refresh_day_pnl(cfg, st)

            active, local_hour, sess_label = is_active_session(cfg)
            do_sec = (tick % max(cfg.mon_security_every, 1) == 0) or cfg.once or (not active and bool(st.get("positions")))
            try:
                monitor_positions(cfg, st, with_security=do_sec)
            except AuthError as e:
                cool = max(float(cfg.auth_cooldown_sec), float(e.sleep_s))
                rate_limit_until = time.time() + cool
                log_event({"event": "auth_error", "sleep_s": cool, "where": "monitor", "error": str(e)[:200]})
                print(f"[auth] monitor cooldown {cool:.0f}s: {e}", flush=True)
                continue
            except RateLimitError as e:
                rate_limit_until = time.time() + e.sleep_s
                log_event({"event": "rate_limit", "sleep_s": e.sleep_s, "where": "monitor"})
                continue
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

            if not active and not cfg.once:
                if open_n:
                    sleep_s = min(cfg.poll_sec * 2, 15.0)
                    if tick % 10 == 1:
                        print(f"[rest] {sess_label} open={open_n} mon-only sleep={sleep_s}s", flush=True)
                    time.sleep(max(0.0, sleep_s - (time.time() - t0)))
                    continue
                sleep_s = max(30.0, float(cfg.offhours_poll_sec))
                if tick % 3 == 1:
                    print(f"[rest] {sess_label} no new entries, sleep={sleep_s:.0f}s", flush=True)
                time.sleep(max(0.0, sleep_s - (time.time() - t0)))
                continue

            if open_n < cfg.max_positions:
                try:
                    cands = fetch_candidates(cfg)
                except AuthError as e:
                    cool = max(float(cfg.auth_cooldown_sec), float(e.sleep_s))
                    rate_limit_until = time.time() + cool
                    log_event({"event": "auth_error", "sleep_s": cool, "where": "trenches", "error": str(e)[:200]})
                    print(f"[auth] trenches cooldown {cool:.0f}s: {e}", flush=True)
                    continue
                except RateLimitError as e:
                    rate_limit_until = time.time() + e.sleep_s
                    log_event({"event": "rate_limit", "sleep_s": e.sleep_s, "where": "trenches"})
                    continue
                except Exception as e:
                    print(f"[err] trenches: {e}", flush=True)
                    cands = []
                print(
                    f"[scan] tick={tick} cands={len(cands)} open={open_n} buys_today={st.get('buys_today', 0)} "
                    f"gate={'Y' if tick % max(cfg.gate_every, 1) == 0 or cfg.once else 'N'} day_pnl={st.get('day_realized_est', 0):.2f}",
                    flush=True,
                )
                if cands and (tick % max(cfg.gate_every, 1) == 0 or cfg.once):
                    checked = 0
                    scan_ts = int(time.time())
                    scan_rows: list[dict] = []
                    for tok in cands:
                        scan_rows.append({
                            "event": "scan_candidate",
                            "scan_ts": scan_ts,
                            "tick": tick,
                            "category": tok.get("_cat"),
                            "token": (tok.get("address") or "").lower(),
                            "symbol": tok.get("symbol") or "?",
                            "server_order": tok.get("_server_order"),
                            "client_rank": tok.get("_client_rank"),
                            "age": tok.get("_age"),
                            "lp": tok.get("_lp"),
                            "mc": fnum(tok.get("usd_market_cap") or tok.get("market_cap")),
                            "liq": fnum(tok.get("liquidity")),
                            "vol_1h": fnum(tok.get("volume_1h") or tok.get("volume_24h")),
                            "was_selected_for_gate": False,
                            "not_selected_reason": "pending",
                            "gate_result": None,
                        })
                    row_by_addr = {r["token"]: r for r in scan_rows if r.get("token")}
                    try:
                        soft_seen = st.setdefault("soft_seen", {})
                        now_i = int(time.time())
                        bought_break = False
                        for tok in cands:
                            if bought_break:
                                break
                            addr = tok["address"].lower()
                            row = row_by_addr.get(addr)
                            if checked >= cfg.max_gates_per_tick:
                                if row and row.get("not_selected_reason") == "pending":
                                    row["not_selected_reason"] = "beyond_max_gates"
                                # mark remaining
                                for r in scan_rows:
                                    if r.get("not_selected_reason") == "pending" and r["token"] != addr:
                                        if r["client_rank"] is not None and tok.get("_client_rank") is not None:
                                            if r["client_rank"] >= tok.get("_client_rank", 0):
                                                r["not_selected_reason"] = "beyond_max_gates"
                                break
                            if addr in st["seen"] or addr in (st.get("positions") or {}):
                                if row:
                                    row["not_selected_reason"] = "already_seen" if addr in st["seen"] else "has_position"
                                continue
                            soft_ts = int(soft_seen.get(addr) or 0)
                            age_hint = tok.get("_age")
                            if soft_ts and now_i - soft_ts < soft_retry_wait(cfg, age_hint):
                                if row:
                                    row["not_selected_reason"] = "soft_cooldown"
                                continue
                            sym = tok.get("symbol") or "?"
                            checked += 1
                            gate_started = int(time.time())
                            if row:
                                row["was_selected_for_gate"] = True
                                row["not_selected_reason"] = None
                                row["gate_started_ts"] = gate_started
                            try:
                                ok, reason, snap = pre_entry_gate(cfg, tok)
                            except AuthError as e:
                                cool = max(float(cfg.auth_cooldown_sec), float(e.sleep_s))
                                rate_limit_until = time.time() + cool
                                log_event({"event": "auth_error", "sleep_s": cool, "where": "gate", "error": str(e)[:200]})
                                print(f"[auth] gate cooldown {cool:.0f}s: {e}", flush=True)
                                if row:
                                    row["gate_result"] = "auth_error"
                                break
                            except RateLimitError as e:
                                rate_limit_until = time.time() + e.sleep_s
                                log_event({"event": "rate_limit", "sleep_s": e.sleep_s, "where": "gate"})
                                if row:
                                    row["gate_result"] = "rate_limit"
                                break
                            if row:
                                row["gate_finished_ts"] = int(time.time())
                                row["gate_result"] = "ok" if ok else f"reject:{reason}"
                            if not ok:
                                soft = is_soft_reject(reason)
                                age_now = snap.get("age") if snap else age_hint
                                if soft and age_now is not None and age_now > cfg.fresh_max_age_sec and str(reason).startswith(
                                    ("low_liq:", "top10_pending:", "no_buy_route:", "buy_quote_zero_out")
                                ):
                                    soft = False
                                if soft:
                                    soft_seen[addr] = now_i
                                else:
                                    st["seen"][addr] = now_i
                                    soft_seen.pop(addr, None)
                                log_event({
                                    "event": "reject", "token": addr, "symbol": sym, "reason": reason,
                                    "mc": snap.get("mc"), "liq": snap.get("liquidity"),
                                    "lp": snap.get("launchpad") or tok.get("_lp"),
                                    "soft": soft,
                                    "client_rank": tok.get("_client_rank"),
                                    "scan_ts": scan_ts,
                                    "gate_started_ts": gate_started,
                                    **gate_audit_fields(snap),
                                })
                                print(f"[reject] {sym} {reason} mc={snap.get('mc', 0):.0f} liq={snap.get('liquidity', 0):.0f}", flush=True)
                                continue
                            st["seen"][addr] = now_i
                            soft_seen.pop(addr, None)
                            print(
                                f"[signal] {sym} mode={snap.get('entry_mode')} mc=${snap.get('mc', 0):.0f} "
                                f"liq={snap.get('liquidity', 0):.0f} buy={snap.get('buy_eth', cfg.buy_eth)} "
                                f"age={snap.get('age')} {snap.get('entry_why')} {addr[:12]}…",
                                flush=True,
                            )
                            try:
                                if cfg.shadow_collect:
                                    log_event({
                                        "event": "shadow_signal",
                                        "token": addr,
                                        "symbol": sym,
                                        "mode": snap.get("entry_mode"),
                                        "mc": snap.get("mc"),
                                        "liq": snap.get("liquidity"),
                                        "lp": snap.get("launchpad") or tok.get("_lp"),
                                        "client_rank": tok.get("_client_rank"),
                                        "scan_ts": scan_ts,
                                        **gate_audit_fields(snap),
                                    })
                                    print(f"[shadow] skip buy {sym}", flush=True)
                                    continue
                                if cfg.probe_eth > 0:
                                    pok, preason, pmeta = probe_trade(cfg, tok["address"], sym)
                                    log_event({
                                        "event": "probe", "ok": pok, "reason": preason, "symbol": sym,
                                        "token": addr, "probe_eth": pmeta.get("probe_eth"), "mode": pmeta.get("mode"),
                                    })
                                    if not pok:
                                        print(f"[probe_fail] {sym} {preason}", flush=True)
                                        continue
                                    print(f"[probe_ok] {sym} {preason}", flush=True)
                                next_size = float(snap.get("buy_eth") or resolve_buy_eth(cfg))
                                ok_exp, exp_reason = exposure_ok(cfg, st, next_size)
                                if not ok_exp:
                                    st["seen"].pop(addr, None)
                                    soft_seen[addr] = int(time.time())
                                    log_event({
                                        "event": "reject", "token": addr, "symbol": sym, "reason": exp_reason,
                                        "soft": True, "client_rank": tok.get("_client_rank"), "scan_ts": scan_ts,
                                    })
                                    print(f"[reject] {sym} {exp_reason}", flush=True)
                                    continue
                                res = buy(cfg, tok["address"], sym, buy_eth=next_size)
                                if res.get("order_status") == "failed":
                                    log_event({"event": "buy_failed", **{k: v for k, v in res.items() if k != "result"}})
                                    print(f"[buy_failed] {sym} order_status=failed", flush=True)
                                    continue
                                entry_liq = snap.get("liquidity") or fnum(tok.get("liquidity"))
                                log_event({
                                    "event": "buy",
                                    **{k: v for k, v in res.items() if k != "result"},
                                    "entry_liq": entry_liq,
                                    "mc": snap.get("mc"),
                                    "mode": snap.get("entry_mode"),
                                    "why": snap.get("entry_why"),
                                    "lp": snap.get("launchpad") or tok.get("_lp"),
                                    "client_rank": tok.get("_client_rank"),
                                    "scan_ts": scan_ts,
                                    **gate_audit_fields(snap),
                                })
                                if cfg.live or cfg.paper_positions:
                                    q_out = str(res.get("quote_out") or "0")
                                    try:
                                        init_tok = int(q_out)
                                    except Exception:
                                        init_tok = 0
                                    st.setdefault("positions", {})[addr] = {
                                        "symbol": sym,
                                        "ts": int(time.time()),
                                        "buy_eth": next_size,
                                        "entry_liq": entry_liq,
                                        "entry_mc": snap.get("mc"),
                                        "entry_price": snap.get("price"),
                                        "quote_out": q_out,
                                        "initial_tokens": str(init_tok),
                                        "remaining_tokens": str(init_tok),
                                        "remaining_cost_basis": next_size,
                                        "realized_eth": 0.0,
                                        "sold_tokens": "0",
                                        "tp1_filled": False,
                                        "tp2_filled": False,
                                        "tp3_filled": False,
                                        "peak_executable_return": 0.0,
                                        "unpriced_streak": 0,
                                        "entry_mode": snap.get("entry_mode"),
                                        "lp": snap.get("launchpad") or tok.get("_lp"),
                                        "mode": res.get("mode"),
                                        "order_id": res.get("order_id"),
                                        "strategy_order_id": res.get("strategy_order_id"),
                                        "strategy_ok": res.get("strategy_ok"),
                                        "order_status": res.get("order_status"),
                                        "creator_address": snap.get("creator_address"),
                                        "creator_token_balance": snap.get("creator_token_balance"),
                                        "creator_token_status": snap.get("creator_token_status"),
                                    }
                                st["buys_today"] = int(st.get("buys_today") or 0) + 1
                                print(
                                    f"[buy] {res.get('mode')} {sym} mc=${snap.get('mc', 0):.0f} liq={entry_liq:.0f} "
                                    f"order={res.get('order_status')} strategy_ok={res.get('strategy_ok')}",
                                    flush=True,
                                )
                                bought_break = True
                                for r in scan_rows:
                                    if r.get("not_selected_reason") == "pending":
                                        r["not_selected_reason"] = "bought_break"
                                break
                            except AuthError as e:
                                cool = max(float(cfg.auth_cooldown_sec), float(e.sleep_s))
                                rate_limit_until = time.time() + cool
                                log_event({"event": "auth_error", "sleep_s": cool, "where": "buy", "error": str(e)[:200]})
                                print(f"[auth] buy cooldown {cool:.0f}s: {e}", flush=True)
                                break
                            except RateLimitError as e:
                                rate_limit_until = time.time() + e.sleep_s
                                log_event({"event": "rate_limit", "sleep_s": e.sleep_s, "where": "buy"})
                                break
                            except Exception as e:
                                log_event({"event": "buy_error", "token": addr, "symbol": sym, "error": str(e)[:300]})
                                print(f"[buy_err] {sym}: {e}", flush=True)
                                break
                    finally:
                        if cfg.scan_log_enabled and scan_rows:
                            for r in scan_rows:
                                if r.get("not_selected_reason") == "pending":
                                    r["not_selected_reason"] = "not_reached"
                                log_scan_event(r)
                        save_state(st)

            if cfg.once:
                break
            time.sleep(max(0.0, cfg.poll_sec - (time.time() - t0)))
        except AuthError as e:
            cool = max(float(cfg.auth_cooldown_sec), float(e.sleep_s))
            rate_limit_until = time.time() + cool
            log_event({"event": "auth_error", "sleep_s": cool, "where": "loop", "error": str(e)[:200]})
            print(f"[auth] loop cooldown {cool:.0f}s: {e}", flush=True)
            time.sleep(cool)
        except RateLimitError as e:
            rate_limit_until = time.time() + e.sleep_s
            log_event({"event": "rate_limit", "sleep_s": e.sleep_s, "where": "loop"})
            time.sleep(e.sleep_s)
        except Exception as e:
            print(f"[loop_err] {e}", flush=True)
            time.sleep(max(1.0, cfg.poll_sec))


def apply_profile(cfg: Config, name: str, buy_eth_cli: float) -> None:
    """Parameter packs from reversed wallets — style, not address mirror."""
    cfg.profile = name
    if name == "adff":
        # 荒大宝-style scalp, recalibrated on paper100: skip bankr + age0-15, longer hold, lower TP
        cfg.buy_eth = 0.03 if buy_eth_cli == 0.03 else buy_eth_cli
        cfg.min_mc, cfg.max_mc = 1000, 50000
        cfg.bankr_max_mc = 80000
        cfg.fresh_min_age_sec = 30
        cfg.fresh_max_age_sec = 90
        cfg.disable_reheat = True
        cfg.reheat_min_vol_1h = 5000
        cfg.reheat_min_swaps_1h = 20
        cfg.min_liquidity = 30
        cfg.max_top10 = 0.70
        cfg.max_top10_fresh = 0.95
        cfg.fresh_top10_age_sec = 90
        cfg.allow_unindexed_liq = False  # unindexed first-wave correlated with lp_drop losses
        cfg.soft_retry_sec = 2
        cfg.allowed_lps = ("virtuals", "pons", "noxa", "trench", "flap")  # no bankr
        # TP lowered so full-clear can fire; hold stretched — 25s almost never hit +12%
        cfg.exit_mode = "hf_full"
        cfg.tp1, cfg.tp1_pct = 8, 100
        cfg.tp2, cfg.tp2_pct = 50, 0
        cfg.tp3, cfg.tp3_pct = 100, 0
        cfg.trail_activate_pct = 8
        cfg.trail_drawdown_pct = 25
        cfg.use_trailing = False
        cfg.hard_sl_pct = cfg.sl = 15
        cfg.max_hold_sec = 60
        cfg.lp_drop_pct = 25.0
        cfg.min_liq_hold = 0.0  # absolute floor kills micro-liq first-wave; rely on lp_drop %
        cfg.use_default_risk = False  # fixed size like $50 template
        cfg.default_risk_pct = 0
    elif name == "7a23":
        # 0xDavid: probe-ish mid size, $5-40k MC
        cfg.buy_eth = 0.06 if buy_eth_cli == 0.03 else buy_eth_cli
        cfg.min_mc, cfg.max_mc = 5000, 40000
        cfg.fresh_max_age_sec = 900
        cfg.reheat_min_vol_1h = 8000
        cfg.reheat_min_swaps_1h = 30
        cfg.min_liquidity = 2000
        # HF reverse of 0x7a23: probe + mid size; 1.1-1.5x sell ~30% then ladder; leave runner
        cfg.exit_mode = "hf_scale"
        cfg.tp1, cfg.tp1_pct = 25, 30    # ~1.25x sell 30% of bag
        cfg.tp2, cfg.tp2_pct = 50, 30    # ~1.5x sell another 30%
        cfg.tp3, cfg.tp3_pct = 100, 25   # 2x sell 25%
        # remainder 15% trailing
        cfg.trail_activate_pct = 50
        cfg.trail_drawdown_pct = 20
        cfg.use_trailing = True
        cfg.hard_sl_pct = cfg.sl = 30
        cfg.max_hold_sec = 300
        if cfg.probe_eth <= 0:
            cfg.probe_eth = 0.001  # 0xDavid-style probe default
        cfg.use_default_risk = True
        cfg.default_risk_pct = 1.0
    elif name == "417c":
        # heavier size, wider MC incl secondary heat
        cfg.buy_eth = 0.12 if buy_eth_cli == 0.03 else buy_eth_cli
        cfg.min_mc, cfg.max_mc = 8000, 50000
        cfg.fresh_max_age_sec = 1200
        cfg.reheat_min_vol_1h = 12000
        cfg.reheat_min_swaps_1h = 40
        cfg.min_liquidity = 3000
        # HF reverse of 0x417c: larger size; 1.1-1.5x sell ~25% then multi-sell ladder + residual bag
        cfg.exit_mode = "hf_scale"
        cfg.tp1, cfg.tp1_pct = 30, 25    # ~1.3x sell 25%
        cfg.tp2, cfg.tp2_pct = 80, 30    # ~1.8x sell 30%
        cfg.tp3, cfg.tp3_pct = 150, 25   # 2.5x sell 25%
        # remainder 20% trail for multi-hour runners
        cfg.trail_activate_pct = 80
        cfg.trail_drawdown_pct = 25
        cfg.use_trailing = True
        cfg.hard_sl_pct = cfg.sl = 35
        cfg.max_hold_sec = 3600  # can hold runners longer
        cfg.use_default_risk = True
        cfg.default_risk_pct = 1.25



def build_config(
    *,
    wallet: str | None = None,
    profile: str = "adff",
    buy_eth: float = 0.03,
    slippage: int = 30,
    poll: float = 1.0,
    gate_every: int = 2,
    max_gates: int = 2,
    mon_sec_every: int = 3,
    min_mc: float | None = None,
    max_mc: float | None = None,
    bankr_max_mc: float | None = None,
    min_liq: float | None = None,
    max_top10: float | None = None,
    max_top10_fresh: float | None = None,
    fresh_min_age: int | None = None,
    fresh_max_age: int | None = None,
    reheat_min_vol: float | None = None,
    allow_unindexed_liq: bool | None = None,
    disable_reheat: bool | None = None,
    soft_retry_sec: int | None = None,
    allowed_lps: str | None = None,
    lp_drop_pct: float = 35.0,
    min_liq_hold: float = 800.0,
    max_hold_sec: int | None = None,
    max_positions: int = 3,
    daily_loss_usd: float = 100.0,
    allow_uniswap: bool = False,
    live: bool = False,
    once: bool = False,
    paper_positions: bool | None = None,
    require_sell_quote: bool = True,
    probe_eth: float = 0.0,
    risk_pct: float = 0.0,
    max_buy_eth: float = 0.0,
    min_wallet_eth: float = 0.01,
    anti_mev: bool = True,
    max_creator_open_count: int = 20,
    reject_creator_hold: bool = False,
    enable_fake_heat: bool = True,
    exit_mode: str | None = None,
    hard_sl_pct: float | None = None,
    trail_activate_pct: float | None = None,
    trail_drawdown_pct: float | None = None,
    use_trailing: bool = True,
    bankroll_eth: float = 0.0,
    max_open_exposure_pct: float = 15.0,
    use_default_risk: bool | None = None,
    active_hours_cn: str = "18-4",
    offhours_mode: str = "sleep",
    offhours_poll_sec: float = 60.0,
    timezone_offset_hours: int = 8,
    confirm_orders: bool = True,
    shadow_collect: bool = False,
    scan_log_enabled: bool = True,
    hazard_mode: str = "off",
    hazard_snap_n: int | None = None,
    hazard_snap_gap_sec: float | None = None,
) -> Config:
    cfg = Config(
        wallet=wallet or os.environ.get("GMGN_WALLET", "0x37e9f4a84693bce7f7729612ee91a94c91eef898"),
        buy_eth=buy_eth,
        slippage=slippage,
        poll_sec=poll,
        gate_every=max(1, gate_every),
        max_gates_per_tick=max(1, max_gates),
        mon_security_every=max(1, mon_sec_every),
        lp_drop_pct=lp_drop_pct,
        min_liq_hold=min_liq_hold,
        max_positions=max_positions,
        daily_loss_usd=daily_loss_usd,
        only_safe_lp=not allow_uniswap,
        live=live,
        once=once,
        paper_positions=False if paper_positions is None else paper_positions,
        require_sell_quote=require_sell_quote,
        probe_eth=probe_eth,
        risk_pct=risk_pct,
        max_buy_eth=max_buy_eth,
        min_wallet_eth=min_wallet_eth,
        anti_mev=anti_mev,
        max_creator_open_count=max_creator_open_count,
        reject_creator_hold=reject_creator_hold,
        enable_fake_heat=enable_fake_heat,
        use_trailing=use_trailing,
        bankroll_eth=bankroll_eth,
        max_open_exposure_pct=max_open_exposure_pct,
        active_hours_cn=active_hours_cn,
        offhours_mode=offhours_mode,
        offhours_poll_sec=offhours_poll_sec,
        timezone_offset_hours=timezone_offset_hours,
        confirm_orders=confirm_orders,
        shadow_collect=shadow_collect,
        scan_log_enabled=scan_log_enabled,
        hazard_mode=(hazard_mode or "off").lower(),
    )
    apply_profile(cfg, profile, buy_eth)
    if exit_mode:
        cfg.exit_mode = exit_mode
    if hard_sl_pct is not None:
        cfg.hard_sl_pct = cfg.sl = hard_sl_pct
    if trail_activate_pct is not None:
        cfg.trail_activate_pct = trail_activate_pct
    if trail_drawdown_pct is not None:
        cfg.trail_drawdown_pct = trail_drawdown_pct
    if use_default_risk is not None:
        cfg.use_default_risk = use_default_risk
    if paper_positions is not None:
        cfg.paper_positions = paper_positions
    if min_mc is not None:
        cfg.min_mc = min_mc
    if max_mc is not None:
        cfg.max_mc = max_mc
    if bankr_max_mc is not None:
        cfg.bankr_max_mc = bankr_max_mc
    if min_liq is not None:
        cfg.min_liquidity = min_liq
    if max_top10 is not None:
        cfg.max_top10 = max_top10
    if max_top10_fresh is not None:
        cfg.max_top10_fresh = max_top10_fresh
    if fresh_min_age is not None:
        cfg.fresh_min_age_sec = max(0, int(fresh_min_age))
    if fresh_max_age is not None:
        cfg.fresh_max_age_sec = fresh_max_age
    if reheat_min_vol is not None:
        cfg.reheat_min_vol_1h = reheat_min_vol
    if allow_unindexed_liq is not None:
        cfg.allow_unindexed_liq = allow_unindexed_liq
    if disable_reheat is not None:
        cfg.disable_reheat = disable_reheat
    if soft_retry_sec is not None:
        cfg.soft_retry_sec = max(1, int(soft_retry_sec))
    if allowed_lps is not None:
        parts = tuple(p.strip().lower() for p in allowed_lps.split(",") if p.strip())
        cfg.allowed_lps = parts
    if max_hold_sec is not None:
        cfg.max_hold_sec = max_hold_sec
    if hazard_snap_n is not None:
        cfg.hazard_snap_n = max(1, int(hazard_snap_n))
    if hazard_snap_gap_sec is not None:
        cfg.hazard_snap_gap_sec = max(0.2, float(hazard_snap_gap_sec))
    if cfg.hazard_mode not in ("off", "shadow", "enforce"):
        cfg.hazard_mode = "off"
    # CLI risk exits must win over profile defaults
    cfg.lp_drop_pct = lp_drop_pct
    cfg.min_liq_hold = min_liq_hold
    return cfg


def run_bot(cfg: Config) -> None:
    try:
        parse_active_hours_cn(cfg.active_hours_cn)
    except Exception as e:
        print(f"[config_error] active_hours_cn: {e}", flush=True)
        return
    configure_runtime(cfg)
    if cfg.live:
        print("WARNING: --live spends real funds", flush=True)
        ok, reason = live_preflight(cfg)
        if not ok:
            print(f"[live_blocked] {reason}", flush=True)
            log_event({"event": "live_blocked", "reason": reason})
            return
        print(f"[live_preflight] {reason}", flush=True)
    size = resolve_buy_eth(cfg)
    br = bankroll_eth(cfg)
    print(
        f"[size] buy_eth={size:.6f} risk_pct={cfg.risk_pct or (cfg.default_risk_pct if cfg.use_default_risk else 0)} "
        f"bankroll≈{br:.4f} max_open_exposure={cfg.max_open_exposure_pct}% "
        f"probe_eth={cfg.probe_eth} sell_quote={cfg.require_sell_quote} anti_mev={cfg.anti_mev} "
        f"confirm_orders={cfg.confirm_orders}",
        flush=True,
    )
    try:
        loop(cfg)
    except KeyboardInterrupt:
        print("\n[stop]", flush=True)


def compute_stats(log_path: Path | None = None) -> dict:
    path = log_path or LOG_PATH
    # also scan both dry/live if default
    paths = [path]
    for extra in (Path("trades.dry.jsonl"), Path("trades.live.jsonl"), Path("trades.jsonl")):
        if extra.exists() and extra not in paths:
            paths.append(extra)
    counts: dict[str, int] = {}
    rejects: dict[str, int] = {}
    buys = probes_ok = probes_fail = rug_exits = rate_limits = buy_failed = 0
    used = None
    for path in paths:
        if not path.exists():
            continue
        used = path
        for line in path.read_text().splitlines():
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = o.get("event") or "unknown"
            if "event" not in o and o.get("mode") in ("dry-run", "live") and "buy_eth" in o:
                ev = "buy"
            counts[ev] = counts.get(ev, 0) + 1
            if ev == "reject":
                r = str(o.get("reason") or "?")
                key = r.split(":")[0].split(" ")[0]
                rejects[key] = rejects.get(key, 0) + 1
            elif ev == "buy":
                buys += 1
            elif ev == "buy_failed":
                buy_failed += 1
            elif ev == "probe":
                if o.get("ok"):
                    probes_ok += 1
                else:
                    probes_fail += 1
            elif ev == "emergency_sell":
                rug_exits += 1
            elif ev == "rate_limit":
                rate_limits += 1
    if used is None:
        return {"events": 0}
    return {
        "events": sum(counts.values()),
        "counts": counts,
        "buys": buys,
        "buy_failed": buy_failed,
        "probes_ok": probes_ok,
        "probes_fail": probes_fail,
        "emergency_sells": rug_exits,
        "rate_limits": rate_limits,
        "reject_reasons": dict(sorted(rejects.items(), key=lambda x: -x[1])[:15]),
        "log": str(used),
    }
