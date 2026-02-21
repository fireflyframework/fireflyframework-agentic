<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		Sparkles,
		User,
		SendHorizonal,
		Trash2,
		Scan,
		Loader,
		ChevronRight,
		ChevronDown,
		CheckCircle2,
		Zap,
		Eye,
		AlertTriangle,
		Info,
		Lightbulb,
		AlertCircle,
		Check,
		X,
	} from 'lucide-svelte';
	import { marked } from 'marked';
	import hljs from 'highlight.js/lib/core';
	import javascript from 'highlight.js/lib/languages/javascript';
	import typescript from 'highlight.js/lib/languages/typescript';
	import python from 'highlight.js/lib/languages/python';
	import json from 'highlight.js/lib/languages/json';
	import bash from 'highlight.js/lib/languages/bash';
	import yaml from 'highlight.js/lib/languages/yaml';
	import xml from 'highlight.js/lib/languages/xml';
	import css from 'highlight.js/lib/languages/css';
	import sql from 'highlight.js/lib/languages/sql';
	import markdown from 'highlight.js/lib/languages/markdown';
	import {
		oracleConnected,
		oracleAnalyzing,
		oracleInsights,
		oracleChatMessages,
		oracleChatStreaming,
		requestAnalysis,
		sendOracleChat,
		clearOracleChat,
		approveInsight,
		skipInsight,
	} from '$lib/stores/oracle';
	import { currentProject } from '$lib/stores/project';

	// Register highlight.js languages
	hljs.registerLanguage('javascript', javascript);
	hljs.registerLanguage('js', javascript);
	hljs.registerLanguage('typescript', typescript);
	hljs.registerLanguage('ts', typescript);
	hljs.registerLanguage('python', python);
	hljs.registerLanguage('py', python);
	hljs.registerLanguage('json', json);
	hljs.registerLanguage('bash', bash);
	hljs.registerLanguage('sh', bash);
	hljs.registerLanguage('shell', bash);
	hljs.registerLanguage('yaml', yaml);
	hljs.registerLanguage('yml', yaml);
	hljs.registerLanguage('xml', xml);
	hljs.registerLanguage('html', xml);
	hljs.registerLanguage('css', css);
	hljs.registerLanguage('sql', sql);
	hljs.registerLanguage('markdown', markdown);
	hljs.registerLanguage('md', markdown);

	// Configure marked to use highlight.js for code blocks
	const renderer = new marked.Renderer();
	renderer.code = ({ text, lang }: { text: string; lang?: string }) => {
		const langClass = lang && hljs.getLanguage(lang) ? lang : '';
		let highlighted: string;
		try {
			highlighted = langClass
				? hljs.highlight(text, { language: langClass }).value
				: hljs.highlightAuto(text).value;
		} catch {
			highlighted = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
		}
		const langLabel = lang || 'code';
		return `<div class="code-block-wrapper"><div class="code-block-header"><span class="code-lang">${langLabel}</span><button class="code-copy-btn" onclick="(function(btn){var code=btn.closest('.code-block-wrapper').querySelector('code').textContent;navigator.clipboard.writeText(code);btn.dataset.copied='true';setTimeout(function(){btn.dataset.copied='';},1500);})(this)" title="Copy code">Copy</button></div><pre><code class="hljs${langClass ? ' language-' + langClass : ''}">${highlighted}</code></pre></div>`;
	};
	marked.setOptions({ renderer });

	// Braille spinner animation
	const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
	const THINKING_MESSAGES = [
		'Observing patterns...',
		'Reading the construct...',
		'Seeing what others cannot...',
		'Contemplating the architecture...',
		'Analyzing the threads of causality...',
		'Divining the outcome...',
		'Studying the pipeline flow...',
		'Perceiving the hidden connections...',
	];

	let spinnerFrame = $state(SPINNER_FRAMES[0]);
	let currentThinkingMsg = $state(THINKING_MESSAGES[0]);
	let thinkingInterval: ReturnType<typeof setInterval> | null = null;
	let messageInterval: ReturnType<typeof setInterval> | null = null;
	let spinnerIdx = 0;
	let messageIdx = 0;

	const isThinking = $derived(
		$oracleChatMessages.some((m) => m.role === 'oracle' && m.streaming && !m.content)
	);

	$effect(() => {
		if (isThinking) {
			spinnerIdx = 0;
			messageIdx = Math.floor(Math.random() * THINKING_MESSAGES.length);
			currentThinkingMsg = THINKING_MESSAGES[messageIdx];
			thinkingInterval = setInterval(() => {
				spinnerIdx = (spinnerIdx + 1) % SPINNER_FRAMES.length;
				spinnerFrame = SPINNER_FRAMES[spinnerIdx];
			}, 80);
			messageInterval = setInterval(() => {
				messageIdx = (messageIdx + 1) % THINKING_MESSAGES.length;
				currentThinkingMsg = THINKING_MESSAGES[messageIdx];
			}, 2500);
		} else {
			if (thinkingInterval) {
				clearInterval(thinkingInterval);
				thinkingInterval = null;
			}
			if (messageInterval) {
				clearInterval(messageInterval);
				messageInterval = null;
			}
		}
	});

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

	function formatTime(ts: string): string {
		if (!ts) return '';
		try {
			const d = new Date(ts);
			return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
		} catch {
			return '';
		}
	}

	let chatInput = $state('');
	let messagesContainer: HTMLDivElement | undefined = $state(undefined);

	function scrollToBottom(): void {
		requestAnimationFrame(() => {
			if (messagesContainer) {
				messagesContainer.scrollTop = messagesContainer.scrollHeight;
			}
		});
	}

	function handleSendChat(): void {
		const text = chatInput.trim();
		if (!text || $oracleChatStreaming) return;
		sendOracleChat(text);
		chatInput = '';
		scrollToBottom();
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			handleSendChat();
		}
	}

	// Auto-scroll when messages change
	$effect(() => {
		if ($oracleChatMessages.length > 0) {
			scrollToBottom();
		}
	});

	// Insights section
	let insightsExpanded = $state(true);
	const pendingInsights = $derived($oracleInsights.filter(i => i.status === 'pending'));

	function severityIcon(severity: string) {
		switch (severity) {
			case 'critical': return AlertCircle;
			case 'warning': return AlertTriangle;
			case 'suggestion': return Lightbulb;
			default: return Info;
		}
	}

	function severityColor(severity: string): string {
		switch (severity) {
			case 'critical': return '#ef4444';
			case 'warning': return '#f59e0b';
			case 'suggestion': return '#8b5cf6';
			default: return '#3b82f6';
		}
	}

	async function handleApprove(insightId: string) {
		const proj = $currentProject;
		if (!proj) return;
		const instruction = await approveInsight(proj.name, insightId);
		if (instruction) {
			window.dispatchEvent(new CustomEvent('oracle-approved', { detail: { instruction } }));
		}
	}

	async function handleSkip(insightId: string) {
		const proj = $currentProject;
		if (!proj) return;
		await skipInsight(proj.name, insightId);
	}

	// Auto-trigger analysis after Architect canvas actions
	function handleCanvasComplete() {
		if ($oracleConnected && !$oracleAnalyzing) {
			requestAnalysis();
		}
	}

	onMount(() => {
		window.addEventListener('architect-canvas-complete', handleCanvasComplete);
	});

	onDestroy(() => {
		window.removeEventListener('architect-canvas-complete', handleCanvasComplete);
		if (thinkingInterval) clearInterval(thinkingInterval);
		if (messageInterval) clearInterval(messageInterval);
	});
