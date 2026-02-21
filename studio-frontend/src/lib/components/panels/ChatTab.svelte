<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		SendHorizonal,
		Trash2,
		Bot,
		User,
		Wrench,
		Loader,
		ChevronRight,
		CheckCircle2,
		Zap
	} from 'lucide-svelte';
	import { marked } from 'marked';
	import {
		chatMessages,
		chatStreaming,
		addUserMessage,
		addAssistantMessage,
		appendToken,
		completeMessage,
		addToolCall,
		clearChat
	} from '$lib/stores/chat';
	import { settingsData } from '$lib/stores/settings';
	import { nodes, edges, resetNodeCounter } from '$lib/stores/pipeline';
	import type { Node, Edge } from '@xyflow/svelte';

	const assistantName = $derived($settingsData?.user_profile?.assistant_name || 'The Architect');

	// Tool call display helpers
	let expandedToolGroups: Record<string, boolean> = $state({});

	function toggleToolGroup(msgId: string): void {
		expandedToolGroups[msgId] = !expandedToolGroups[msgId];
	}

	function toolCallSummary(toolCalls: { tool: string }[]): string {
		const counts: Record<string, number> = {};
		for (const tc of toolCalls) {
			counts[tc.tool] = (counts[tc.tool] || 0) + 1;
		}
		return Object.entries(counts)
			.map(([name, count]) => (count > 1 ? `${name} x${count}` : name))
			.join(', ');
	}

	function formatToolArgs(args: Record<string, unknown>): string {
		if (!args || Object.keys(args).length === 0) return '';
		return Object.entries(args)
			.map(([k, v]) => {
				const val = typeof v === 'string' ? v : JSON.stringify(v);
				// Truncate long values for display
				const display = val.length > 80 ? val.slice(0, 77) + '...' : val;
				return `${k}: ${display}`;
			})
			.join('\n');
	}

	function toolIcon(toolName: string): string {
		const icons: Record<string, string> = {
			add_node: '+',
			connect_nodes: '~',
			configure_node: '*',
			remove_node: '-',
			list_nodes: '#',
			list_edges: '#',
			list_registered_tools: '?',
			list_registered_agents: '?',
			list_reasoning_patterns: '?'
		};
		return icons[toolName] || '>';
	}

	function sanitizeHtml(html: string): string {
		return html
			.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
			.replace(/\bon\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '');
	}

	function renderMarkdown(content: string): string {
		if (!content) return '';
		const raw = marked(content, { async: false }) as string;
		return sanitizeHtml(raw);
	}

	let inputText = $state('');
	let messagesContainer: HTMLDivElement | undefined = $state(undefined);
	let inputElement: HTMLTextAreaElement | undefined = $state(undefined);
	let ws: WebSocket | null = $state(null);
	let currentAssistantMsgId = $state('');
	let connectionError = $state('');
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let reconnectAttempts = $state(0);
	let gotServerError = false;
	const MAX_RECONNECT_ATTEMPTS = 5;

	function applyCanvasSync(canvas: { nodes: any[]; edges: any[] }): void {
		// Merge assistant-created nodes into the existing canvas.
		// Update existing nodes with new config, add new ones.
		nodes.update((current) => {
			const existingMap = new Map<string, Node>();
			for (const n of current) existingMap.set(n.id, n);

			// Update existing nodes with new config from assistant
			for (const n of canvas.nodes) {
				const existing = existingMap.get(n.id);
				if (existing) {
					existing.data = { ...existing.data, label: n.label || existing.data.label, ...n.config };
					if (n.position) existing.position = n.position;
				}
			}

			// Add new nodes that don't exist yet
			const newNodes: Node[] = canvas.nodes
				.filter((n: any) => !existingMap.has(n.id))
				.map((n: any) => ({
					id: n.id,
					type: n.type,
					position: n.position ?? { x: 250, y: 200 },
					data: { label: n.label || n.id, ...n.config }
				}));

			return [...current, ...newNodes];
		});

		// Sync edges: add new, keep existing
		edges.update((current) => {
			const existingEdgeIds = new Set<string>();
			for (const e of current) existingEdgeIds.add(e.id);
			const newEdges: Edge[] = canvas.edges
				.filter((e: any) => !existingEdgeIds.has(e.id))
				.map((e: any) => ({
					id: e.id,
					source: e.source,
					target: e.target,
					sourceHandle: e.source_handle ?? undefined,
					targetHandle: e.target_handle ?? undefined
				}));
			return [...current, ...newEdges];
		});

		// Handle canvas clear: if assistant cleared canvas, remove nodes not in sync
		if (canvas.nodes.length === 0) {
			nodes.set([]);
			edges.set([]);
		}

		// Update node counter so manual adds don't collide
		resetNodeCounter();
	}

	function getWsUrl(): string {
		const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
		return `${protocol}//${window.location.host}/ws/assistant`;
	}

	function connectWs(): void {
		if (ws && ws.readyState === WebSocket.OPEN) return;

		connectionError = '';
		gotServerError = false;
		let socket: WebSocket;
		try {
			socket = new WebSocket(getWsUrl());
		} catch {
			connectionError = 'AI Assistant requires a configured LLM provider. Check Settings.';
			return;
		}

		socket.onopen = () => {
			connectionError = '';
			reconnectAttempts = 0;
		};

		socket.onmessage = (event) => {
			let data: Record<string, unknown>;
			try {
				data = JSON.parse(event.data);
			} catch {
				console.warn('[ChatTab] Unparseable WebSocket message:', event.data);
				return;
			}

			if (data.type === 'token') {
				if (!currentAssistantMsgId) {
					currentAssistantMsgId = addAssistantMessage();
				}
				appendToken(currentAssistantMsgId, data.content as string);
				scrollToBottom();
			} else if (data.type === 'response_complete') {
				if (currentAssistantMsgId) {
					completeMessage(currentAssistantMsgId, data.full_text as string);
				}
				currentAssistantMsgId = '';
				scrollToBottom();
			} else if (data.type === 'tool_call') {
				if (!currentAssistantMsgId) {
					currentAssistantMsgId = addAssistantMessage();
				}
				// Normalize args: PydanticAI may send a JSON string instead of object
				let args = data.args as Record<string, unknown>;
				if (typeof args === 'string') {
					try {
						args = JSON.parse(args);
					} catch {
						args = { raw: args };
					}
				}
				if (!args || typeof args !== 'object' || Array.isArray(args)) {
					args = {};
				}
				addToolCall(currentAssistantMsgId, {
					tool: data.tool,
					args,
					result: data.result
				});
				scrollToBottom();
			} else if (data.type === 'canvas_sync') {
				// Assistant modified the canvas — apply the new state
				const canvas = data.canvas as { nodes: any[]; edges: any[] };
				if (canvas) {
					applyCanvasSync(canvas);
				}
			} else if (data.type === 'error') {
				connectionError = data.message as string;
				// Mark as a server-sent error so onclose doesn't overwrite it
				gotServerError = true;
				if (currentAssistantMsgId) {
					completeMessage(currentAssistantMsgId, '');
				} else {
					chatStreaming.set(false);
				}
				currentAssistantMsgId = '';
			}
		};

		socket.onclose = () => {
			if (currentAssistantMsgId) {
				completeMessage(currentAssistantMsgId, '[Connection lost]');
				currentAssistantMsgId = '';
			} else {
				chatStreaming.set(false);
			}
			ws = null;

			// If the server sent an explicit error (e.g. missing API key),
			// don't overwrite it with a generic reconnect message — and
			// don't enter the reconnect loop since it will just fail again.
			if (gotServerError) {
				gotServerError = false;
				reconnectAttempts = MAX_RECONNECT_ATTEMPTS;
				return;
			}

			reconnectAttempts++;
			if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
				connectionError = `Connecting to assistant... (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`;
				reconnectTimer = setTimeout(connectWs, 3000);
			} else {
				connectionError = 'Could not connect to AI Assistant. Ensure an LLM API key is configured in Settings.';
			}
		};

		socket.onerror = () => {
			// onclose will handle reconnection
		};

		ws = socket;
	}

	function retryConnection(): void {
		reconnectAttempts = 0;
		connectWs();
	}

	function disconnectWs(): void {
		if (reconnectTimer) {
			clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}
		ws?.close();
		ws = null;
	}

	function sendMessage(): void {
		const text = inputText.trim();
		if (!text || $chatStreaming || !ws) return;

		addUserMessage(text);
		currentAssistantMsgId = addAssistantMessage();
		inputText = '';

		try {
			ws.send(JSON.stringify({ action: 'chat', message: text }));
		} catch {
			connectionError = 'Failed to send message. Connection may be lost.';
			chatStreaming.set(false);
			currentAssistantMsgId = '';
			return;
		}
		scrollToBottom();
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			sendMessage();
		}
	}

	function handleClear(): void {
		clearChat();
		if (ws && ws.readyState === WebSocket.OPEN) {
			try {
				ws.send(JSON.stringify({ action: 'clear_history' }));
			} catch {
				// Ignore — clearing local chat is the main action
			}
		}
		connectionError = '';
	}

	function scrollToBottom(): void {
		requestAnimationFrame(() => {
			if (messagesContainer) {
				messagesContainer.scrollTop = messagesContainer.scrollHeight;
			}
		});
	}

	function formatTime(isoString: string): string {
		const d = new Date(isoString);
		return d.toLocaleTimeString('en-US', {
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	onMount(() => {
		connectWs();
		inputElement?.focus();
	});

	onDestroy(() => {
		disconnectWs();
	});
</script>

<div class="chat-tab">
	<!-- Messages area -->
	<div class="messages" bind:this={messagesContainer}>
		{#if $chatMessages.length === 0}
			<div class="empty-state">
				<div class="empty-icon-circle">
					<Bot size={48} />
				</div>
				<span class="empty-title">{assistantName}</span>
				<span class="empty-hint"
					>{assistantName === 'The Architect'
						? 'I am The Architect. I designed the canvas upon which your agent pipelines take form. Describe what you wish to construct, and I shall design it.'
						: `Ask ${assistantName} to help build your agent pipeline. Add nodes, connect them, configure settings, and more.`}</span
				>
			</div>
		{:else}
			{#each $chatMessages as message (message.id)}
				<div
					class="message"
					class:user={message.role === 'user'}
					class:assistant={message.role === 'assistant'}
				>
					<div class="message-avatar">
						{#if message.role === 'user'}
							<User size={18} />
						{:else}
							<Bot size={18} />
						{/if}
					</div>
					<div class="message-body">
						<div class="message-header">
							<span class="message-role"
								>{message.role === 'user' ? 'You' : assistantName}</span
							>
							<span class="message-time">{formatTime(message.timestamp)}</span>
						</div>
						<div class="message-content" class:markdown={message.role === 'assistant'}>
							{#if message.role === 'assistant'}
								{#if message.streaming && !message.content}
									<div class="thinking-indicator">
										<span class="thinking-dot"></span>
										<span class="thinking-dot"></span>
										<span class="thinking-dot"></span>
										<span class="thinking-label">Thinking...</span>
									</div>
								{:else}
									{@html renderMarkdown(message.content)}
									{#if message.streaming}
										<span class="streaming-cursor"></span>
									{/if}
								{/if}
							{:else}
								{message.content}
							{/if}
						</div>
						{#if message.toolCalls && message.toolCalls.length > 0}
							<div class="tool-calls-container">
								<!-- svelte-ignore a11y_click_events_have_key_events -->
								<!-- svelte-ignore a11y_no_static_element_interactions -->
								<div
									class="tool-calls-header"
									onclick={() => toggleToolGroup(message.id)}
								>
									<div class="tool-calls-header-left">
										<div
											class="tool-chevron"
											class:expanded={expandedToolGroups[message.id]}
										>
											<ChevronRight size={12} />
										</div>
										<Zap size={12} />
										<span class="tool-calls-count"
											>{message.toolCalls.length} tool
											call{message.toolCalls.length !== 1
												? 's'
												: ''}</span
										>
									</div>
									<span class="tool-calls-summary"
										>{toolCallSummary(message.toolCalls)}</span
									>
								</div>
								{#if expandedToolGroups[message.id]}
									<div class="tool-calls-body">
										{#each message.toolCalls as tc, i}
											<div class="tool-call-item">
												<div class="tool-call-row">
													<span class="tool-call-index">{i + 1}</span>
													<span class="tool-call-name">{tc.tool}</span>
													{#if tc.result}
														<CheckCircle2
															size={11}
															class="tool-call-ok"
														/>
													{/if}
												</div>
												{#if tc.args && Object.keys(tc.args).length > 0}
													<div class="tool-call-args">
														{#each Object.entries(tc.args) as [key, val]}
															<div class="tool-arg-line">
																<span class="tool-arg-key"
																	>{key}:</span
																>
																<span class="tool-arg-val"
																	>{typeof val === 'string'
																		? val.length > 120
																			? val.slice(0, 117) +
																				'...'
																			: val
																		: JSON.stringify(
																				val
																			)}</span
																>
															</div>
														{/each}
													</div>
												{/if}
												{#if tc.result}
													<div class="tool-call-result">
														<span class="tool-result-label"
															>result</span
														>
														<span class="tool-result-val"
															>{tc.result.length > 200
																? tc.result.slice(0, 197) + '...'
																: tc.result}</span
														>
													</div>
												{/if}
											</div>
										{/each}
									</div>
								{/if}
							</div>
						{/if}
					</div>
				</div>
			{/each}
		{/if}
	</div>

	<!-- Error banner -->
	{#if connectionError}
		<div class="error-bar">
			<span>{connectionError}</span>
			{#if reconnectAttempts >= MAX_RECONNECT_ATTEMPTS}
				<button class="retry-btn" onclick={retryConnection}>Retry</button>
			{/if}
		</div>
	{/if}

	<!-- Input area -->
	<div class="input-area">
		<textarea
			class="chat-input"
			placeholder="Ask {assistantName}..."
			bind:value={inputText}
			bind:this={inputElement}
			onkeydown={handleKeydown}
			disabled={$chatStreaming}
			rows={1}
		></textarea>
		<div class="input-actions">
			<button
				class="action-btn clear-btn"
				onclick={handleClear}
				title="Clear chat"
				disabled={$chatMessages.length === 0}
			>
				<Trash2 size={14} />
			</button>
			<button
				class="action-btn send-btn"
				onclick={sendMessage}
				disabled={!inputText.trim() || $chatStreaming || !ws}
				title="Send message"
			>
				{#if $chatStreaming}
					<Loader size={14} class="spin-icon" />
				{:else}
					<SendHorizonal size={14} />
				{/if}
			</button>
		</div>
	</div>
</div>

<style>
	.chat-tab {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	.messages {
		flex: 1;
		overflow-y: auto;
		padding: 16px;
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: 10px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.7;
		padding: 24px;
	}

	.empty-icon-circle {
		width: 72px;
		height: 72px;
		border-radius: 50%;
		background: oklch(from var(--color-accent, #ff6b35) l c h / 10%);
		color: var(--color-accent, #ff6b35);
		display: flex;
		align-items: center;
		justify-content: center;
		margin-bottom: 4px;
	}

	.empty-title {
		font-size: 15px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.empty-hint {
		font-size: 12px;
		color: var(--color-text-secondary, #8888a0);
		text-align: center;
		max-width: 320px;
		line-height: 1.5;
	}

	.message {
		display: flex;
		gap: 10px;
		margin-bottom: 16px;
	}

	.message-avatar {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		margin-top: 2px;
	}

	.message.user .message-avatar {
		background: oklch(from var(--color-accent, #ff6b35) l c h / 15%);
		color: var(--color-accent, #ff6b35);
	}

	.message.assistant .message-avatar {
		background: var(--color-overlay-subtle);
		color: var(--color-text-secondary, #8888a0);
	}

	.message-body {
		flex: 1;
		min-width: 0;
	}

	.message-header {
		display: flex;
		align-items: baseline;
		gap: 8px;
		margin-bottom: 4px;
	}

	.message-role {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.message-time {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.6;
	}

	.message-content {
		font-size: 13px;
		line-height: 1.6;
		color: var(--color-text-primary, #e8e8ed);
		white-space: pre-wrap;
		word-break: break-word;
	}

	.message.user .message-content {
		background: oklch(from var(--color-accent, #ff6b35) l c h / 10%);
		border-radius: 8px;
		padding: 8px 12px;
	}

	.message.assistant .message-content {
		background: var(--color-bg-elevated, #1a1a26);
		border-radius: 8px;
		padding: 8px 12px;
	}

	.message-content.markdown {
		white-space: normal;
	}

	.message-content.markdown :global(p) {
		margin: 0 0 8px;
	}

	.message-content.markdown :global(p:last-child) {
		margin-bottom: 0;
	}

	.message-content.markdown :global(h1),
	.message-content.markdown :global(h2),
	.message-content.markdown :global(h3),
	.message-content.markdown :global(h4),
	.message-content.markdown :global(h5),
	.message-content.markdown :global(h6) {
		margin: 12px 0 6px;
		font-weight: 600;
		line-height: 1.3;
	}

	.message-content.markdown :global(h1) {
		font-size: 16px;
	}

	.message-content.markdown :global(h2) {
		font-size: 14px;
	}

	.message-content.markdown :global(h3) {
		font-size: 13px;
	}

	.message-content.markdown :global(code) {
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		font-size: 11px;
		background: var(--color-overlay-subtle);
		padding: 1px 4px;
		border-radius: 3px;
	}

	.message-content.markdown :global(pre) {
		background: var(--color-code-bg, var(--color-bg-primary));
		border-radius: 6px;
		padding: 10px 12px;
		overflow-x: auto;
		margin: 8px 0;
	}

	.message-content.markdown :global(pre code) {
		background: none;
		padding: 0;
		font-size: 11px;
		line-height: 1.5;
	}

	.message-content.markdown :global(ul),
	.message-content.markdown :global(ol) {
		margin: 6px 0;
		padding-left: 20px;
	}

	.message-content.markdown :global(li) {
		margin-bottom: 2px;
	}

	.message-content.markdown :global(blockquote) {
		border-left: 3px solid var(--color-accent, #ff6b35);
		margin: 8px 0;
		padding: 4px 12px;
		color: var(--color-text-secondary, #8888a0);
	}

	.message-content.markdown :global(a) {
		color: var(--color-accent, #ff6b35);
		text-decoration: underline;
	}

	.message-content.markdown :global(hr) {
		border: none;
		border-top: 1px solid var(--color-border, #2a2a3a);
		margin: 10px 0;
	}

	.message-content.markdown :global(table) {
		border-collapse: collapse;
		width: 100%;
		margin: 8px 0;
		font-size: 11px;
	}

	.message-content.markdown :global(th),
	.message-content.markdown :global(td) {
		border: 1px solid var(--color-border, #2a2a3a);
		padding: 4px 8px;
		text-align: left;
	}

	.message-content.markdown :global(th) {
		background: oklch(from var(--color-text-primary) l c h / 4%);
		font-weight: 600;
	}

	.streaming-cursor {
		display: inline-block;
		width: 6px;
		height: 14px;
		background: var(--color-accent, #ff6b35);
		margin-left: 2px;
		animation: blink 0.8s step-end infinite;
		vertical-align: text-bottom;
	}

	@keyframes blink {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0;
		}
	}

	.thinking-indicator {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px 0;
	}

	.thinking-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--color-accent, #ff6b35);
		animation: thinking-pulse 1.4s ease-in-out infinite;
	}

	.thinking-dot:nth-child(2) {
		animation-delay: 0.2s;
	}

	.thinking-dot:nth-child(3) {
		animation-delay: 0.4s;
	}

	.thinking-label {
		font-size: 12px;
		color: var(--color-text-secondary, #8888a0);
		margin-left: 6px;
		font-style: italic;
	}

	@keyframes thinking-pulse {
		0%,
		80%,
		100% {
			opacity: 0.25;
			transform: scale(0.8);
		}
		40% {
			opacity: 1;
			transform: scale(1);
		}
	}

	/* ---- Collapsible tool calls ---- */

	.tool-calls-container {
		margin-top: 8px;
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 8px;
		overflow: hidden;
		background: oklch(from var(--color-bg-primary) l c h / 50%);
	}

	.tool-calls-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 7px 10px;
		cursor: pointer;
		user-select: none;
		transition: background 0.15s ease;
		gap: 8px;
	}

	.tool-calls-header:hover {
		background: oklch(from var(--color-text-primary) l c h / 3%);
	}

	.tool-calls-header-left {
		display: flex;
		align-items: center;
		gap: 6px;
		color: var(--color-accent, #ff6b35);
		flex-shrink: 0;
	}

	.tool-chevron {
		display: flex;
		align-items: center;
		transition: transform 0.2s ease;
	}

	.tool-chevron.expanded {
		transform: rotate(90deg);
	}

	.tool-calls-count {
		font-size: 11px;
		font-weight: 600;
		white-space: nowrap;
	}

	.tool-calls-summary {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		text-align: right;
	}

	.tool-calls-body {
		border-top: 1px solid var(--color-border, #2a2a3a);
		display: flex;
		flex-direction: column;
	}

	.tool-call-item {
		padding: 8px 10px;
		border-bottom: 1px solid oklch(from var(--color-text-primary) l c h / 3%);
	}

	.tool-call-item:last-child {
		border-bottom: none;
	}

	.tool-call-row {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 2px;
	}

	.tool-call-index {
		width: 16px;
		height: 16px;
		border-radius: 50%;
		background: var(--color-overlay-subtle);
		color: var(--color-text-secondary, #8888a0);
		font-size: 9px;
		font-weight: 600;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.tool-call-name {
		font-size: 11px;
		font-weight: 600;
		color: var(--color-accent, #ff6b35);
	}

	:global(.tool-call-ok) {
		color: #4ade80;
		flex-shrink: 0;
	}

	.tool-call-args {
		margin: 4px 0 0 22px;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.tool-arg-line {
		display: flex;
		gap: 6px;
		font-size: 10px;
		line-height: 1.5;
	}

	.tool-arg-key {
		color: var(--color-text-secondary, #8888a0);
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		flex-shrink: 0;
	}

	.tool-arg-val {
		color: var(--color-text-primary, #e8e8ed);
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		word-break: break-word;
	}

	.tool-call-result {
		margin: 4px 0 0 22px;
		padding: 4px 8px;
		background: rgba(74, 222, 128, 0.06);
		border-left: 2px solid rgba(74, 222, 128, 0.3);
		border-radius: 0 4px 4px 0;
		display: flex;
		gap: 6px;
		font-size: 10px;
		line-height: 1.5;
	}

	.tool-result-label {
		color: #4ade80;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		font-weight: 600;
		flex-shrink: 0;
	}

	.tool-result-val {
		color: var(--color-text-secondary, #8888a0);
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		word-break: break-word;
	}

	.error-bar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 12px;
		background: rgba(239, 68, 68, 0.1);
		border-top: 1px solid rgba(239, 68, 68, 0.2);
		font-size: 11px;
		color: var(--color-error, #ef4444);
		flex-shrink: 0;
	}

	.retry-btn {
		margin-left: auto;
		padding: 2px 10px;
		border: 1px solid rgba(239, 68, 68, 0.3);
		border-radius: 4px;
		background: rgba(239, 68, 68, 0.15);
		color: var(--color-error, #ef4444);
		font-size: 11px;
		cursor: pointer;
		white-space: nowrap;
		transition: background 0.15s ease;
	}

	.retry-btn:hover {
		background: rgba(239, 68, 68, 0.25);
	}

	.input-area {
		flex-shrink: 0;
		border-top: 1px solid var(--color-border, #2a2a3a);
		padding: 8px 12px;
		display: flex;
		gap: 8px;
		align-items: flex-end;
	}

	.chat-input {
		flex: 1;
		background: transparent;
		border: none;
		outline: none;
		color: var(--color-text-primary, #e8e8ed);
		font-size: 13px;
		font-family: inherit;
		line-height: 1.5;
		resize: none;
		padding: 4px 0;
	}

	.chat-input::placeholder {
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.5;
	}

	.chat-input:disabled {
		opacity: 0.5;
	}

	.input-actions {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}

	.action-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: none;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition:
			background 0.15s ease,
			color 0.15s ease;
	}

	.action-btn:hover:not(:disabled) {
		background: oklch(from var(--color-text-primary) l c h / 5%);
		color: var(--color-text-primary, #e8e8ed);
	}

	.action-btn:disabled {
		opacity: 0.3;
		cursor: default;
	}

	.send-btn:not(:disabled) {
		color: var(--color-accent, #ff6b35);
	}

	.send-btn:hover:not(:disabled) {
		background: oklch(from var(--color-accent, #ff6b35) l c h / 12%);
	}

	:global(.spin-icon) {
		animation: chat-spin 1s linear infinite;
	}

	@keyframes chat-spin {
		from {
			transform: rotate(0deg);
		}
		to {
			transform: rotate(360deg);
		}
	}
</style>
