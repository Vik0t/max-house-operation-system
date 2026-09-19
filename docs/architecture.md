# Architecture

```text
MAX Long Poll worker            React mini-app
          │                           │
          └──────── FastAPI ──────────┘
                       │
       ┌───────────────┼────────────────┐
       │               │                │
 Domain/state      AI pipeline      MAX adapter
       │               │                │
       └──────────── PostgreSQL ─────────┘
```

## Domain boundaries

Persistence follows the source-of-truth entities: House, Zone, Asset, Signal, Issue, Initiative, Action, Submission, WorkOrder, Evidence, Verification. `AuditEvent` and `WebhookEvent` support reliability; they do not replace the product entities.

`app/state_machine.py` is the only transition policy. API handlers request transitions; invalid transitions receive HTTP 409. LLM/deterministic extraction can suggest entities and actions, but only domain logic changes state.

## AI stages

1. actionability detection;
2. intent classification;
3. schema-validated structured extraction;
4. Zone/Asset resolution against configured topology;
5. context-aware duplicate scoring (house + zone + asset + category + text + time window);
6. Asset-level recurrence query;
7. Initiative summary;
8. config-grounded action suggestion.

Timeout is injected/tested with `force_ai_failure`; API returns a manual classification fallback without dropping the Signal. Low asset confidence returns Zone choices. Medium duplicate confidence returns explicit LINK / CREATE_NEW decisions.

## Transaction and reliability model

- Each user command commits Signal + derived domain change atomically.
- External IDs prevent duplicate Signals.
- The bot persists the MAX `marker` in a Docker volume; restarts resume polling without replay.
- `WebhookEvent.id` protects webhook processing from replay.
- MAX calls use timeout and bounded exponential retries.
- Audit events are committed in the same transaction as state changes.
- Compose startup waits for PostgreSQL, runs migrations, idempotent seed, then API and the independent bot worker.

## Scale layer

Core code never contains a concrete address or УК policy. `configs/demo_house_a.yaml` and `configs/demo_house_b.yaml` define topology, assets, management organization, routes, contractors and recurrence rules. The selector is a live proof that the same API/UI serves different houses.
