# Rubric — Builder (`builder`)

The builder agent minimises the gap between a green PR and a
deployable, verified artifact (OCI image, static bundle, or binary).

## Hard criteria (must pass)

- [ ] **Build succeeds**: the build command exits 0 and produces an
  artifact at the expected path.
- [ ] **Artifact present**: the output directory or image reference
  is non-empty and parseable.
- [ ] **No vulnerabilities above threshold**: container image scan
  (Trivy or equivalent) reports zero CRITICAL CVEs.
- [ ] **Size within bounds**: artifact size ≤ limit declared in
  `architecture.yaml.quality.max_artifact_mb` (default 200 MB for
  container images, 50 MB for static bundles).

## Soft criteria

- **Build reproducibility**: given the same source SHA, two
  consecutive builds produce byte-identical artifacts (or the
  digest difference is documented).
- **Layer efficiency**: for OCI images, no layer exceeds 100 MB.
- **Build time**: build completes in ≤ 10 minutes.

## Output schema

```
build_report.json:
  {
    "artifact_ref": "...",   # image digest or bundle path
    "size_mb": 42.1,
    "build_time_s": 180,
    "vulnerabilities": {"critical": 0, "high": 2}
  }
$GITHUB_OUTPUT:
  artifact_ref   — string
  build_passed   — true|false
```
