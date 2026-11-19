# M0 executable audit packet

- `../../docs/research/M0_EXECUTION_REPORT_2026-11-17.md`: verified official metadata, execution limitations, next gates.
- `./m0_meter_audit.py`: minimal Python standard-library audit script, runnable with source CSV exports or bounded public API access.
- `fixtures/`: **synthetic test records only**, never use for LA product claims.
- `../../docs/core/M0_DATA_FEASIBILITY_PLAN.md` and `../../docs/core/ARCHITECTURE_BASELINE_v1.0.md`: approved design basis from previous phase.

No row-level LADOT data is bundled. The actual join and freshness numbers remain unknown until first successful source fetch.
