# Phase D — Company access control

## Current implementation slice

This phase adds server-side company membership checks for Google sessions. A Google
session must be valid, unrevoked and unexpired; its user must be active; the target
company must be active; and that exact user/company pair must have an ACTIVE
membership. A pending, rejected, suspended, inactive or cross-company membership
cannot pass this check.

The legacy owner username/password session remains the administrator path and
continues to bypass company membership checks.

## Conservative role baseline

| Role | Initial API access |
| --- | --- |
| OWNER | All methods within the explicitly approved company |
| MANAGER | Read-only methods within the explicitly approved company |
| STAFF | Denied until own-record filtering and permissions are implemented |

STAFF access is deliberately fail-closed. Existing operational records generally
do not contain a stable created-by user ID, so a server cannot reliably enforce
"only records created by this member". A display name, free-text operator field,
or creation timestamp is not a safe substitute for immutable actor identity.

## Not yet complete

- Persistent configurable permission grants for view/create/update/void.
- Actor attribution on business transactions and audit-log integration.
- Reliable own-record data filtering.
- Fine-grained permission enforcement for action-style POST routes.
- Google-member workspace UI and company selection.
- End-to-end production OAuth validation.

Google OAuth remains disabled. Do not enable it until the remaining authorization
work and the end-to-end security tests are complete.
