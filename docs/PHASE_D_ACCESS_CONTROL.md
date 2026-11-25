# Phase D — Company access control

## Implemented in the current draft

- Google sessions are checked on every company-scoped API request. A request must have an unexpired, unrevoked session, active user, active company, and an ACTIVE membership for the exact company in the URL.
- The owner username/password session remains the administrator path and keeps access to the existing workspace and administration pages.
- Permission catalogue: each resource supports the four requested actions — view, create, update, void.
- Company-specific roles are stored separately per company; one membership can hold multiple roles.
- Permission grants carry both allow/deny and a data scope (ALL or OWN).
- Existing companies are provisioned with OWNER, MANAGER, and STAFF roles by migration. New companies receive the same baseline lazily when the owner first opens the role editor or a member is assigned.
- New Google members in a one-company setup are assigned the default STAFF role while pending approval.
- An administrator API and mobile-friendly role editor support custom roles and permission configuration.
- The request middleware resolves a company API path to a permission code and authorizes it from the member's assigned roles. Unknown company API routes fail closed.
- A record-actor registry records the creator and last modifier for supported business records. It distinguishes Google user IDs from the legacy owner username/password account.
- ORM reads for supported resources apply a creator filter when the effective data scope is OWN.

## Conservative defaults

| Role | Default grants |
| --- | --- |
| OWNER | All four actions, all company data |
| MANAGER | View only, all company data |
| STAFF | No permissions until the owner configures them |

A custom role can grant only selected resources and actions. For OWN scope, only view and create are currently allowed. Update and void remain denied until write operations can be consistently constrained to records created by the member.

Historical rows are not assigned to a person by inference. They have no actor registry row and therefore are not visible under an OWN-scoped permission. Existing owner access is unchanged.

## Remaining before employee rollout

- CI validates Migration 0035 on PostgreSQL 16 using both a clean schema upgrade/downgrade/re-upgrade and synthetic 0034 data (two companies and three memberships), then verifies the 24-resource permission catalogue, default grants, and membership-role backfill. A separate Neon production-data clone has not been created; the available Neon branch connector does not expose schema-only branching, and copying live business data needs explicit approval.
- Complete the remaining own-scope write and void checks.
- Exercise the role editor and member multi-role assignment through an authenticated browser session.
- Verify every company-scoped route is mapped to a permission resource.
- Complete the Google OAuth end-to-end test with the new schema, then enable the feature flag only after explicit owner approval.

Google OAuth remains disabled. The migration has not been applied to the production Neon database. Do not enable Google OAuth or invite staff until the remaining security checks and production migration have been explicitly approved.
