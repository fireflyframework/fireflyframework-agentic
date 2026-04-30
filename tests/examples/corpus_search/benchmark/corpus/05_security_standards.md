# Acme Corp — Security & Compliance Standards

Owner: Marcus Lee (CFO, security oversight). Last reviewed 2026-02-01.

## Certifications and attestations

- **ISO/IEC 27001:2022** — certified since **November 2020**, last audit
  passed in November 2025 with no major findings.
- **SOC 2 Type II** — annual report covering Trust Service Criteria for
  Security, Availability, and Confidentiality. Latest report period:
  October 2024 – September 2025.
- **GDPR** — full compliance via Standard Contractual Clauses for any
  data leaving the EEA.
- **HIPAA Business Associate Agreement** available for healthcare-vertical
  customers (signed Q3 2025 with 14 customers).
- **eIDAS-compliant qualified signatures** through partnership with
  Trustico-PT since 2022.

## Authentication

- **Multi-Factor Authentication (MFA)** is **mandatory** for all employee
  and customer-administrator accounts. Supported factors: TOTP, hardware
  WebAuthn keys (FIDO2), push to Acme Authenticator mobile app.
- Passwords: minimum 14 characters, checked against the HaveIBeenPwned
  Pwned Passwords API (k-anonymity).
- SSO: SAML 2.0 and OpenID Connect supported for enterprise tenants.

## Encryption

- **At rest**: AES-256-GCM for all customer documents, with per-tenant
  envelope keys managed in AWS KMS.
- **In transit**: TLS 1.3 only; older TLS versions are blocked at the
  load balancer.
- Customer-managed encryption keys (CMEK) available for Enterprise tier.

## Vulnerability management

- Bug bounty program on HackerOne with payouts up to **$25,000** for
  critical findings. 47 valid reports in 2025.
- Quarterly external penetration tests by NCC Group.
- Internal SAST scanning on every commit (Snyk, Semgrep).

## Incident response

- 24/7 on-call rotation through PagerDuty.
- Customer notification within **72 hours** of confirmed material breach
  (matches GDPR Article 33).
- Post-incident reports published in the customer trust portal.

## Data residency

Customer data is stored exclusively in the region selected at signup:
- EU customers: **eu-west-1 (Ireland)**
- Brazil customers: **sa-east-1 (São Paulo)**
- US customers: **us-east-1 (N. Virginia)**

Cross-region replication is opt-in only, never automatic.

## Auditor

The current SOC 2 auditor is **Sensiba LLP**.
