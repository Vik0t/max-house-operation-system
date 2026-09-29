# Evidence registry

| ID | Claim | Type | Evidence | Status |
|---|---|---|---|---|
| E-001 | The MVP completes Signal → verified Asset state | TECH_BENCHMARK | `tests/e2e/test_golden_path.py`, browser QA | VERIFIED |
| E-002 | State transitions reject impossible paths | TECH_BENCHMARK | `tests/unit/test_state_machines.py` | VERIFIED |
| E-003 | Same core supports two houses | TECH_BENCHMARK | two YAML configs + E2E second-house test + live selector | VERIFIED |
| E-004 | Webhook replay does not duplicate processing | TECH_BENCHMARK | integration idempotency test | VERIFIED |
| E-005 | MAX bot connects and receives updates via Long Polling | TECH_BENCHMARK | production `GET /me`, polling marker and `/integrations/max/status`; adapter integration tests | VERIFIED FOR PERSONAL DIALOG / LIVE GROUP CHAT PENDING |
| E-006 | Time-to-action will fall by 50% | PRODUCT_HYPOTHESIS | none yet | UNVALIDATED |
| E-007 | Representative is the best primary persona | ASSUMPTION | product spec hypothesis | UNVALIDATED |
| E-008 | 20 repeated E2E runs have zero critical failures | TECH_BENCHMARK | automated test loop | VERIFIED |
| E-009 | Group initiative poll updates its shared card | TECH_BENCHMARK | MAX mock adapter and bot-worker unit tests | TESTED IN CODE / LIVE GROUP CHAT PENDING |

Do not present UNVALIDATED claims as measured outcomes.
