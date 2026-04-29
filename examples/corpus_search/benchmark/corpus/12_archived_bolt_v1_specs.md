# Acme Bolt — Product Specifications (API v1) [ARCHIVED]

> **This document is ARCHIVED. It describes API v1, which was deprecated in
> October 2023. For current specifications please refer to the API v2 document.**

Document maintained by: Product Engineering. Version: 1.9.0. Last updated 2023-09-01.

## Service Level Agreement (v1 — DEPRECATED)

- **API availability SLA: 99.90%** measured monthly.
- Credit schedule:
  - <99.90% but ≥99.50%: 15% credit
  - <99.50%: 35% credit
- No scheduled-maintenance exclusion window in v1.

## Rate limits (API v1 — DEPRECATED)

| Endpoint class | Limit |
|---------------|-------|
| `/sign/*`     | **200 RPS** per tenant |
| `/documents/*`| 500 RPS per tenant |
| `/audit/*`    | 50 RPS per tenant |

Note: API v2 raised these limits significantly. The current `/sign/*` limit is
500 RPS (see the current product specifications document).

## Document size limits (v1 — DEPRECATED)

- Per-document: **10 MB**
- Per-batch sign: 20 documents
- No bulk batch endpoint in v1.

## Pricing tiers (v1 — SUPERSEDED)

- **Starter**: $49/month, 50 sign-events
- **Growth**: $249/month, 500 sign-events
- **Scale**: $999/month, 3,000 sign-events

Pricing was revised substantially in v2. Current pricing is available in the
current Product Specifications document.

## Webhook signing (v1 — DEPRECATED)

API v1 webhooks used a shared static secret. Rotating per-tenant HMAC-SHA256
signing was introduced in API v2.

## Migration guide

Customers on API v1 must migrate before **December 31, 2023**. Migration guide:
- Replace all `/api/v1/` prefixes with `/api/v2/`.
- Update authentication to use the new OAuth2 client-credentials flow.
- Adjust rate-limit handling: new burst allowance (1.5×) may require backoff
  logic changes.
- Test webhook signature verification against the new HMAC-SHA256 scheme.
