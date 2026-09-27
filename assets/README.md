# Firefly Agentic brand assets

Firefly Agentic shares the [Firefly Framework](https://github.com/fireflyframework)
wordmark and amber firefly glow-dot, with a violet palette for the agentic project.
These SVGs appear in the README and documentation site.

## Diagrams

Each diagram answers one question. The architecture view groups capabilities;
the agent view explains a run; the model view explains provider and API selection.
They do not imply that every optional module runs by default or that every provider
supports the same features.

| Asset | Dimensions | Purpose |
|-------|------------|---------|
| [`banner.svg`](banner.svg) | 1280 × 320 | Firefly wordmark, Agentic lockup and a constellation of connected agents. |
| [`architecture.svg`](architecture.svg) | 1100 × 710 | FireflyAgent, tools, memory and model configuration, with optional composition around the Pydantic AI 2 engine. |
| [`agent-anatomy.svg`](agent-anatomy.svg) | 1100 × 760 | A normal successful agent run, with default and optional middleware shown separately. |
| [`model-routing.svg`](model-routing.svg) | 1100 × 690 | Effective model selection and ModelOptions validation; explicit Chat, Responses and other provider routes. |
| [`protocols.svg`](protocols.svg) | 1100 × 680 | Selected public extension contracts, with protocols distinguished from abstract base classes and configuration. |
| [`reasoning.svg`](reasoning.svg) | 1100 × 590 | Four patterns using the base loop, two with custom execution strategies, and their shared result/trace contracts. |
| [`pipeline.svg`](pipeline.svg) | 1100 × 690 | An example document-processing DAG plus the separate roles of Pause, Send, cycles, checkpoints and audit sinks. |
| [`workflows.svg`](workflows.svg) | 1100 × 710 | Python workflow primitives, context, runners, journal replay and resource budgets. |
| [`rag.svg`](rag.svg) | 1100 × 660 | Eight embedding providers, six vector backends and the indexing/query flow; compatibility remains a configuration concern. |
| [`ecosystem.svg`](ecosystem.svg) | 1100 × 672 | Related Firefly projects, without implying API or feature parity across runtimes. |

`docs/assets/` contains byte-identical generated copies for the documentation
site. Its `logo.svg` and `favicon.svg` are separate site identity assets and are
not produced by this generator.

## Design system

- **Wordmark:** the shared Firefly logo is embedded as vector paths, including
  the amber glow-dot. No image or font download is required.
- **Palette:** violet `#8b5cf6`, `#7c3aed` and `#6d28d9`; deep violet `#4c1d95`;
  ink `#1e1633`; body text `#322b45`; light panel `#f5f2fe`; stroke `#e4def5`.
  The shared glow-dot uses `#FFF9C1` to `#F68000`.
- **Typography:** system sans text, with 16 px card headings and generally
  14 px body text. Each view uses separate cards and generous spacing instead
  of dense inventories. Display diagrams at their natural aspect ratio and
  provide a link to the full-size SVG when embedding them at reduced widths.
- **Accessibility:** every SVG has a title, a descriptive text alternative and
  `role="img"`. Titles and descriptions explain the relationships, not only the
  file name. Embedding pages should still provide useful image alt text.
- **Self-contained output:** no scripts, external images, external fonts or
  remote resource references. Wordmark and brand icons are vendored vector paths.

## Regenerating

The standard-library generator runs with Python 3.13 or later:

```bash
python assets/tools/build_brand_assets.py
python assets/tools/build_brand_assets.py --check
```

The build writes the banner and nine diagrams to both `assets/` and
`docs/assets/`. `--check` regenerates them in memory and exits unsuccessfully if
any file is missing or differs; it does not change files. Both modes check card
geometry and measured text fit. Fixed embedded character advances make layout
identical across operating systems; the generator does not inspect local fonts.
Rendering can use a different system fallback font, so visual inspection remains
necessary after changes.

The generator imports the wordmark from [`tools/wordmark.py`](tools/wordmark.py)
and brand icons from [`tools/icons.py`](tools/icons.py). Those local sources and
[`tools/build_brand_assets.py`](tools/build_brand_assets.py) are authoritative;
edit them and regenerate instead of editing the resulting SVGs independently.

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
