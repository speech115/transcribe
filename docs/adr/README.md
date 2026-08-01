# ADR Index

One row per ADR; this is the canonical index. Adding an ADR means adding its
row here in the same commit (AGENTS.md rule).

| ADR | Decision | Status |
|-----|----------|--------|
| [0001](ADR-0001-engine-seam.md) | Один движковый шов (`lib/engine.py`) для всех внешних контрактов движка | accepted |
| [0002](ADR-0002-run-module.md) | Весь контракт прогона живёт в одном модуле `lib/run.py` | accepted |
| [0003](ADR-0003-subtitle-and-term-artifacts.md) | Опциональные субтитры и детерминированные замены как артефакты прогона | accepted |
| [0004](ADR-0004-persistent-watch-state.md) | Persistent watch state и option-aware idempotency | accepted |
