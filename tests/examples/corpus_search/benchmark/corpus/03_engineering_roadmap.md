# Acme Corp — Engineering Roadmap 2026

Owner: Inès Laurent (CTO). Last updated 2026-01-15.

## North-star bets for 2026

1. **Acme Bolt API v3** — generally available Q3 2026.
2. **Rust migration** for the document-rendering core. Phase-1 (PDF generator)
   complete by 2026-Q4, full migration by 2027.
3. **Postgres 17 upgrade** in production by Q2 2026 (currently on Postgres 14).
4. **Python 3.13 SDK** released alongside API v3.

## API v3 highlights

- New **/sign/batch** endpoint for up to 5,000 signatures per call.
- Webhooks: **at-least-once delivery**, **HMAC-SHA256** signing.
- Rate limits raised from 500 RPS to **1,000 RPS** per tenant.
- Backwards-compatible with v2 for at least 18 months post-GA.

## Rust migration phases

| Phase | Scope | Target |
|-------|-------|--------|
| 1 | PDF rendering library (forms, watermarks) | 2026-Q4 |
| 2 | Crypto / signing engine | 2027-Q1 |
| 3 | Document parser + diff | 2027-Q2 |
| 4 | Sunset Go-based legacy renderer | 2027-Q3 |

Performance target after phase 1: **3× throughput on PDF rendering**, **45%
lower memory** on the document-render fleet.

## Postgres 17 upgrade

Currently running Postgres 14. Upgrade plan:
- January 2026: spin up shadow replicas on PG17 (done).
- March 2026: cut over reporting workloads.
- May 2026: cut over primary OLTP cluster (zero-downtime via logical replication).
- June 2026: decommission PG14.

## Reliability targets (2026)

- **API availability SLO: 99.95%** (matches Acme Bolt customer SLA).
- **p99 latency: <150ms** for /sign endpoints in EMEA region.
- Multi-region failover: **AZ-eu-west-1 → AZ-eu-west-2** within 90 seconds.

## Tooling and platform

- Migrating from CircleCI to **GitHub Actions** by April 2026.
- Adopting **Bazel** for the polyglot Rust+Python+Go monorepo.
- Test framework consolidating on **pytest** (Python) and **cargo nextest** (Rust).

## Hiring plan

Engineering will grow from 142 to ~180 by year-end. Priority hires:
- Senior Rust engineers (4)
- Site reliability engineers (3) for the Madrid office
- Developer relations (2)
