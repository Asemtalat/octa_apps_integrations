# Live audit — 2026-09-21

Baseline: `96dfd1f45d449a2776e529ed0bfc24c1f062a60c`.

## Evidence

- Existing Odoo application opens its dashboard (empty-state observed).
- Baseline isolated Python suites: 189 passed (10 + 8 + 25 + 7 + 4 + 135).
- Patched isolated Python suites: 190 passed (10 + 34 + 7 + 4 + 135).
- These results are NOT Odoo ORM or live provider certification results.
- Eight new Odoo regression tests (3 membership, 5 outbox) ran on Odoo.sh: total 37 tests, zero failures/errors, build 6ea71155. Four JS controller tests also passed. Backend order search/filter/reset empty states exercised in the live development database.

## Fixes in this branch

1. Reassigning a membership recomputes BOTH old and new users' security groups.
2. Membership scope changes invalidate cached record-rule domains. Inactive or transferred active contexts are cleared.
3. Stale processing and dispatch exceptions/invalid results go to awaiting confirmation, not blind resend.
4. Stale processing recovery skips database rows locked by another transaction.
5. Malformed query results remain inconclusive.
6. Pure idempotency tests moved to lib so Odoo tests have a dedicated discovery package.

## Known release blockers — not solved by this patch

- No production POS adapter/provider certification. Scheduled dispatch remains disabled.
- Crash after remote acceptance but before local transaction commit still needs a durable transaction-boundary design and remote idempotency validation.
- Concurrent database workers, lease ownership, retries and crash recovery need multi-transaction integration tests.
- Three-party portals, catalog publishing and all required UI screens are not complete.
- Merchant/partner end-to-end account journeys and full cross-tenant negative test matrix remain pending.
- Provider portal observations do not establish API availability or permission.

## Reproduce isolated tests

Install pytest in an isolated environment, then run:

```sh
python octa_connect/tools/run_all_tests.py
```

## Required Odoo acceptance

On an isolated Odoo 19 database, install core, API, UI and connector demo with tests enabled.
Verify explicit test counts/errors in logs; a green hosting build alone is insufficient.
Repeat module upgrade, then exercise live UI and negative permission tests.
Do not enable outbound dispatch or merge into the deployment branch before acceptance.

## Merchant portal — 2026-09-22

The backend is not the merchant portal. A separate authenticated workspace now
exists at `/octa/portal`, with a branded entry at `/octa/start`. It reuses Odoo
authentication, supports a non-internal Portal user, and serves a custom Arabic
HTML/CSS interface with overview, orders, connections, and account/branches.

- First portal build dfb9f8ad: 42 actual Odoo tests, zero failures/errors.
- Five HTTP tests cover all four sections, anonymous redirect, foreign-tenant
  refusal, suspended account, and revoked membership.
- Membership lookup uses sudo only with an authenticated-user filter. Business
  reads use normal ORM permissions plus explicit selected tenant/branch domains.
- Connections show technical, production-approval, and branch-readiness flags
  separately. These flags are stored values, not live health probes.
- Read-only scope: no menu publishing, account creation, external dispatch, or
  connector credential editing is added by this portal.
- MFA enforcement, real invitation delivery, English support, mobile visual
  acceptance, order detail/timeline and complete role journeys remain pending.
- Build 734137cc: 44 tests passed, including populated tenant/branch data checks,
  but demo loading failed on an invalid XML comment. Fixed in 65fd460e: build 38489007 SUCCESS,
  44 tests with zero failures/errors. Live browser verification covered dashboard,
  populated orders, exact order search, application readiness flags, account/branches.
  This browser check used the development administrator with a demo membership;
  non-internal Portal access was verified separately by HTTP acceptance tests.
  Demo preview creates no new credentials.
