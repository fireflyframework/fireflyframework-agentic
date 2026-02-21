<script lang="ts">
  let { role, content, agentName = '', accentColor = '#6366f1', timestamp = '' }: {
    role: 'user' | 'assistant';
    content: string;
    agentName?: string;
    accentColor?: string;
    timestamp?: string;
  } = $props();
</script>

<div class="message {role}" style="--accent: {accentColor}">
  <div class="message-header">
    {#if role === 'assistant' && agentName}
      <span class="agent-badge" style="background: var(--accent); color: #fff">{agentName}</span>
    {:else}
      <span class="user-badge">You</span>
    {/if}
    {#if timestamp}
      <span class="timestamp">{timestamp}</span>
    {/if}
  </div>
  <div class="message-body">
    {@html content}
  </div>
</div>

<style>
  .message {
    padding: 12px 16px;
    border-radius: 12px;
    margin-bottom: 8px;
    animation: slideIn 0.2s ease;
  }
  .message.assistant {
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-border);
  }
  .message.user {
    background: var(--color-accent-muted);
    border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent);
  }
  .message-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  .agent-badge, .user-badge {
    font-size: 0.7rem;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .user-badge {
    background: var(--color-bg-hover);
    color: var(--color-text-secondary);
  }
  .timestamp {
    font-size: 0.65rem;
    color: var(--color-text-muted);
  }
  .message-body {
    font-size: 0.875rem;
    line-height: 1.6;
    color: var(--color-text-primary);
  }
  .message-body :global(p) { margin: 0.4em 0; }
  .message-body :global(code) {
    background: var(--color-code-bg);
    padding: 1px 5px;
    border-radius: 4px;
    font-size: 0.8rem;
  }
  .message-body :global(pre) {
    background: var(--color-code-bg);
    border: 1px solid var(--color-code-border);
    border-radius: 8px;
    padding: 12px;
    overflow-x: auto;
    margin: 8px 0;
  }
  @keyframes slideIn {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>
