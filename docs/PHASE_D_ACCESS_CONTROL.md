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
- Google login now redirects to a separate mobile-friendly `/employee` entry page instead of the administrator login/workspace.
- `GET /auth/google/workspace` returns only the signed-in user's own companies, membership states, assigned roles, and effective allowed permissions. Duplicate role grants combine additively and ALL data scope takes precedence over OWN.
- ACTIVE members can review their granted feature permissions and data scope. PENDING, REJECTED, SUSPENDED, and company-inactive members can see their own onboarding state but receive no business permissions. Rejected/suspended users may sign in for this self-service status view; company-scoped business APIs still require an ACTIVE membership and explicit permission on every request.
- The employee workspace is separate from the owner administration interface. The /employee page is the member's onboarding and permission overview; /employee/catalog is a separate read-only workspace for the first employee business features.
- The employee home page shows a feature link only when its effective view grant can pass the server's scope rules. Product lookup requires products.view with ALL scope. Inventory lookup requires both inventory.view and products.view with ALL scope because the stock API embeds product information. OWN-scoped grants for shared master data or stock balances are not presented as usable feature links.
- The catalog page supports company-scoped product search and stock-by-location lookup on mobile, tablet, and desktop. It sends read-only GET requests only; each API request still revalidates the Google session, exact active company membership, permission grants, data scope, and cross-module dependencies in middleware. The public page route serves only a static shell and does not itself grant access.
- Add a separate read-only `/employee/sales` workspace for sales and return history. Sales lookup supports sale number, product code, barcode, product name, status, and date filters; it displays line snapshots, payment method, totals, card amount, and fees only when the member can view sales data and has `payments.view` with ALL scope.
- Return history is available only when `sales_returns.view` and `sales.view` both have ALL scope, in addition to the sale-list payment visibility dependency. The page requires selecting an original completed sale because the current returns API is nested under a sale. It only performs GET requests and never creates sales, posts refunds, voids a sale, or changes inventory.
- Sales with OWN scope may be listed according to the existing record-actor filtering, but this does not grant access to company-wide returns. Every read continues to be authorized by the company-scoped API middleware.
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
- Playwright runs ten isolated Chromium UI tests covering role permission/scope editing, member multi-role assignment, employee permission summary/logout and pending-approval messaging, permission-aware product/inventory/sales navigation, product search, stock lookup, sales history filters, returns lookup, OWN-scope return restrictions, and hiding sales when the required ALL-scoped payment visibility is absent.
- API tests verify the employee workspace requires a valid Google session, only returns the signed-in user's own memberships, combines role grants additively with ALL taking precedence over OWN, hides all business permissions for PENDING/REJECTED/SUSPENDED memberships, and rejects revoked sessions. Mocked Google callback tests also verify rejected/suspended users can sign in to view their own status without receiving company grants.
- A separate authenticated Chromium end-to-end test starts the real FastAPI application against the disposable CI PostgreSQL database. It verifies an unauthenticated request receives 401, signs in through the legacy owner username/password flow, updates STAFF grants, creates a custom role, assigns STAFF plus the custom role to a member through the real administrator APIs, and verifies the persisted grants and membership-role rows directly in PostgreSQL.
- The role editor rejects stale asynchronous responses when company/role selections change and disables permission saving while new role data is loading.
- Latest CI run: 404 Python tests passed, 3 skipped; ten fixture-backed Chromium UI tests passed; the authenticated FastAPI/PostgreSQL browser end-to-end test passed; PostgreSQL Migration 0035 backfill, full downgrade, clean re-upgrade, and final revision checks passed. See the [GitHub Actions run](https://github.com/gold-jewelry-team/gold-jewelry-erp/actions/runs/45573759707).

## Remaining before employee rollout

- Perform a final owner-session smoke test against the intended staging deployment with Migration 0035 applied. CI E2E uses an isolated database and temporary owner credentials; it does not change or verify the production Render/Neon environment.
- Complete the Google OAuth end-to-end test with the new schema, while keeping the feature flag disabled until the owner explicitly approves activation.
- Extend the employee workspace beyond read-only product, inventory, sales, and return history. Sales checkout, refund payments, purchases, receiving, customer orders, stocktake, cash drawer, and other operational workflows still need dedicated employee-safe screens and action controls. Do not invite employees for daily operations until each workflow, staging tests, and production migration are approved.
- OWN-scope update and void remain intentionally unavailable until write paths can be consistently constrained to records created by the member.

## Production safety

Google OAuth remains disabled. Alembic Migration 0035 has not been applied to production Neon, and no production records were changed by this PR. A separate Neon production-data clone has not been created because the available Neon branch connector does not expose schema-only branching; copying live business data would need explicit approval.

Do not merge/deploy this PR, apply production Migration 0035, or enable Google OAuth until the owner has explicitly approved each respective step.
