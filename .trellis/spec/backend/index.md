# Backend Development Guidelines

> rh-sniper / Robinhood paper-trading bot conventions.

---

## Pre-Development Checklist

1. Read [Logging Guidelines](./logging-guidelines.md) if touching `log_event` / trades jsonl / hazard fields  
2. Read [Paper EV Research](./paper-ev-research.md) if changing filters, paper cmdline, or offline analysis  
3. Read [Quality Guidelines](./quality-guidelines.md) for forbidden patterns  
4. Prefer stdlib + existing `engine.py` helpers over new deps  

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Logging Guidelines](./logging-guidelines.md) | JSONL contracts, `gate_audit_fields`, buy hazard keys | Active |
| [Paper EV Research](./paper-ev-research.md) | No look-ahead, bucket metrics, decision tree | Active |
| [Quality Guidelines](./quality-guidelines.md) | Forbidden patterns, paper/live gates | Active |
| [Directory Structure](./directory-structure.md) | Module layout | Stub |
| [Database Guidelines](./database-guidelines.md) | N/A (JSONL state) | Stub |
| [Error Handling](./error-handling.md) | Auth/rate limits | Stub |

---

## Quality Check (before finish)

- [ ] Buy/shadow/reject include `gate_audit_fields` when gate ran  
- [ ] No look-ahead entry rules in research scripts  
- [ ] `python3 scripts/test_paper_exec.py`  
- [ ] `python3 scripts/hazard_report.py --self-check`  
- [ ] Paper experiment uses **new** log filename  

**Language**: documentation in **English** (task PRDs may be Chinese).
