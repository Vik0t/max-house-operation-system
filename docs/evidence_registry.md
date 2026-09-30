# Evidence registry

| ID | Claim | Type | Evidence | Status |
|---|---|---|---|---|
| E-001 | The MVP completes Signal → verified Asset state | TECH_BENCHMARK | `tests/e2e/test_golden_path.py`, browser QA | VERIFIED |
| E-002 | State transitions reject impossible paths | TECH_BENCHMARK | `tests/unit/test_state_machines.py` | VERIFIED |
| E-003 | Same core supports two houses | TECH_BENCHMARK | two YAML configs + E2E second-house test + live selector | VERIFIED |
| E-004 | Webhook replay does not duplicate processing | TECH_BENCHMARK | integration idempotency test | VERIFIED |
| E-005 | MAX bot connects and receives group updates via Long Polling | TECH_BENCHMARK | production `GET /me`, polling marker, live group permission check (`read_all_messages=true`), inbound group message → persisted initiative (30 September 2026) | VERIFIED LIVE GROUP |
| E-006 | Time-to-action will fall by 50% | PRODUCT_HYPOTHESIS | none yet | UNVALIDATED |
| E-007 | Representative is the best primary persona | ASSUMPTION | product spec hypothesis | UNVALIDATED |
| E-008 | 20 repeated E2E runs have zero critical failures | TECH_BENCHMARK | automated test loop | VERIFIED |
| E-009 | Group initiative poll accepts one vote per MAX user | TECH_BENCHMARK | live group message created an informal poll; MAX callback stored one vote, repeated callback received 409; bot-worker unit tests | VERIFIED LIVE VOTE; VISUAL CARD REFRESH NOT INDEPENDENTLY INSPECTED |
| E-010 | One living Issue card can be created and edited in the MAX group | TECH_BENCHMARK | production `POST /messages` returned a MAX message ID; `PUT /messages` returned `success=true` for the seeded elevator Issue (30 September 2026); 116 automated tests cover card reuse, privacy and restart state | VERIFIED LIVE TRANSPORT; NEXT RESIDENT MESSAGE/STATE-CHANGE VISUAL CHECK STILL PENDING |

Do not present UNVALIDATED claims as measured outcomes.
