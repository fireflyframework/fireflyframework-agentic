<script lang="ts">
	import { smithCode, smithMessages, smithIsThinking, chatWithSmith, executeCode, generateCode, pendingCommand, approveCommand, connectSmith, disconnectSmith, syncCanvasToSmith } from '$lib/stores/smith';
	import ThinkingIndicator from '$lib/components/shared/ThinkingIndicator.svelte';
	import ChatMessage from '$lib/components/shared/ChatMessage.svelte';
	import ToolCallDisplay from '$lib/components/shared/ToolCallDisplay.svelte';
	import CommandApprovalModal from '$lib/components/shared/CommandApprovalModal.svelte';
	import { Copy, Play, RefreshCw, Send, Loader } from 'lucide-svelte';
	import { nodes, edges } from '$lib/stores/pipeline';
	import { get } from 'svelte/store';
	import { onMount, onDestroy } from 'svelte';

	let chatInput = $state('');
	let messagesContainer: HTMLDivElement;
	let copied = $state(false);

	onMount(() => {
		connectSmith();
	});

	onDestroy(() => {
		disconnectSmith();
	});

	function handleCopy() {
		const code = get(smithCode);
		if (code) {
			navigator.clipboard.writeText(code);
			copied = true;
			setTimeout(() => copied = false, 2000);
		}
	}

	function handleRefresh() {
		const graph = {
			nodes: get(nodes).map((n: any) => ({ id: n.id, type: n.type, data: n.data, position: n.position })),
			edges: get(edges).map((e: any) => ({ id: e.id, source: e.source, target: e.target }))
		};
		generateCode(graph);
	}

	function handleRun() {
		const code = get(smithCode);
		if (code) {
			executeCode(code);
		}
	}

	function handleSend() {
		const msg = chatInput.trim();
		if (!msg) return;
		chatInput = '';
		chatWithSmith(msg);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSend();
		}
	}

	// Auto-scroll messages
	$effect(() => {
		$smithMessages;
		$smithIsThinking;
		if (messagesContainer) {
			requestAnimationFrame(() => {
				messagesContainer.scrollTop = messagesContainer.scrollHeight;
			});
		}
	});
</script>

<div class="smith-container">
	<!-- Toolbar -->
	<div class="smith-toolbar">
		<span class="smith-label">Smith</span>
		<div class="toolbar-actions">
			<button class="toolbar-btn" onclick={handleCopy} title="Copy code">
				<Copy size={14} />
				{#if copied}
					<span class="copied-text">Copied!</span>
				{/if}
			</button>
			<button class="toolbar-btn" onclick={handleRun} title="Run code">
				<Play size={14} />
			</button>
			<button class="toolbar-btn" onclick={handleRefresh} title="Regenerate from pipeline">
				<RefreshCw size={14} />
			</button>
		</div>
	</div>

	<!-- Code area -->
	<div class="code-area">
		{#if $smithIsThinking && !$smithCode}
			<div class="code-generating">
				<Loader size={20} class="smith-spinner" />
				<span>Smith is generating code...</span>
			</div>
		{:else if $smithCode}
			<pre class="code-display"><code>{$smithCode}</code></pre>
		{:else}
			<pre class="code-display"><code>{'// Generate code from your pipeline...\n// Click Refresh or ask Smith to generate.'}</code></pre>
		{/if}
	</div>

	<!-- Chat area -->
	<div class="chat-area">
		<div class="messages" bind:this={messagesContainer}>
			{#each $smithMessages as msg}
				<ChatMessage
					role={msg.role}
					content={msg.content}
					agentName="Smith"
					accentColor="#22c55e"
				/>
				{#if msg.toolCalls}
					{#each msg.toolCalls as tc}
						<ToolCallDisplay
							toolName={tc.name}
							args={tc.args}
							result={tc.result}
							accentColor="#22c55e"
						/>
					{/each}
				{/if}
			{/each}
			{#if $smithIsThinking}
				<ThinkingIndicator
					accentColor="#22c55e"
					messages={['Compiling...', 'It is... inevitable.', 'Analyzing the construct...', 'Making it real...']}
				/>
			{/if}
		</div>
		<div class="input-bar">
			<input
				type="text"
				placeholder="Ask Smith..."
				bind:value={chatInput}
				onkeydown={handleKeydown}
			/>
			<button class="send-btn" onclick={handleSend} disabled={!chatInput.trim()}>
				<Send size={14} />
			</button>
		</div>
	</div>
</div>

{#if $pendingCommand}
	{@const cmdId = $pendingCommand.commandId}
	<CommandApprovalModal
		command={$pendingCommand.command}
		level={$pendingCommand.level}
		onApprove={() => approveCommand(cmdId, true)}
		onDeny={() => approveCommand(cmdId, false)}
	/>
{/if}

<style>
	.smith-container {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: linear-gradient(180deg, rgba(34, 197, 94, 0.01) 0%, var(--color-bg-primary) 100%);
	}

	.smith-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 12px;
		border-bottom: 1px solid var(--color-border);
		background: var(--color-bg-secondary);
		flex-shrink: 0;
	}

	.smith-label {
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: #22c55e;
	}

	.toolbar-actions {
		display: flex;
		gap: 4px;
	}

	.toolbar-btn {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px 8px;
		border: 1px solid var(--color-border);
		border-radius: 6px;
		background: var(--color-bg-elevated);
		color: var(--color-text-secondary);
		cursor: pointer;
		font-size: 0.75rem;
		transition: all 0.15s;
	}
	.toolbar-btn:hover {
		color: var(--color-text-primary);
		border-color: var(--color-accent);
	}

	.copied-text {
		color: #22c55e;
		font-size: 0.7rem;
	}

	.code-area {
		flex: 3;
		overflow: auto;
		border-bottom: 1px solid var(--color-border);
		min-height: 0;
	}

	.code-display {
		margin: 0;
		padding: 12px 16px;
		font-size: 0.8rem;
		line-height: 1.6;
		color: var(--color-text-primary);
		background: var(--color-code-bg);
		white-space: pre-wrap;
		word-break: break-word;
		min-height: 100%;
	}

	.code-display code {
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
	}

	.code-generating {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		height: 100%;
		color: var(--color-text-muted);
		font-size: 0.85rem;
	}

	:global(.smith-spinner) {
		animation: smith-spin 1s linear infinite;
	}

	@keyframes smith-spin {
		to {
			transform: rotate(360deg);
		}
	}

	.chat-area {
		flex: 2;
		display: flex;
		flex-direction: column;
		min-height: 0;
	}

	.messages {
		flex: 1;
		overflow-y: auto;
		padding: 12px;
		min-height: 0;
	}

	.input-bar {
		display: flex;
		gap: 8px;
		padding: 8px 12px;
		border-top: 1px solid var(--color-border);
		background: var(--color-bg-secondary);
		flex-shrink: 0;
	}

	.input-bar input {
		flex: 1;
		padding: 8px 12px;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-bg-elevated);
		color: var(--color-text-primary);
		font-size: 0.85rem;
		outline: none;
	}
	.input-bar input:focus {
		border-color: #22c55e;
	}
	.input-bar input::placeholder {
		color: var(--color-text-muted);
	}

	.send-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		border: none;
		border-radius: 8px;
		background: #22c55e;
		color: #fff;
		cursor: pointer;
		transition: background 0.15s;
	}
	.send-btn:hover { background: #16a34a; }
	.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
