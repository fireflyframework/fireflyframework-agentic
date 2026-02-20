# Firefly Studio Frontend

SvelteKit 5 frontend for [Firefly Studio](../docs/studio.md) -- the visual
agent IDE for the Firefly GenAI framework.

## Prerequisites

- Node.js 20+
- npm (or pnpm)
- Python backend running (`firefly studio --dev` or see below)

## Setup

```bash
npm install
```

## Development

Start the Vite dev server with hot module replacement:

```bash
npm run dev
```

The frontend runs at `http://localhost:5173`. The Python backend must be
running separately (the backend's CORS config allows this origin):

```bash
# In another terminal
firefly studio --no-browser --dev
```

## Build

Build the static SPA for production:

```bash
npm run build
```

Output goes to `build/`. To bundle it into the Python package:

```bash
cp -r build/* ../src/fireflyframework_genai/studio/static/
```

## Type Check

```bash
npm run check
```

## Tech Stack

| Technology | Purpose |
|---|---|
| [SvelteKit 2](https://svelte.dev/docs/kit) | Application framework |
| [Svelte 5](https://svelte.dev/) | UI components (runes: `$state`, `$derived`, `$effect`, `$props`) |
| [@xyflow/svelte](https://svelteflow.dev/) | Node graph canvas |
| [Tailwind CSS 4](https://tailwindcss.com/) | Utility-first styling |
| [Lucide Svelte](https://lucide.dev/) | Icon library |
| [Vite 7](https://vite.dev/) | Build tool |

## Project Structure

```
src/
  routes/                    # SvelteKit file-based routing
    build/+page.svelte       # Main canvas workspace
    evaluate/+page.svelte    # Evaluation page
    experiments/+page.svelte # Experiments page
    deploy/+page.svelte      # Deployment page
    monitor/+page.svelte     # Monitoring page
    files/+page.svelte       # File management page
  lib/
    components/
      layout/                # AppShell, Sidebar, TopBar, CommandPalette, ShortcutsModal
      canvas/                # Canvas, NodePalette, node components (Agent, Tool, Reasoning, Condition)
      panels/                # BottomPanel, ConfigPanel, ChatTab, CodeTab, ConsoleTab, TimelineTab
    stores/                  # Svelte writable stores (pipeline, execution, ui, chat, project)
    api/                     # REST client (client.ts), WebSocket client (websocket.ts)
    execution/               # Execution bridge (bridge.ts)
    types/                   # TypeScript type definitions (graph.ts)
  app.css                    # Global styles, CSS custom properties, focus-visible ring
```

## Design Language

Dark, premium developer-tool aesthetic. All colors via CSS custom properties.
No emojis -- icons only (Lucide). See [docs/studio.md](../docs/studio.md#frontend-development)
for the full design specification.
