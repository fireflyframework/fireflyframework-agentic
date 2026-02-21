<script lang="ts">
  let { accentColor = '#6366f1', messages = ['Thinking...'] }: {
    accentColor?: string;
    messages?: string[];
  } = $props();

  let messageIndex = $state(0);

  $effect(() => {
    const interval = setInterval(() => {
      messageIndex = (messageIndex + 1) % messages.length;
    }, 3000);
    return () => clearInterval(interval);
  });
</script>

<div class="thinking" style="--accent: {accentColor}">
  <div class="thinking-dots">
    <span class="dot"></span>
    <span class="dot"></span>
    <span class="dot"></span>
  </div>
  <span class="thinking-text">{messages[messageIndex]}</span>
</div>

<style>
  .thinking {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    border-radius: 12px;
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-border);
    animation: fadeIn 0.3s ease;
  }
  .thinking-dots {
    display: flex;
    gap: 4px;
  }
  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent);
    animation: bounce 1.4s infinite ease-in-out both;
  }
  .dot:nth-child(1) { animation-delay: -0.32s; }
  .dot:nth-child(2) { animation-delay: -0.16s; }
  .thinking-text {
    font-size: 0.8rem;
    color: var(--color-text-secondary);
    font-style: italic;
  }
  @keyframes bounce {
    0%, 80%, 100% { transform: scale(0); }
    40% { transform: scale(1); }
  }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>
