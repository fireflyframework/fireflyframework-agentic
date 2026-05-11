# Rubric — Guardian (`guardian`)

The guardian agent minimises security, quality, and compliance risk
in the generated PR before the builder step consumes it. It is a
gate: a critical finding blocks the pipeline; the finding is fed
back to codegen for remediation.

## Hard criteria (must pass — blocks pipeline if violated)

- [ ] **No critical secrets**: no API keys, tokens, passwords, or
  private keys in committed files (checked with `trufflehog` or
  equivalent pattern scan).
- [ ] **No critical CVEs**: direct dependencies have no known CVEs
  rated CVSS ≥ 9.0.
- [ ] **No dangerous patterns**: no `eval(user_input)`, no raw SQL
  string concatenation, no `shell=True` with untrusted input.
- [ ] **License compliance**: all dependencies use permissive or
  weak-copyleft licenses (MIT, Apache-2, LGPL). GPL or proprietary
  licenses trigger a warning that must be acknowledged.

## Soft criteria (graded — do not block)

- **High CVEs**: dependencies with CVSS 7–9 are flagged with
  recommended upgrade paths.
- **Code complexity**: cyclomatic complexity > 15 per function is
  flagged.
- **Type safety**: missing type annotations on public functions are
  flagged.

## Output schema

```
guardian_report.md — human-readable finding list (markdown)
$GITHUB_OUTPUT:
  guardian_passed  — true|false
  critical_count   — integer
  warning_count    — integer
```

## Loss function

Loss = (critical_findings × 10) + (high_findings × 2) + (warning_count × 0.1).
Pipeline is blocked when loss > 0 for the hard-criteria dimensions.
