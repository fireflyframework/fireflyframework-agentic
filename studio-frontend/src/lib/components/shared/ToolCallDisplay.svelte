<script lang="ts">
  import { ChevronDown, ChevronRight, Wrench } from 'lucide-svelte';

  let { toolName, args = '', result = '', accentColor = '#6366f1' }: {
    toolName: string;
    args?: string;
    result?: string;
    accentColor?: string;
  } = $props();

  let expanded = $state(false);
</script>

<div class="tool-call" style="--accent: {accentColor}">
  <button class="tool-header" onclick={() => expanded = !expanded}>
    <Wrench size={14} style="color: var(--accent)" />
    <span class="tool-name">{toolName}</span>
    {#if expanded}
      <ChevronDown size={14} />
    {:else}
      <ChevronRight size={14} />
    {/if}
  </button>
  {#if expanded}
    <div class="tool-body">
      {#if args}
        <div class="tool-section">
          <span class="tool-label">Args</span>
          <pre>{args}</pre>
        </div>
      {/if}
      {#if result}
        <div class="tool-section">
          <span class="tool-label">Result</span>
          <pre>{result}</pre>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .tool-call {
    border: 1px solid var(--color-border);
    border-radius: 8px;
    margin: 6px 0;
    overflow: hidden;
    background: var(--color-bg-secondary);
  }
  .tool-header {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 8px 12px;
    border: none;
    background: none;
    color: var(--color-text-secondary);
    cursor: pointer;
    font-size: 0.8rem;
  }
  .tool-header:hover { background: var(--color-bg-hover); }
  .tool-name { font-weight: 500; flex: 1; text-align: left; }
  .tool-body {
    padding: 0 12px 8px;
    border-top: 1px solid var(--color-border);
  }
  .tool-section { margin-top: 8px; }
  .tool-label {
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    color: var(--color-text-muted);
    letter-spacing: 0.5px;
  }
  pre {
    margin: 4px 0 0;
    padding: 8px;
    border-radius: 4px;
    background: var(--color-code-bg);
    font-size: 0.75rem;
    overflow-x: auto;
    color: var(--color-text-primary);
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
