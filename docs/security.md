# Security notes

## Implemented

- Git and Docker context exclude `.env`.
- Settings validate integration mode.
- MAX token is never accepted via query parameter.
- Webhook secret uses constant-time comparison.
- Signal external IDs and Webhook event IDs are unique/idempotent.
- Evidence accepts only `http(s)`, `/demo/` or data-image URIs; no executable upload path exists.
- Domain transitions are deterministic and audited.
- Synthetic and AI-derived data carry provenance.
- Database is not exposed to the host by Compose.

## Production gates

- Replace demo identities with MAX identity verification and RBAC.
- Require (not merely support) `MAX_WEBHOOK_SECRET` in real mode.
- Add chat-to-house authorization mapping; never trust a request-provided house ID.
- Use S3-compatible object storage, MIME sniffing, size limits, malware scanning and signed URLs for uploads.
- Add retention/deletion policy and PII redaction.
- Move secrets to Docker/Kubernetes secret mounts or a managed secret store.
- Generate explicit Alembic revisions for every schema change and rehearse backup/restore.

