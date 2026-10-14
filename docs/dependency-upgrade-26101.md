# Dependency resolution in 26.10.1

Copyright 2026 Firefly Software Foundation. SPDX-License-Identifier: Apache-2.0.

This release resolves the 23 Dependabot requests open on October 14, 2026 in one
combined dependency set. Several requests were older than changes already on
`main`; their obsolete diffs were not applied. The tables record how each
requested update is represented in the release.

## Runtime dependencies

| Request | Resolution |
| --- | --- |
| [#334: httpx2](https://github.com/fireflyframework/fireflyframework-agentic/pull/334) | Keep 2.13.1, already newer than the requested 2.12.0. |
| [#333: httpcore2](https://github.com/fireflyframework/fireflyframework-agentic/pull/333) | Keep 2.13.1, already newer than the requested 2.10.0. |
| [#332: pypdf](https://github.com/fireflyframework/fireflyframework-agentic/pull/332) | Require at least 6.19.0 and lock 6.20.1; the old 6.16.1 target misses later fixes. |
| [#330: h2](https://github.com/fireflyframework/fireflyframework-agentic/pull/330) | Lock 4.4.1 with hpack 4.2.0. |
| [#329: cryptography](https://github.com/fireflyframework/fireflyframework-agentic/pull/329) | Require at least 50.0.0 in the security extra; lock 50.0.2. Review platform changes below. |
| [#328: aiohttp](https://github.com/fireflyframework/fireflyframework-agentic/pull/328) | Lock 3.14.5, including the requested 3.14.3 corrections. |
| [#327: genai-prices](https://github.com/fireflyframework/fireflyframework-agentic/pull/327) | Keep the existing `>=0.1.9,<0.2` requirement and 0.1.9 lock. The requested range migration was already complete. |
| [#325: httplib2](https://github.com/fireflyframework/fireflyframework-agentic/pull/325) | Lock 0.32.0. |
| [#322: pyasn1](https://github.com/fireflyframework/fireflyframework-agentic/pull/322) | Lock 0.6.4. |
| [#321: Pillow](https://github.com/fireflyframework/fireflyframework-agentic/pull/321) | Require and lock 12.3.0. Retain pillow-heif; the original PR removed it. Register its HEIF decoder explicitly. |
| [#319: MCP](https://github.com/fireflyframework/fireflyframework-agentic/pull/319) | Lock MCP 2.3.0 and FastMCP 4.1.0, satisfying the patched-version intent and the current consumer protocol contract. |
| [#318: soupsieve](https://github.com/fireflyframework/fireflyframework-agentic/pull/318) | Lock 2.9.0; the requested 2.8.4 misses later fixes. |
| [#316: joserfc](https://github.com/fireflyframework/fireflyframework-agentic/pull/316) | Lock 1.6.8. |
| [#313: Pydantic AI](https://github.com/fireflyframework/fireflyframework-agentic/pull/313) | Preserve the completed 2.x migration and all provider extras, raise the minimum to 2.53.0, and lock 2.55.0. |
| [#290: py7zr](https://github.com/fireflyframework/fireflyframework-agentic/pull/290) | Require and lock 1.1.4, which completes the extraction fixes beyond the requested 1.1.3. Replace removed `readall()` with bounded in-memory extraction. |
| [#289: langsmith](https://github.com/fireflyframework/fireflyframework-agentic/pull/289) | Lock 0.8.18. |

The same lock refresh updates affected AnyIO, CairoSVG, datasets, fsspec,
langgraph-sdk, multidict, OAuthLib, PyJWT, PyMongo, urllib3 and virtualenv
dependencies. Virtualenv 21.7.13 contains the identified fixes while remaining
compatible with xAI's `packaging<26` requirement; the newest virtualenv requires
`packaging>=26.3` and cannot be substituted into that graph.

The resolved graph retains both httpx and httpx2 where their upstream users need
them. Do not remove one by renaming imports or forcing dependency overrides.
The runtime lock is a tested development resolution, not a transitive lock
embedded in the published wheel. Applications must resolve their selected extras
normally and qualify their own lock. See the [migration guide](migration.md#dependency-refresh-in-26101).

## Build, documentation and GitHub Actions

| Request | Resolution |
| --- | --- |
| [#326: uv-build](https://github.com/fireflyframework/fireflyframework-agentic/pull/326) | Allow `>=0.9.5,<0.13.0`; build and inspect wheel and source distributions. |
| [#320: MkDocs Material](https://github.com/fireflyframework/fireflyframework-agentic/pull/320) | Require `>=9.7.7,<10`, including the search-suggestion XSS fix. |
| [#317: setup-uv](https://github.com/fireflyframework/fireflyframework-agentic/pull/317) | Pin v9.0.0 by commit in all seven steps; retain cache pruning explicitly. |
| [#312: upload-pages-artifact](https://github.com/fireflyframework/fireflyframework-agentic/pull/312) | Pin v5.0.0 by commit. The generated site does not require hidden-file uploads. |
| [#311: cache](https://github.com/fireflyframework/fireflyframework-agentic/pull/311) | Pin v6.1.0 by commit. |
| [#310: deploy-pages](https://github.com/fireflyframework/fireflyframework-agentic/pull/310) | Pin v5.0.1 by commit, preserving the Pages artifact and permissions. |
| [#308: checkout](https://github.com/fireflyframework/fireflyframework-agentic/pull/308) | Pin v7.0.1 by commit in all nine steps, including the newer documentation check. |

GitHub-hosted Linux runners supply the Node 24 runtime required by these action
versions. Self-hosted runners need their own compatibility check. The release
workflow now generates `SHA256SUMS` alongside the wheel and source archive.

## Compatibility changes

Pydantic AI 2.53 changes concurrency-limiter ownership and release behavior;
2.55 includes rejected fallback attempts in usage accounting. Firefly continues
to accept native model objects and toolsets. Its option validator uses the
renamed `thinking_enabled_by_default` profile flag, preserving rejection of
sampling controls when reasoning is active. Explicit supported
`reasoning="none"` remains available.

Native limiter tests cover normal completion, early breaks, errors and
cancellation in both streaming modes, including subsequent capacity reuse.
Incremental streams close unfinished text iterators before their native context
exits. Fallback tests verify aggregate rejected-attempt token accounting on
2.55; applications needing that correction must require at least 2.55. These
checks do not establish separate dollar-cost attribution for each attempted
provider/model in a native fallback chain.

Mistral embeddings use the SDK 2 client module with a fallback to the 1.x import.
Tests run the installed 2.10.1 SDK against a local HTTP endpoint for single and
batched inputs and error propagation; no paid provider call is required.

Cryptography 49 removed macOS Intel and Windows 32-bit binary wheels. The 50.0.2
dependency requires platform qualification even though Agentic's own wheel is
pure Python. This release is qualified locally on macOS arm64 and in Linux CI;
it does not establish installation or operation on every platform.

The PostgreSQL namespace fix, schema, helper signatures, embedding widths and
pgvector/HNSW backend remain unchanged. No database migration is required.

## Remaining optional-package advisories

The release is not a claim of zero vulnerabilities. Comparing the resolved lock
with the 100 open GitHub alerts captured on October 14 leaves six matching
advisories: two for Ragas 0.2.6 and four for ChromaDB 1.5.9. That comparison is a
dated inventory, not a complete security assessment or a guarantee about future
advisories. No residual alert was dismissed to make the count smaller.

Ragas remains at 0.2.6 because newer compatible-looking releases either patch
asyncio during import or require an Instructor `jiter` range incompatible with
the OpenAI SDK. The affected package contains image-loading code covered by
[arbitrary file read](https://github.com/advisories/GHSA-v2xr-wvrv-p969) and
[multimodal SSRF](https://github.com/advisories/GHSA-95ww-475f-pr4f) advisories.
Firefly's five Ragas metrics use text samples and fixed text metrics; no direct
call to those image loaders was found in this adapter. This does not repair or
clear the dependency advisory. Do not expose upstream multimodal evaluation to
untrusted inputs; use isolated workers with restricted filesystem and egress
access when evaluating untrusted data.

ChromaDB 1.5.9 is still the latest published version inspected, and its four
alerts have no published patched version:
[code injection](https://github.com/advisories/GHSA-36p7-vc44-83pf),
[cross-tenant data access](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr),
[incomplete RBAC scoping](https://github.com/advisories/GHSA-xph7-9rjv-w5fr), and
[pre-authentication code injection](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c).
The default Agentic adapter creates an embedded client, but callers can provide
HTTP clients. Restrict access to trusted processes and configurations. Do not
expose affected servers to untrusted clients or rely on their built-in RBAC or
Agentic namespace metadata as a tenant authorization boundary. Use separate
instances for direct clients in different trust domains. Applications that
cannot satisfy those restrictions should select a different supported backend.

The Chroma adapter combines namespace and metadata predicates with `$and` so an
equality filter cannot replace the requested namespace. It still shares document
IDs across its collection; its namespace behavior does not inherit PostgreSQL's
26.10.0 write-conflict guarantee. See [vector-store authorization](security.md#vector-store-authorization).
