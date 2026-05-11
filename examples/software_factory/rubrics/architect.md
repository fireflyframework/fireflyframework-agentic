# Rubric — Architect (`architect`)

The architect agent minimises the gap between a PRD/SPEC and an ADR +
`architecture.yaml` that gives `codegen` everything it needs to generate
correct, idiomatic code without making architectural decisions itself.

## Hard criteria (must pass)

- [ ] **PRD coverage**: every Acceptance Criterion in `spec.yaml` is
  addressed by at least one module or contract in `architecture.yaml`.
- [ ] **Archetype exists**: `architecture.yaml.archetype` must resolve to a
  real directory in `knowledge_base/archetypes/`.
- [ ] **ADR decision present**: the ADR Decision section states the chosen
  approach and explicitly rejects at least one alternative.
- [ ] **Contracts defined**: every module boundary in `architecture.yaml`
  has an explicit interface contract (API schema, event schema, or
  function signature).
- [ ] **Stack declared**: `architecture.yaml.stack` is set to a supported
  value (e.g. `pyfly`, `static`, `container`).

## Soft criteria

- **Minimality**: number of modules = minimum needed to satisfy the PRD.
  Each extra module added must be justified in the ADR.
- **Dependency direction**: no circular dependencies between modules.
- **Cost estimate**: ADR includes a rough LLM cost estimate for the
  codegen step (tokens × model rate).

## Output schema

```
ADR.md             — Architecture Decision Record (markdown)
architecture.yaml  — machine-readable: archetype, modules, contracts, stack
```

## Loss function (self-evaluation prompt)

After generating both outputs, the architect re-reads `spec.yaml` and
answers for each Acceptance Criterion:

1. Which module(s) implement this criterion?
2. Is the interface contract between those modules explicit in architecture.yaml?

Any unanswered criterion is a gap; the agent revises. Max 2 rounds.
