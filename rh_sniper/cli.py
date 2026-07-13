#!/usr/bin/env python3
"""rh-sniper CLI — manage / run the Robinhood GMGN sniper."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import typer

from rh_sniper.engine import (
    LOG_PATH,
    STATE_PATH,
    build_config,
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
    min_liq: Optional[float] = typer.Option(None, "--min-liq"),
    fresh_max_age: Optional[int] = typer.Option(None, "--fresh-max-age"),
    reheat_min_vol: Optional[float] = typer.Option(None, "--reheat-min-vol"),
    lp_drop_pct: float = typer.Option(35.0, "--lp-drop-pct"),
    min_liq_hold: float = typer.Option(800.0, "--min-liq-hold"),
    max_hold_sec: Optional[int] = typer.Option(None, "--max-hold-sec"),
    max_positions: int = typer.Option(3, "--max-positions"),
    daily_loss_usd: float = typer.Option(100.0, "--daily-loss-usd"),
    allow_uniswap: bool = typer.Option(False, "--allow-uniswap", help="Allow naked Uni pools"),
    live: bool = typer.Option(False, "--live", help="REAL money (off by default)"),
    once: bool = typer.Option(False, "--once", help="Single cycle then exit"),
) -> None:
    """Start the sniper (dry-run unless --live)."""
    if profile not in {"adff", "7a23", "417c"}:
        raise typer.BadParameter("profile must be adff | 7a23 | 417c")
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
        min_liq=min_liq,
        fresh_max_age=fresh_max_age,
        reheat_min_vol=reheat_min_vol,
        lp_drop_pct=lp_drop_pct,
        min_liq_hold=min_liq_hold,
        max_hold_sec=max_hold_sec,
        max_positions=max_positions,
        daily_loss_usd=daily_loss_usd,
        allow_uniswap=allow_uniswap,
        live=live,
        once=once,
    )
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
    typer.echo(f"day: {st.get('day')}  buys_today: {st.get('buys_today', 0)}  day_pnl_est: {st.get('day_realized_est', 0)}")
    typer.echo(f"seen_tokens: {len(seen)}  open_positions: {len(pos)}")
    for addr, meta in pos.items():
        typer.echo(
            f"  - {meta.get('symbol', '?')} {addr[:12]}… "
            f"mode={meta.get('entry_mode')} mc={meta.get('entry_mc')} "
            f"liq={meta.get('entry_liq')} {meta.get('mode')}"
        )


@app.command()
def logs(
    n: int = typer.Option(20, "--n", "-n", help="Show last N events"),
    event: Optional[str] = typer.Option(None, "--event", "-e", help="Filter event type (buy/reject/...)"),
) -> None:
    """Tail trades.jsonl."""
    if not LOG_PATH.exists():
        typer.echo(f"no log file: {LOG_PATH}")
        raise typer.Exit(1)
    lines = LOG_PATH.read_text().splitlines()
    rows = []
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
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
        typer.echo(f"{ts} {ev:16} {sym:12} {reason}{extra}")


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
                        typer.echo(f"      robinhood {w.get('address')} balances={len(bals)}")
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
    from rh_sniper import __version__
    typer.echo(f"rh-sniper {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