</script>

<div class="oracle-tab">
	<!-- Messages area -->
	<div class="messages" bind:this={messagesContainer}>
		{#if $oracleChatMessages.length === 0}
			<div class="empty-state">
				<div class="empty-icon-circle">
					<Sparkles size={48} />
				</div>
				<span class="empty-title">The Oracle</span>
				<span class="empty-hint">
					I see what others cannot. Ask about your pipeline architecture,
					patterns, or potential improvements.
				</span>
			</div>
		{:else}
			{#each $oracleChatMessages as msg (msg.id)}
				<div
					class="message"
					class:user={msg.role === 'user'}
					class:assistant={msg.role === 'oracle'}
				>
					<div class="message-avatar">
						{#if msg.role === 'user'}
							<User size={18} />
						{:else}
							<Sparkles size={18} />
						{/if}
					</div>
					<div class="message-body">
						<div class="message-header">
							<span class="message-role">
								{msg.role === 'user' ? 'You' : 'Oracle'}
							</span>
							<span class="message-time">{formatTime(msg.timestamp)}</span>
						</div>
						<div
							class="message-content"
							class:markdown={msg.role === 'oracle'}
						>
							{#if msg.role === 'oracle'}
								{#if msg.streaming && !msg.content}
									<div class="thinking-indicator">
										<span class="thinking-spinner">{spinnerFrame}</span>
										{#key currentThinkingMsg}
											<span class="thinking-message"
												>{currentThinkingMsg}</span
											>
										{/key}
									</div>
								{:else}
									{@html renderMarkdown(msg.content)}
									{#if msg.streaming}
										<span class="streaming-cursor"></span>
									{/if}
								{/if}
							{:else}
								{msg.content}
							{/if}
						</div>
						<!-- Tool calls (ready for future use) -->
						{#if (msg as any).toolCalls && (msg as any).toolCalls.length > 0}
							<div class="tool-calls-container">
								<!-- svelte-ignore a11y_click_events_have_key_events -->
								<!-- svelte-ignore a11y_no_static_element_interactions -->
								<div
									class="tool-calls-header"
									onclick={() => toggleToolGroup(msg.id)}
								>
									<div class="tool-calls-header-left">
										<div
											class="tool-chevron"
											class:expanded={expandedToolGroups[msg.id]}
										>
											<ChevronRight size={12} />
										</div>
										<Zap size={12} />
										<span class="tool-calls-count">
											{(msg as any).toolCalls.length} tool call{(msg as any)
												.toolCalls.length !== 1
												? 's'
												: ''}
										</span>
									</div>
									<span class="tool-calls-summary">
										{toolCallSummary((msg as any).toolCalls)}
									</span>
								</div>
								{#if expandedToolGroups[msg.id]}
									<div class="tool-calls-body">
										{#each (msg as any).toolCalls as tc, i}
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
																<span class="tool-arg-val">
																	{typeof val === 'string'
																		? val.length > 120
																			? val.slice(0, 117) +
																				'...'
																			: val
																		: JSON.stringify(val)}
																</span>
															</div>
														{/each}
													</div>
												{/if}
												{#if tc.result}
													<div class="tool-call-result">
														<span class="tool-result-label">result</span>
														<span class="tool-result-val">
															{tc.result.length > 200
																? tc.result.slice(0, 197) + '...'
																: tc.result}
														</span>
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

	<!-- Inline insights section -->
	{#if pendingInsights.length > 0}
		<div class="insights-section">
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div class="insights-header" onclick={() => insightsExpanded = !insightsExpanded}>
				<div class="insights-header-left">
					<Eye size={12} />
					<span>Insights ({pendingInsights.length})</span>
				</div>
				<div class="insights-chevron" class:expanded={insightsExpanded}>
					<ChevronRight size={12} />
				</div>
			</div>
			{#if insightsExpanded}
				<div class="insights-list">
					{#each pendingInsights as insight (insight.id)}
						{@const SevIcon = severityIcon(insight.severity)}
						<div class="insight-card">
							<div class="insight-top">
								<span class="insight-severity-icon" style:color={severityColor(insight.severity)}>
									<SevIcon size={13} />
								</span>
								<span class="insight-title">{insight.title}</span>
							</div>
							{#if insight.description}
								<p class="insight-desc">{insight.description}</p>
							{/if}
							<div class="insight-actions">
								<button class="insight-approve" onclick={() => handleApprove(insight.id)} title="Approve and forward to Architect">
									<Check size={11} />
									<span>Approve</span>
								</button>
								<button class="insight-skip" onclick={() => handleSkip(insight.id)} title="Skip this insight">
									<X size={11} />
									<span>Skip</span>
								</button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}

	<!-- Error bar when disconnected -->
	{#if !$oracleConnected}
		<div class="error-bar">
			<span>Oracle is not connected. Ensure the backend is running.</span>
		</div>
	{/if}

	<!-- Input area -->
	<div class="input-area">
		<div class="input-row">
			<textarea
				class="chat-input"
				placeholder="Ask The Oracle..."
				bind:value={chatInput}
				onkeydown={handleKeydown}
				disabled={!$oracleConnected || $oracleChatStreaming}
				rows={1}
			></textarea>
			<div class="input-actions">
				<button
					class="action-btn analyze-btn"
					onclick={requestAnalysis}
					disabled={!$oracleConnected || $oracleAnalyzing}
					title="Analyze pipeline"
				>
					{#if $oracleAnalyzing}
						<Loader size={14} class="spin-icon" />
					{:else}
						<Scan size={14} />
					{/if}
				</button>
				<button
					class="action-btn clear-btn"
					onclick={clearOracleChat}
					title="Clear chat"
					disabled={$oracleChatMessages.length === 0}
				>
					<Trash2 size={14} />
				</button>
				<button
					class="action-btn send-btn"
					onclick={handleSendChat}
					disabled={!chatInput.trim() ||
						!$oracleConnected ||
						$oracleChatStreaming}
					title="Send message"
				>
					{#if $oracleChatStreaming}
						<Loader size={14} class="spin-icon" />
					{:else}
						<SendHorizonal size={14} />
					{/if}
				</button>
			</div>
		</div>
	</div>
</div>

<style>
	.oracle-tab {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	/* Messages */
	.messages {
		flex: 1;
		overflow-y: auto;
		padding: 16px;
		background: linear-gradient(
			180deg,
			oklch(from #8b5cf6 l c h / 2%) 0%,
			var(--color-bg-primary, #0a0a0f) 100%
		);
	}

	.messages::-webkit-scrollbar {
		width: 5px;
	}
	.messages::-webkit-scrollbar-track {
		background: transparent;
	}
	.messages::-webkit-scrollbar-thumb {
		background: var(--color-border, #2a2a3a);
		border-radius: 3px;
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
		background: oklch(from #8b5cf6 l c h / 10%);
		color: #8b5cf6;
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

	/* Message layout */
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
		background: oklch(from #8b5cf6 l c h / 15%);
		color: #8b5cf6;
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
		background: oklch(from #8b5cf6 l c h / 10%);
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
	.message-content.markdown :global(h3) {
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
		border-left: 3px solid #8b5cf6;
		margin: 8px 0;
		padding: 4px 12px;
		color: var(--color-text-secondary, #8888a0);
	}

	.message-content.markdown :global(a) {
		color: #8b5cf6;
		text-decoration: underline;
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

	/* Streaming cursor */
	.streaming-cursor {
		display: inline-block;
		width: 6px;
		height: 14px;
		background: #8b5cf6;
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

	/* Thinking indicator */
	.thinking-indicator {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 0;
	}

	.thinking-spinner {
		font-size: 16px;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		color: #8b5cf6;
		flex-shrink: 0;
		line-height: 1;
	}

	.thinking-message {
		font-size: 12px;
		color: var(--color-text-secondary, #8888a0);
		font-style: italic;
		animation: msg-fade 0.4s ease;
	}

	@keyframes msg-fade {
		from {
			opacity: 0;
			transform: translateX(4px);
		}
		to {
			opacity: 1;
			transform: translateX(0);
		}
	}

	/* Tool calls */
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
		color: #8b5cf6;
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
		color: #8b5cf6;
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

	/* Insights section */
	.insights-section {
		flex-shrink: 0;
		border-top: 1px solid var(--color-border, #2a2a3a);
		background: oklch(from #8b5cf6 l c h / 3%);
	}

	.insights-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 12px;
		cursor: pointer;
		user-select: none;
		transition: background 0.15s;
	}

	.insights-header:hover {
		background: oklch(from #8b5cf6 l c h / 6%);
	}

	.insights-header-left {
		display: flex;
		align-items: center;
		gap: 6px;
		color: #8b5cf6;
		font-size: 11px;
		font-weight: 600;
	}

	.insights-chevron {
		display: flex;
		align-items: center;
		color: var(--color-text-secondary);
		transition: transform 0.2s;
	}

	.insights-chevron.expanded {
		transform: rotate(90deg);
	}

	.insights-list {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 0 8px 8px;
		max-height: 200px;
		overflow-y: auto;
	}

	.insight-card {
		padding: 8px 10px;
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 8px;
		background: var(--color-bg-elevated, #1a1a26);
	}

	.insight-top {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 4px;
	}

	.insight-severity-icon {
		display: flex;
		align-items: center;
		flex-shrink: 0;
	}

	.insight-title {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.insight-desc {
		font-size: 11px;
		line-height: 1.4;
		color: var(--color-text-secondary, #8888a0);
		margin: 0 0 6px;
	}

	.insight-actions {
		display: flex;
		gap: 6px;
	}

	.insight-approve {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 3px 8px;
		border: 1px solid oklch(from #8b5cf6 l c h / 30%);
		border-radius: 5px;
		background: transparent;
		color: #8b5cf6;
		font-size: 10px;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.15s;
	}

	.insight-approve:hover {
		background: oklch(from #8b5cf6 l c h / 10%);
		border-color: #8b5cf6;
	}

	.insight-skip {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 3px 8px;
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 5px;
		background: transparent;
		color: var(--color-text-secondary, #8888a0);
		font-size: 10px;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.15s;
	}

	.insight-skip:hover {
		background: oklch(from var(--color-text-primary) l c h / 5%);
	}

	/* Error bar */
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

	/* Input area */
	.input-area {
		flex-shrink: 0;
		border-top: 1px solid var(--color-border, #2a2a3a);
		padding: 8px 12px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.input-row {
		display: flex;
		gap: 4px;
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
		min-height: 24px;
		max-height: 80px;
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

	.analyze-btn:not(:disabled) {
		color: #8b5cf6;
	}

	.analyze-btn:hover:not(:disabled) {
		background: oklch(from #8b5cf6 l c h / 12%);
		color: #a78bfa;
	}

	.send-btn:not(:disabled) {
		color: #8b5cf6;
	}

	.send-btn:hover:not(:disabled) {
		background: oklch(from #8b5cf6 l c h / 12%);
	}

	:global(.spin-icon) {
		animation: oracle-spin 1s linear infinite;
	}

	@keyframes oracle-spin {
		from {
			transform: rotate(0deg);
		}
		to {
			transform: rotate(360deg);
		}
	}

	/* Code block syntax highlighting */
	.message-content.markdown :global(.code-block-wrapper) {
		position: relative;
		margin: 8px 0;
		border-radius: 8px;
		overflow: hidden;
		border: 1px solid var(--color-border, #2a2a3a);
	}

	.message-content.markdown :global(.code-block-header) {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 4px 10px;
		background: oklch(from var(--color-text-primary) l c h / 3%);
		border-bottom: 1px solid var(--color-border, #2a2a3a);
	}

	.message-content.markdown :global(.code-lang) {
		font-size: 10px;
		font-weight: 600;
		color: var(--color-text-secondary, #8888a0);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.message-content.markdown :global(.code-copy-btn) {
		font-size: 10px;
		font-weight: 500;
		color: var(--color-text-secondary, #8888a0);
		background: none;
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 4px;
		padding: 2px 8px;
		cursor: pointer;
		transition:
			color 0.15s,
			border-color 0.15s;
	}

	.message-content.markdown :global(.code-copy-btn:hover) {
		color: var(--color-text-primary, #e8e8ed);
		border-color: var(--color-text-secondary, #8888a0);
	}

	.message-content.markdown :global(.code-copy-btn[data-copied='true']) {
		color: var(--color-success, #22c55e);
		border-color: var(--color-success, #22c55e);
	}

	.message-content.markdown :global(.code-block-wrapper pre) {
		margin: 0;
		border-radius: 0;
		border: none;
	}

	/* highlight.js theme (dark) */
	.message-content.markdown :global(.hljs) {
		color: #abb2bf;
		background: var(--color-code-bg, var(--color-bg-primary));
	}

	.message-content.markdown :global(.hljs-keyword),
	.message-content.markdown :global(.hljs-selector-tag),
	.message-content.markdown :global(.hljs-literal),
	.message-content.markdown :global(.hljs-section),
	.message-content.markdown :global(.hljs-link) {
		color: #c678dd;
	}

	.message-content.markdown :global(.hljs-string),
	.message-content.markdown :global(.hljs-addition) {
		color: #98c379;
	}

	.message-content.markdown :global(.hljs-number),
	.message-content.markdown :global(.hljs-regexp),
	.message-content.markdown :global(.hljs-meta) {
		color: #d19a66;
	}

	.message-content.markdown :global(.hljs-comment),
	.message-content.markdown :global(.hljs-quote) {
		color: #5c6370;
		font-style: italic;
	}

	.message-content.markdown :global(.hljs-title),
	.message-content.markdown :global(.hljs-name) {
		color: #61afef;
	}

	.message-content.markdown :global(.hljs-variable),
	.message-content.markdown :global(.hljs-template-variable) {
		color: #e06c75;
	}

	.message-content.markdown :global(.hljs-built_in),
	.message-content.markdown :global(.hljs-type) {
		color: #e6c07b;
	}

	.message-content.markdown :global(.hljs-attr),
	.message-content.markdown :global(.hljs-attribute) {
		color: #d19a66;
	}

	.message-content.markdown :global(.hljs-deletion) {
		color: #e06c75;
	}

	.message-content.markdown :global(.hljs-params) {
		color: #abb2bf;
	}

	.message-content.markdown :global(.hljs-function) {
		color: #61afef;
	}
</style>
