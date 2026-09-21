# Live audit — 2026-09-21

Baseline: `96dfd1f45d449a2776e529ed0bfc24c1f062a60c`.

## Evidence

- Existing Odoo application opens its dashboard (empty-state observed).
- Baseline isolated Python suites: 189 passed (10 + 8 + 25 + 7 + 4 + 135).
- Patched isolated Python suites: 190 passed (10 + 34 + 7 + 4 + 135).
- These results are NOT Odoo ORM or live provider certification results.
- Eight new Odoo regression tests are added (3 membership, 5 outbox); runtime result pending.

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
