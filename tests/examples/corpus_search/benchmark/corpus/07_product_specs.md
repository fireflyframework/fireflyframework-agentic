# Acme Bolt — Product Specifications (API v2)

Document maintained by: Product Engineering. Version: 2.14.3. Last updated 2026-02-10.

## Service Level Agreement

- **API availability SLA: 99.95%** measured monthly across all regions.
- **Credit schedule**:
  - <99.95% but ≥99.90%: 10% credit
  - <99.90% but ≥99.50%: 25% credit
  - <99.50%: 50% credit
- **Excluded windows**: scheduled maintenance announced ≥7 days in advance
  (max 4 hours/quarter).
- **Status page**: https://status.acmecorp.example

## Rate limits (API v2)

| Endpoint class | Limit | Burst |
|---------------|-------|-------|
| `/sign/*`     | **500 RPS** per tenant | 1.5× for 30s |
| `/documents/*`| 1,000 RPS per tenant | 1.5× for 30s |
| `/audit/*`    | 100 RPS per tenant | 2× for 60s |
| Webhooks (outbound) | 50 deliveries/s per tenant | n/a |

API v3 will raise the `/sign/*` limit to **1,000 RPS** per tenant (see
the Engineering Roadmap document).

## Region failover

Primary regions and their secondaries:

| Primary | Secondary | RTO |
|---------|-----------|-----|
| AZ-eu-west-1 (Ireland) | AZ-eu-west-2 (London) | 90 seconds |
| AZ-us-east-1 (N. Virginia) | AZ-us-west-2 (Oregon) | 120 seconds |
| AZ-sa-east-1 (São Paulo) | AZ-us-east-1 (cross-continental, opt-in) | 5 minutes |

Failover is automatic for AZ-eu-west-1 and AZ-us-east-1; sa-east-1 to a
cross-continental region requires explicit opt-in due to data-residency
considerations (see Privacy Policy).

## Document size limits

- Per-document: **50 MB** (PDF, DOCX, JPG, PNG)
- Per-batch sign: 100 documents
- Total batch payload: **500 MB**
- Concurrent in-flight signatures per tenant: 250

## Webhook signing

Webhooks are signed with HMAC-SHA256 using a per-tenant rotating secret.
Signature header: `X-Acme-Signature: t=<timestamp>,v1=<hex>`. Tolerance
window: 5 minutes for replay protection.

## Supported file formats

- **PDF** (1.7 / 2.0)
- **DOCX** (Office Open XML)
- **JPG / JPEG, PNG** (auto-converted to single-page PDF)
- TIFF (deprecated; planned removal Q4 2026)

## Audit log retention

Customer-facing audit logs: **24 months** online, **7 years** archived.
Compliance audit logs (immutable, eIDAS qualified signatures only):
**10 years**.

## Pricing tiers (summary)

- **Starter**: $99/month, 100 sign-events
- **Growth**: $499/month, 1,500 sign-events, webhook delivery
- **Scale**: $1,999/month, 10,000 sign-events, multi-region, SSO
- **Enterprise**: custom pricing, includes BAA, CMEK, dedicated TAM
