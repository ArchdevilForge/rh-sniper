#!/usr/bin/env python3
"""rh-sniper CLI — manage / run the Robinhood GMGN sniper."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Optional

import typer

from rh_sniper import __version__
from rh_sniper.engine import (
    LOG_PATH,
    STATE_PATH,
    build_config,
    compute_stats,
    load_state,
    run_bot,
)

app = typer.Typer(
    name="rh-sniper",
    help="Robinhood-chain meme sniper via GMGN (strategy replica, not copy-trade).",
    add_completion=False,
    no_args_is_help=True,
)

ProfileOpt = typer.Option("adff", "--profile", "-p", help="adff | 7a23 | 417c")
WalletOpt = typer.Option(None, "--wallet", "-w", help="Wallet bound to GMGN API key")


@app.command()
def run(
    profile: str = ProfileOpt,
    wallet: Optional[str] = WalletOpt,
    buy_eth: float = typer.Option(0.03, "--buy-eth", help="Buy size in native ETH"),
    slippage: int = typer.Option(30, "--slippage"),
    poll: float = typer.Option(1.0, "--poll", help="Fast loop seconds"),
    gate_every: int = typer.Option(2, "--gate-every", help="Hard-check every N fast loops"),
    max_gates: int = typer.Option(2, "--max-gates", help="Max hard-checks per gate tick"),
    mon_sec_every: int = typer.Option(3, "--mon-sec-every", help="Full security mon every N loops"),
    min_mc: Optional[float] = typer.Option(None, "--min-mc"),
    max_mc: Optional[float] = typer.Option(None, "--max-mc"),
    bankr_max_mc: Optional[float] = typer.Option(None, "--bankr-max-mc", help="Bankr LP max MC override"),
    min_liq: Optional[float] = typer.Option(None, "--min-liq"),
    max_top10: Optional[float] = typer.Option(None, "--max-top10", help="Max top10 holder rate, e.g. 0.55"),
    max_top10_fresh: Optional[float] = typer.Option(None, "--max-top10-fresh", help="Looser top10 while very fresh"),
    fresh_max_age: Optional[int] = typer.Option(None, "--fresh-max-age"),
    reheat_min_vol: Optional[float] = typer.Option(None, "--reheat-min-vol"),
    allow_unindexed_liq: Optional[bool] = typer.Option(
        None, "--allow-unindexed-liq/--no-unindexed-liq", help="liq=0 + fresh → trust buy quote"
    ),
    disable_reheat: Optional[bool] = typer.Option(
        None, "--disable-reheat/--enable-reheat", help="First-wave only (no reheat entries)"
    ),
    soft_retry_sec: Optional[int] = typer.Option(None, "--soft-retry-sec", help="Soft reject cooldown seconds"),
    lp_drop_pct: float = typer.Option(35.0, "--lp-drop-pct"),
    min_liq_hold: float = typer.Option(800.0, "--min-liq-hold"),
    max_hold_sec: Optional[int] = typer.Option(None, "--max-hold-sec"),
    max_positions: int = typer.Option(3, "--max-positions"),
    daily_loss_usd: float = typer.Option(100.0, "--daily-loss-usd"),
    allow_uniswap: bool = typer.Option(False, "--allow-uniswap", help="Allow naked Uni pools"),
    live: bool = typer.Option(False, "--live", help="REAL money (off by default)"),
    once: bool = typer.Option(False, "--once", help="Single cycle then exit"),
    paper_positions: bool = typer.Option(False, "--paper-positions", help="Track positions in dry-run (default off)"),
    require_sell_quote: bool = typer.Option(True, "--require-sell-quote/--no-sell-quote", help="Require token->NATIVE quote"),
    probe_eth: float = typer.Option(0.0, "--probe-eth", help="Probe size; >0 enables probe buy/sell before full size"),
    risk_pct: float = typer.Option(0.0, "--risk-pct", help="Size as % of native (2=2%); 0=use --buy-eth"),
    max_buy_eth: float = typer.Option(0.0, "--max-buy-eth", help="Cap when using --risk-pct"),
    min_wallet_eth: float = typer.Option(0.01, "--min-wallet-eth", help="Live gate min native balance"),
    anti_mev: bool = typer.Option(True, "--anti-mev/--no-anti-mev"),
    max_creator_open_count: int = typer.Option(20, "--max-creator-open-count", help="0 disables"),
    reject_creator_hold: bool = typer.Option(False, "--reject-creator-hold"),
    enable_fake_heat: bool = typer.Option(True, "--fake-heat/--no-fake-heat"),
    exit_mode: Optional[str] = typer.Option(None, "--exit-mode", help="hf_full|hf_scale|principal|wide (override profile)"),
    hard_sl_pct: Optional[float] = typer.Option(None, "--hard-sl", help="Hard stop-loss percent, e.g. 55"),
    trail_activate_pct: Optional[float] = typer.Option(None, "--trail-activate", help="Activate trailing after +X%"),
    trail_drawdown_pct: Optional[float] = typer.Option(None, "--trail-dd", help="Trailing giveback from peak %"),
    no_trailing: bool = typer.Option(False, "--no-trailing"),
    bankroll_eth: float = typer.Option(0.0, "--bankroll-eth", help="Bankroll for risk sizing; 0=native bal"),
    max_open_exposure_pct: float = typer.Option(15.0, "--max-open-exposure-pct"),
    use_default_risk: bool = typer.Option(False, "--use-default-risk", help="Use profile default risk% if --risk-pct not set"),
    tp_ladder: Optional[str] = typer.Option(None, "--tp-ladder", help="e.g. 100:55,200:25,400:10"),
    active_hours_cn: str = typer.Option(
        "18-4",
        "--active-hours-cn",
        help="CN hours window, e.g. 18-4 or 18-21,8-12; all/24h = always",
    ),
    offhours_mode: str = typer.Option(
        "sleep",
        "--offhours-mode",
        help="sleep=rest no entries; mon=legacy alias of sleep; off=deep idle",
    ),
    offhours_poll_sec: float = typer.Option(60.0, "--offhours-poll", help="Seconds between checks when resting"),
    timezone_offset_hours: int = typer.Option(8, "--tz-offset", help="Local offset hours (CN=8)"),
) -> None:
    """Start the sniper (dry-run unless --live)."""
    if profile not in {"adff", "7a23", "417c"}:
        raise typer.BadParameter("profile must be adff | 7a23 | 417c")
    if exit_mode and exit_mode not in {"hf_full", "hf_scale", "principal", "wide"}:
        raise typer.BadParameter("exit-mode must be hf_full|hf_scale|principal|wide")
    cfg = build_config(
        wallet=wallet,
        profile=profile,
        buy_eth=buy_eth,
        slippage=slippage,
        poll=poll,
        gate_every=gate_every,
        max_gates=max_gates,
        mon_sec_every=mon_sec_every,
        min_mc=min_mc,
        max_mc=max_mc,
        bankr_max_mc=bankr_max_mc,
        min_liq=min_liq,
        max_top10=max_top10,
        max_top10_fresh=max_top10_fresh,
        fresh_max_age=fresh_max_age,
        reheat_min_vol=reheat_min_vol,
        allow_unindexed_liq=allow_unindexed_liq,
        disable_reheat=disable_reheat,
        soft_retry_sec=soft_retry_sec,
        lp_drop_pct=lp_drop_pct,
        min_liq_hold=min_liq_hold,
        max_hold_sec=max_hold_sec,
        max_positions=max_positions,
        daily_loss_usd=daily_loss_usd,
        allow_uniswap=allow_uniswap,
        live=live,
        once=once,
        paper_positions=paper_positions,
        require_sell_quote=require_sell_quote,
        probe_eth=probe_eth,
        risk_pct=risk_pct,
        max_buy_eth=max_buy_eth,
        min_wallet_eth=min_wallet_eth,
        anti_mev=anti_mev,
        max_creator_open_count=max_creator_open_count,
        reject_creator_hold=reject_creator_hold,
        enable_fake_heat=enable_fake_heat,
        exit_mode=exit_mode,
        hard_sl_pct=hard_sl_pct,
        trail_activate_pct=trail_activate_pct,
        trail_drawdown_pct=trail_drawdown_pct,
        use_trailing=not no_trailing,
        bankroll_eth=bankroll_eth,
        max_open_exposure_pct=max_open_exposure_pct,
        use_default_risk=use_default_risk if use_default_risk else None,
        active_hours_cn=active_hours_cn,
        offhours_mode=offhours_mode,
        offhours_poll_sec=offhours_poll_sec,
        timezone_offset_hours=timezone_offset_hours,
    )
    if tp_ladder:
        parts = []
        for chunk in tp_ladder.split(","):
            a, b = chunk.split(":")
            parts.append((float(a), float(b)))
        if len(parts) >= 1:
            cfg.tp1, cfg.tp1_pct = parts[0]
        if len(parts) >= 2:
            cfg.tp2, cfg.tp2_pct = parts[1]
        if len(parts) >= 3:
            cfg.tp3, cfg.tp3_pct = parts[2]
    run_bot(cfg)


@app.command("status")
def status_cmd() -> None:
    """Show runtime state (positions, seen, counters)."""
    if not STATE_PATH.exists():
        typer.echo(f"no state file: {STATE_PATH}")
        raise typer.Exit(1)
    st = load_state()
    pos = st.get("positions") or {}
    seen = st.get("seen") or {}
    typer.echo(f"state: {STATE_PATH}")
    typer.echo(
        f"day: {st.get('day')}  buys_today: {st.get('buys_today', 0)}  "
        f"day_pnl_est: {st.get('day_realized_est', 0)}  paper_pnl_est: {st.get('paper_realized_est', 0):+.6f} ETH"
    )
    typer.echo(f"seen_tokens: {len(seen)}  open_positions: {len(pos)}")
    for addr, meta in pos.items():
        typer.echo(
            f"  - {meta.get('symbol', '?')} {addr[:12]}… "
            f"mode={meta.get('entry_mode')} mc={meta.get('entry_mc')} "
            f"liq={meta.get('entry_liq')} buy={meta.get('buy_eth')} {meta.get('mode')}"
        )


@app.command()
def logs(
    n: int = typer.Option(20, "--n", "-n", help="Show last N events"),
    event: Optional[str] = typer.Option(None, "--event", "-e", help="Filter event type"),
) -> None:
    """Tail trades.jsonl."""
    if not LOG_PATH.exists():
        typer.echo(f"no log file: {LOG_PATH}")
        raise typer.Exit(1)
    rows = []
    for line in LOG_PATH.read_text().splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        ev = obj.get("event")
        if not ev and obj.get("mode") in ("dry-run", "live") and "buy_eth" in obj:
            ev = "buy"
            obj = {**obj, "event": "buy"}
        if event and obj.get("event") != event:
            continue
        rows.append(obj)
    for obj in rows[-n:]:
        ts = obj.get("ts")
        ev = obj.get("event")
        sym = obj.get("symbol") or ""
        reason = obj.get("reason") or obj.get("mode") or ""
        mc = obj.get("mc")
        extra = f" mc={mc}" if mc is not None else ""
        typer.echo(f"{ts} {str(ev):16} {sym:12} {reason}{extra}")


@app.command()
def stats() -> None:
    """Summarize trades.jsonl (rejects / buys / probes / emergency exits)."""
    s = compute_stats()
    if not s.get("events"):
        typer.echo(f"no events in {s.get('log', LOG_PATH)}")
        raise typer.Exit(1)
    typer.echo(f"log: {s['log']}")
    typer.echo(f"events: {s['events']}  buys: {s['buys']}  buy_failed: {s.get('buy_failed',0)}  emergency_sells: {s['emergency_sells']}")
    typer.echo(f"probes_ok: {s['probes_ok']}  probes_fail: {s['probes_fail']}  rate_limits: {s.get('rate_limits',0)}")
    typer.echo(f"counts: {s.get('counts')}")
    typer.echo("top reject reasons:")
    for k, v in (s.get("reject_reasons") or {}).items():
        typer.echo(f"  {k}: {v}")


@app.command()
def doctor() -> None:
    """Check gmgn-cli + config + wallet bindings."""
    ok = True
    path = shutil.which("gmgn-cli")
    if not path:
        typer.echo("FAIL  gmgn-cli not on PATH (npm install -g gmgn-cli)")
        ok = False
    else:
        typer.echo(f"OK    gmgn-cli: {path}")
        p = subprocess.run(["gmgn-cli", "config", "--check"], capture_output=True, text=True)
        if p.returncode == 0:
            typer.echo("OK    gmgn-cli config --check")
        else:
            typer.echo(f"FAIL  gmgn-cli config --check\n{(p.stderr or p.stdout)[:300]}")
            ok = False
        p2 = subprocess.run(["gmgn-cli", "portfolio", "info", "--raw"], capture_output=True, text=True)
        if p2.returncode == 0 and p2.stdout.strip():
            try:
                info = json.loads(p2.stdout)
                wallets = info.get("wallets") or []
                typer.echo(f"OK    portfolio wallets: {len(wallets)}")
                for w in wallets:
                    if w.get("chain") == "robinhood":
                        bals = w.get("balances") or []
                        native = 0.0
                        for b in bals:
                            if (b.get("token_address") or "").lower() in (
                                "",
                                "0x0000000000000000000000000000000000000000",
                            ):
                                try:
                                    native = float(b.get("balance") or 0)
                                except Exception:
                                    native = 0.0
                        typer.echo(f"      robinhood {w.get('address')} native≈{native}")
                        if native <= 0:
                            typer.echo("WARN  robinhood native balance is 0 — --live will be blocked")
            except json.JSONDecodeError:
                typer.echo("WARN  portfolio info not JSON")
        else:
            typer.echo(f"WARN  portfolio info failed: {(p2.stderr or p2.stdout)[:200]}")
    typer.echo(f"INFO  state path: {STATE_PATH} exists={STATE_PATH.exists()}")
    typer.echo(f"INFO  log path:   {LOG_PATH} exists={LOG_PATH.exists()}")
    raise typer.Exit(0 if ok else 1)


@app.command()
def reset_state(
    yes: bool = typer.Option(False, "--yes", help="Confirm delete state.json"),
) -> None:
    """Clear seen/positions state (does not touch chain)."""
    if not yes:
        typer.echo("refusing without --yes")
        raise typer.Exit(1)
    if STATE_PATH.exists():
        STATE_PATH.unlink()
        typer.echo(f"deleted {STATE_PATH}")
    else:
        typer.echo("nothing to delete")


@app.command()
def version() -> None:
    """Print version."""
    typer.echo(f"rh-sniper {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
