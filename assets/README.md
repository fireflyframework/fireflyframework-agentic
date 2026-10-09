# Firefly Agentic brand assets

Firefly Agentic uses the lowercase `agentic` wordmark in Manrope 500, with the
original Firefly trail on its terminal `c` and the unchanged `by firefly`
endorsement. Charcoal, ivory, and amber connect the documentation to the
[Framework family](https://github.com/fireflyframework). The product and API
name remains Firefly Agentic.

## Diagrams

Each diagram answers one question. The architecture view groups capabilities;
the agent view explains a run; the model view explains provider and API selection.
They do not imply that every optional module runs by default or that every provider
supports the same features.

| Asset | Dimensions | Purpose |
|-------|------------|---------|
| [`brand-logo.svg`](brand-logo.svg), [`brand-logo-light.svg`](brand-logo-light.svg) | Original master viewBox | Outlined Agentic lockup for dark and light surfaces. The dark-surface variant is also generated as `logo.svg`. |
| [`banner.svg`](banner.svg), [`banner-light.svg`](banner-light.svg) | 1600 × 480 | Canonical Agentic lockup and “Intelligence, composed.” in both themes. |
| [`favicon.svg`](favicon.svg) | 128 × 128 | The exact terminal `c` path and original trail gradient on charcoal. |
| [`architecture.svg`](architecture.svg) | 1100 × 710 | FireflyAgent, tools, memory and model configuration, with optional composition around the Pydantic AI 2 engine. |
| [`agent-anatomy.svg`](agent-anatomy.svg) | 1100 × 760 | A normal successful agent run, with default and optional middleware shown separately. |
| [`model-routing.svg`](model-routing.svg) | 1100 × 690 | Effective model selection and ModelOptions validation; explicit Chat, Responses and other provider routes. |
| [`protocols.svg`](protocols.svg) | 1100 × 680 | Selected public extension contracts, with protocols distinguished from abstract base classes and configuration. |
| [`reasoning.svg`](reasoning.svg) | 1100 × 590 | Four patterns using the base loop, two with custom execution strategies, and their shared result/trace contracts. |
| [`pipeline.svg`](pipeline.svg) | 1100 × 690 | An example document-processing DAG plus the separate roles of Pause, Send, cycles, checkpoints and audit sinks. |
| [`workflows.svg`](workflows.svg) | 1100 × 710 | Python workflow primitives, context, runners, journal replay and resource budgets. |
| [`rag.svg`](rag.svg) | 1100 × 660 | Eight embedding providers, six vector backends and the indexing/query flow; compatibility remains a configuration concern. |
| [`ecosystem.svg`](ecosystem.svg) | 1100 × 672 | Related Firefly projects, without implying API or feature parity across runtimes. |

`docs/assets/` contains byte-identical generated copies of all 15 assets,
including the header logo and favicon.

## Design system

- **Wordmark:** canonical outlined masters are recorded in
  [`tools/brand-source/ORIGIN.json`](tools/brand-source/ORIGIN.json), including
  their original export and normalized vendored SHA-256 hashes, plus the
  canonical website generator hash. Generation
  verifies the vendored hashes before using the artwork. Nested endorsement dimensions
  are retained when placing a master.
- **Palette:** charcoal `#10110f`, ivory `#f3f1eb`, amber `#ffb34a`, graphite
  `#272820`, muted text `#62645b`, and border `#d8d4ca`. Amber title bands use
  charcoal text; graphite title bands use ivory text. The generator checks
  text contrast of at least 4.5:1; the current minimum is 5.32:1.
- **Typography:** system sans text, with 16 px card headings and generally
  14 px body text. Each view uses separate cards and generous spacing instead
  of dense inventories. Display diagrams at their natural aspect ratio and
  provide a link to the full-size SVG when embedding them at reduced widths.
  The documentation uses bundled Manrope with its
  [SIL Open Font License](../docs/assets/fonts/OFL.txt); logos remain outlined.
- **Accessibility:** every technical diagram has a title, a descriptive text
  alternative and `role="img"`. Titles and descriptions explain the
  relationships, not only the file name. Brand masters retain their canonical
  titles; embedding pages provide useful image alt text.
- **Self-contained output:** no scripts, external images, external fonts or
  remote resource references. Wordmark and brand icons are vendored vector paths.

## Regenerating

The standard-library generator runs with Python 3.13 or later:

```bash
python assets/tools/build_brand_assets.py
python assets/tools/build_brand_assets.py --check
```

The build writes the logo variants, banner variants, favicon, and nine diagrams
to both `assets/` and `docs/assets/`. `--check` regenerates them in memory and exits unsuccessfully if
any file is missing or differs; it does not change files. Both modes check card
geometry and measured text fit. Fixed embedded character advances make layout
identical across operating systems; the generator does not inspect local fonts.
Rendering can use a different system fallback font, so visual inspection remains
necessary after changes.

The generator reads the verified masters from `tools/brand-source/` and brand
icons from [`tools/icons.py`](tools/icons.py). To refresh the identity, export
the canonical masters and record their original bytes as `sourceSha256`.
Normalize only trailing LF bytes to exactly one LF (`data.rstrip(b"\n") + b"\n"`),
record the vendored bytes as `sha256`, and regenerate. The generator applies
the same EOF normalization to every output and its documentation mirror.
Edit diagram
layout in [`tools/build_brand_assets.py`](tools/build_brand_assets.py), rather
than editing output SVGs independently. Brand ownership terms are recorded in
[`tools/brand-source/NOTICE.md`](tools/brand-source/NOTICE.md).

## Previewing and checking

CairoSVG is a rendering tool, not a dependency of asset generation. It is also
available with the framework's `[binary]` extra. An isolated preview command is:

```bash
uv run --no-project --with cairosvg python -c "import cairosvg; cairosvg.svg2png(url='assets/model-routing.svg', write_to='/tmp/firefly-model-routing.png')"
```

After changing a diagram, render it at its native size and inspect text fit,
arrow endpoints, spacing and contrast. The automatic card check does not prove
that every label or connector is visually clear. Check the documentation's
responsive rendering too, then run `--check` to verify both generated locations.
