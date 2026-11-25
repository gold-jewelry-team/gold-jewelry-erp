# Inventory Operation Recovery Design

## Status

Design proposal only. This document does not change the production database, execute migrations, or alter live inventory data.

## Context and current behavior

Manual inventory adjustments and manual shelf transfers already require a client-generated UUID idempotency key. The key is persisted in `inventory_movements.reference_id`, with the operation type in `reference_type`. The service compares the full operation content before returning the original movement. Reusing a key for different content returns HTTP 409. PostgreSQL company-row locking serializes keyed writes, and the existing CI suite covers concurrent adjustment retries.

The browser currently stores the pending payload and UUID in `localStorage`, scoped by company and site. If that browser storage is cleared or becomes unreadable, the client can lose the UUID needed for an exact retry. The movement history can show the movement ID and reference UUID after a successful operation, but it is not a first-class recovery inbox and cannot represent a request accepted by the server but not yet completed.

The application currently uses a single administrator session cookie. There is no reliable employee/user identity suitable for per-employee ownership. Recovery must therefore be scoped to company and site and protected by the existing administrator-session middleware. Do not invent or assume employee IDs.

## Goals

1. Recover an operation even after browser storage is cleared, without guessing based on product, quantity, note, or timestamp.
2. Preserve existing adjustment/transfer API behavior and exact-retry semantics.
3. Make request acceptance durable before attempting the inventory ledger write.
4. Make the inventory movement and request completion atomic in one database transaction.
5. Make duplicate submissions and concurrent retries safe.
6. Provide a server-side recovery inbox for recent and unfinished requests.
7. Keep a permanent audit trail for completed/rejected requests; do not silently expire idempotency keys.

## Non-goals

- No automatic matching of unkeyed movement history to a lost request.
- No automatic resubmission of a request merely because its result is uncertain.
- No multi-employee authorization model in this phase.
- No change to stocktake batch processing in the first implementation unless separately tested and designed.
- No production migration or database write as part of design review.

## Proposed data model

Add an `inventory_operation_requests` table:

- `id`: UUID primary key; server-issued recovery handle.
- `company_id`, `site_id`: required ownership/scope columns.
- `operation_type`: constrained to `MANUAL_ADJUSTMENT` or `MANUAL_TRANSFER`.
- `idempotency_key`: client UUID; unique with `company_id`.
- `payload`: JSONB containing the validated canonical request body.
- `payload_fingerprint`: SHA-256 of a canonical serialization of operation type and payload.
- `status`: `PENDING`, `COMPLETED`, or `REJECTED`.
- `movement_id`: nullable FK to `inventory_movements.id`, populated only when completed.
- `failure_code` and `failure_message`: nullable, sanitized validation/rejection detail.
- `created_at`, `updated_at`, `completed_at`: server timestamps.

Constraints and indexes:

- Unique `(company_id, idempotency_key)` so the same request key cannot create two request records.
- Index `(company_id, site_id, created_at DESC)` for the recovery inbox.
- Check constraints for allowed operation types and statuses.
- Check constraint: `COMPLETED` requires `movement_id`; non-completed states must not claim a movement.
- Foreign keys use restrictive deletion semantics for company/site/movement references.

Do not add a uniqueness constraint to all existing movement `reference_id` values without first auditing all reference types; those fields are also used by other business flows. The request table owns uniqueness for the new request workflow.

## Request lifecycle and transaction boundaries

1. Validate the authenticated admin request and the company/site relationship.
2. Canonicalize the operation payload and compute its fingerprint.
3. Insert a `PENDING` request record and commit it before changing inventory.
   - If `(company_id, idempotency_key)` already exists, compare operation type and fingerprint.
   - Exact match: continue/recover the existing request.
   - Different content: return HTTP 409; never overwrite the original payload.
4. In a new transaction, select the request row `FOR UPDATE`.
   - If `COMPLETED`, return its linked original movement.
   - If `REJECTED`, return its stored rejection; a corrected request must use a new key.
   - If `PENDING`, execute the existing inventory service using the stored canonical payload.
5. In that same transaction, set `movement_id`, status `COMPLETED`, and `completed_at`, then commit.
   - The movement and completion state commit together.
   - If the process crashes before this transaction commits, both changes roll back and the previously committed request remains `PENDING`.
   - A later explicit retry can safely lock and process that pending request.
6. Deterministic business validation failures may be committed as `REJECTED` in a separate transaction after rollback. Unexpected database/infrastructure failures leave the request `PENDING` for explicit recovery; do not convert unknown outcomes to success or rejection.

The request row lock serializes retries for the same request. The movement's existing idempotency key remains a second safety layer during transition and for compatibility with existing clients.

## Proposed API

Keep existing routes:

- `POST /companies/{company_id}/inventory/adjustments`
- `POST /companies/{company_id}/inventory/transfers`

Adapt them to create/find the durable request record, then process it through the lifecycle above. Preserve existing response status semantics: first successful creation is HTTP 201; an exact replay/recovery is HTTP 200; conflicting reuse is HTTP 409.

Add:

