# Phase D — Company access control

## Implemented in the current draft

- Every company-scoped Google API request checks an unexpired, unrevoked session, active user, active company, and ACTIVE membership for the exact company in the URL.
- The owner username/password session remains the administrator path and keeps access to the existing workspace and administration pages.
- The permission catalogue supports four actions per resource: view, create, update, and void.
- Roles are company-scoped. A member can hold multiple built-in or custom roles; allowed grants combine additively, with ALL scope taking precedence over OWN.
- Permission grants support allow/deny and data scope (ALL or OWN).
- Existing companies receive OWNER, MANAGER, and STAFF roles through Migration 0035. New companies initialize those roles lazily when the owner first opens the role editor or assigns a member.
- New Google members in a one-company setup are assigned the default STAFF role while pending approval.
- Administrator APIs and a mobile-friendly role editor support custom roles, permission configuration, and multi-role membership assignment.
- The request middleware maps every published company API route to a permission code. Unknown routes fail closed.
- Cross-module operations require their dependent module grants as well. Examples include:
  - Catalog-backed sales require product, inventory-location, gold-price, and tender permissions.
  - Purchase drafts require supplier and product visibility; receiving also requires inventory-create permission.
  - Customer-order APIs require payment visibility because responses embed payment transactions; creating orders or recording deposits/refunds also requires the related payment/order permissions.
  - Supplier payments require both supplier-payables and payment permissions; payable bills linked to purchases require purchase visibility.
  - Gold-material settlement into supplier bills requires supplier-payables view/update, and referenced supplier/purchase visibility.
  - Daily closing and operational reports require the underlying sales, payments, supplier-payables, expenses, cash-drawer, and customer-order view grants represented in their summaries.
  - Bank reconciliation reports require bank-account visibility; statement-line adjustments also require permission to create bank ledger entries.
- Cross-module dependent grants must have ALL data scope; OWN scope cannot be used to bypass another module's row visibility.
- A record-actor registry records creator and last modifier for supported business records, distinguishing Google user IDs from the legacy owner username/password account.
- ORM reads on supported resources apply a creator filter when the effective primary data scope is OWN.

## Conservative defaults

| Role | Default grants |
| --- | --- |
| OWNER | All four actions, all company data |
| MANAGER | View only, all company data |
| STAFF | No permissions until the owner configures them |

OWN scope currently supports read/create only for independent transaction records in purchases, sales, customer orders, and operating expenses. Shared master data, inventory balances, bank/gold balances, reconciliation, supplier payables, cash drawer, and aggregate reports require ALL scope. Update and void under OWN are denied. Operations that touch dependent modules also require the appropriate dependent permission with ALL scope.

Historical rows are not assigned to a person by inference. Rows without a record-actor registry entry are not visible under an OWN-scoped permission. Existing owner access is unchanged.

## Validation completed

- CI passes on PostgreSQL 16 with a clean schema upgrade, full downgrade, clean re-upgrade, and final Alembic revision check.
- CI rolls the disposable database back to 0034, seeds two synthetic companies and three existing memberships, then upgrades to 0035 and verifies the 24-resource × 4-action catalogue, six company roles, 576 role grants, default-role baselines, and three membership-role backfills.
- CI checks every published `/companies/{company_id}/...` route in OpenAPI for an explicit permission mapping.
- CI covers cross-module permission dependencies, data-scope requirements, own-record filtering, member/role management, session lifecycle, and PostgreSQL inventory/reconciliation behavior.
- Playwright runs the role editor and multi-role member assignment in Chromium at a mobile viewport with deterministic API fixtures. Backend tests separately verify that administrator-only pages and APIs reject unauthenticated and Google-only access. The browser tests exercise the actual page JavaScript and user interactions, but do not claim a live authenticated browser test against production.
- Latest CI run: all checks successful. See the [GitHub Actions run](https://github.com/gold-jewelry-team/gold-jewelry-erp/actions).

## Remaining before employee rollout

- Perform a final owner-session smoke test against an isolated or staging deployment with Migration 0035 before employee rollout. The automated Chromium test uses API fixtures and does not replace this live authenticated check.
- Complete the Google OAuth end-to-end test with the new schema, while keeping the feature flag disabled until the owner explicitly approves activation.
- Complete employee-facing workspace and onboarding UX; do not invite employees until access tests and production migration have been approved.
- OWN-scope update and void remain intentionally unavailable until write paths can be consistently constrained to records created by the member.

## Production safety

Google OAuth remains disabled. Alembic Migration 0035 has not been applied to production Neon, and no production records were changed by this PR. A separate Neon production-data clone has not been created because the available Neon branch connector does not expose schema-only branching; copying live business data would need explicit approval.

Do not merge/deploy this PR, apply production Migration 0035, or enable Google OAuth until the owner has explicitly approved each respective step.