- `GET /companies/{company_id}/inventory/operation-requests?site_id=...&status=PENDING&limit=...`
  - Returns a bounded, newest-first recovery inbox.
  - Includes request ID, type, status, created/updated timestamps, safe product/location/quantity summary, failure detail if rejected, and linked movement ID/reference UUID if completed.
  - Must scope by company and site; require the existing admin session.
- `POST /companies/{company_id}/inventory/operation-requests/{request_id}/retry`
  - Explicitly retries only a `PENDING` request.
  - Verifies the request belongs to the supplied company and selected site.
  - Reuses the server-stored payload; the browser does not need the lost UUID or original payload.
  - Completed requests return the original movement; rejected requests are not retried.

Do not expose a public endpoint that accepts a guessed product/quantity tuple and silently selects a matching movement.

## UI behavior

Add a "待確認／可恢復操作" panel to the inventory movement workspace:

- Load recent pending requests from the recovery inbox.
- Show operation type, product, source/destination, quantity, submitted time, status, and request ID.
- For `PENDING`, offer an explicit "使用伺服器保存內容重試" action.
- For `COMPLETED`, link/show the movement ID and reference UUID; do not offer a second write.
- For `REJECTED`, show the reason and require a corrected new operation with a new key.
- Keep the existing localStorage exact-retry flow as a convenience, but treat the server record as authoritative.
- If localStorage is missing or corrupt, show the recovery inbox instead of asking the user to infer the original operation from approximate history.

## Migration and rollout

1. Implement model, migration, service, API, UI, and tests on a feature branch.
2. CI must test SQLite behavior and PostgreSQL concurrency/recovery behavior.
3. Test crash-like boundaries: request committed before movement; transaction rollback leaves PENDING; explicit retry completes exactly once; duplicate same-key submissions; changed payload conflict; completed replay; rejected request handling; cross-company/site access rejection.
4. Deploy application code only after CI passes. Because the new code requires the new table, deployment must be coordinated with the explicit production migration workflow. Do not rely on container startup to migrate.
5. Run the production Alembic migration only after a separate explicit approval. Verify schema head and health afterward.
6. Do not rewrite or delete existing inventory movements. Existing history remains intact; the new request table only governs requests created after rollout.

## Acceptance criteria

- Clearing browser storage does not prevent recovery of a server-accepted request.
- A pending request can be explicitly retried from the recovery inbox and creates at most one movement.
- A completed request always resolves to the same movement ID.
- Reusing a key with a different operation type or payload returns 409.
- A movement and its request completion cannot be committed separately.
- No heuristic matching or silent automatic resubmission occurs.
- Existing stock balances and movement history are unchanged by the migration.
- No production migration is run without explicit approval.
## Additional implementation safeguards from code review

The implementation must also preserve compatibility with requests created before this table is deployed:

- Before creating or processing a new request row, check the existing movement ledger for the same company and idempotency UUID using the existing manual-adjustment/transfer idempotency rules.
- If an exact legacy movement already exists, create or complete the request record linked to that movement and return HTTP 200. If the UUID exists with different operation content or type, return HTTP 409. This prevents a browser pending UUID created before rollout from causing a second movement after rollout.
- Never attempt to infer a legacy request when its UUID is missing. Only exact UUID-based ledger reconciliation is allowed.

Canonicalization and uniqueness rules:

- Normalize UUIDs to lowercase canonical strings, Decimal values to fixed-point strings, and explicit timestamps to UTC before hashing. Apply schema defaults before fingerprinting so equivalent accepted payloads produce the same fingerprint.
- Exclude transport-only fields from the fingerprint. Include every field that changes inventory meaning, including operation type, company/site, product, location(s), direction, quantity, weight/unit, note, and explicit occurred_at.
- Keep the unique key (company_id, idempotency_key). If an existing key is submitted for another site, reject it with HTTP 409; never reveal or retry the other site's request. Recovery queries and retry actions must independently verify both company and site.
- Do not rely on the hash alone for correctness: compare the stored operation type and canonical payload as well as the fingerprint.

Locking and transaction order:

- Use one documented lock order in every path: company row, operation-request row, then product/location rows. This is compatible with the current inventory service, which locks the company before the product, and reduces deadlock risk.
- The first transaction durably inserts the PENDING request. The processing transaction obtains the company lock before locking the request row, then invokes the existing inventory service and updates the request to COMPLETED in the same transaction.
- Handle the unique-key insert race by rolling back the losing insert transaction, loading the winner's row, and comparing its site, operation type, and canonical payload. Do not continue using a failed SQLAlchemy transaction.
- A recovery endpoint must not accept a replacement payload. It may only process the immutable payload stored on the request row.

Operational and privacy safeguards:

- Bound recovery inbox pagination (for example, default 50 and maximum 200), filter by exact company/site, and return only the minimum product/location summary needed by the operator.
- Store sanitized failure codes/messages; never persist stack traces, SQL text, credentials, or secrets in the request record.
- Keep idempotency records permanently unless a separately reviewed archival policy is introduced. A retention policy must never make an old UUID reusable.
- Old PENDING records may be highlighted as requiring review, but no background worker may silently retry inventory writes. Retry remains an explicit administrator action.
- Mutating retry routes must use the same administrator-session and request-forgery protections as other inventory write routes.
