<script lang="ts">
	import {
		Eye,
		Scan,
		Info,
		AlertTriangle,
		Lightbulb,
		AlertCircle,
		Check,
		X,
		Loader,
		MessageCircle,
		SendHorizonal,
		Sparkles,
		Trash2,
	} from 'lucide-svelte';
	import { marked } from 'marked';
	import {
		oracleInsights,
		oracleConnected,
		oracleAnalyzing,
		oracleChatMessages,
		oracleChatStreaming,
		requestAnalysis,
		approveInsight,
		skipInsight,
		sendOracleChat,
		clearOracleChat,
	} from '$lib/stores/oracle';
	import { currentProject } from '$lib/stores/project';
	import type { OracleInsight } from '$lib/stores/oracle';
	import ThinkingIndicator from '$lib/components/shared/ThinkingIndicator.svelte';
	import ChatMessage from '$lib/components/shared/ChatMessage.svelte';

	type OracleTab = 'insights' | 'chat';
	let activeTab = $state<OracleTab>('insights');

	const severityConfig: Record<string, { icon: typeof Info; color: string; label: string }> = {
		info: { icon: Info, color: '#3b82f6', label: 'Info' },
		warning: { icon: AlertTriangle, color: '#f59e0b', label: 'Warning' },
		suggestion: { icon: Lightbulb, color: '#8b5cf6', label: 'Suggestion' },
		critical: { icon: AlertCircle, color: '#ef4444', label: 'Critical' },
	};

	function getSeverity(s: string) {
		return severityConfig[s] ?? severityConfig.info;
	}

	function formatTime(ts: string): string {
		if (!ts) return '';
		try {
			const d = new Date(ts);
			return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
		} catch {
			return '';
		}
	}

	let expandedId = $state<string | null>(null);

	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
	}

	async function handleApprove(insight: OracleInsight) {
		const project = $currentProject;
		if (!project) return;
		const instruction = await approveInsight(project.name, insight.id);
		if (instruction) {
			window.dispatchEvent(
				new CustomEvent('oracle-approved', { detail: { instruction } })
			);
		}
	}

	async function handleSkip(insight: OracleInsight) {
		const project = $currentProject;
		if (!project) return;
		await skipInsight(project.name, insight.id);
	}

	let pendingCount = $derived($oracleInsights.filter((i) => i.status === 'pending').length);

	// Chat state
	let chatInput = $state('');
	let chatContainer: HTMLDivElement | undefined = $state(undefined);

	function handleSendChat() {
		const text = chatInput.trim();
		if (!text || $oracleChatStreaming) return;
		sendOracleChat(text);
		chatInput = '';
		scrollChatToBottom();
	}

	function handleChatKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			handleSendChat();
		}
	}

	function scrollChatToBottom() {
		requestAnimationFrame(() => {
			if (chatContainer) {
				chatContainer.scrollTop = chatContainer.scrollHeight;
			}
		});
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

	// Auto-scroll when new messages arrive
	$effect(() => {
		if ($oracleChatMessages.length > 0) {
			scrollChatToBottom();
		}
	});
</script>

<div class="oracle-panel">
	<div class="oracle-header">
		<div class="oracle-tabs">
			<button
				class="oracle-tab"
				class:active={activeTab === 'insights'}
				onclick={() => (activeTab = 'insights')}
			>
				<Eye size={12} />
				<span>Insights</span>
				{#if pendingCount > 0}
					<span class="tab-badge">{pendingCount}</span>
				{/if}
			</button>
			<button
				class="oracle-tab"
				class:active={activeTab === 'chat'}
				onclick={() => (activeTab = 'chat')}
			>
				<MessageCircle size={12} />
				<span>Chat</span>
			</button>
		</div>

		{#if activeTab === 'insights'}
			<button
				class="oracle-analyze-btn"
				onclick={requestAnalysis}
				disabled={!$oracleConnected || $oracleAnalyzing}
			>
				{#if $oracleAnalyzing}
					<Loader size={12} class="oracle-spinner" />
					<span>Analyzing...</span>
				{:else}
					<Scan size={12} />
					<span>Analyze</span>
				{/if}
			</button>
		{:else}
			<button
				class="oracle-clear-btn"
				onclick={clearOracleChat}
				title="Clear conversation"
			>
				<Trash2 size={12} />
			</button>
		{/if}
	</div>

	{#if activeTab === 'insights'}
		<div class="oracle-content">
			{#if $oracleInsights.length === 0}
				<div class="oracle-empty">
					<Eye size={24} />
					<p>No insights yet</p>
					<p class="oracle-empty-hint">
						Click "Analyze" to review your pipeline, or insights will appear
						automatically as you build.
					</p>
				</div>
			{:else}
				{#each $oracleInsights as insight (insight.id)}
					{@const sev = getSeverity(insight.severity)}
					{@const SevIcon = sev.icon}
					<div
						class="insight-card"
						class:approved={insight.status === 'approved'}
						class:skipped={insight.status === 'skipped'}
					>
						<div
							class="insight-header"
							role="button"
							tabindex="0"
							onclick={() => toggleExpand(insight.id)}
							onkeydown={(e) => e.key === 'Enter' && toggleExpand(insight.id)}
						>
							<span class="insight-severity" style:color={sev.color}>
								<SevIcon size={13} />
							</span>
							<span class="insight-title">{insight.title}</span>
							<span class="insight-time">{formatTime(insight.timestamp)}</span>
						</div>

						{#if expandedId === insight.id}
							<div class="insight-body">
								<p class="insight-desc">{insight.description}</p>
							</div>
						{/if}

						{#if insight.status === 'pending'}
							<div class="insight-actions">
								<button
									class="insight-btn approve"
									onclick={() => handleApprove(insight)}
									title="Approve and send to Architect"
								>
									<Check size={11} />
									<span>Approve</span>
								</button>
								<button
									class="insight-btn skip"
									onclick={() => handleSkip(insight)}
									title="Skip this insight"
								>
									<X size={11} />
									<span>Skip</span>
								</button>
							</div>
						{:else if insight.status === 'approved'}
							<div class="insight-status-badge approved-badge">Sent to Architect</div>
						{:else}
							<div class="insight-status-badge skipped-badge">Skipped</div>
						{/if}
					</div>
				{/each}
			{/if}
		</div>
	{:else}
		<!-- Chat tab -->
		<div class="oracle-chat" bind:this={chatContainer}>
			{#if $oracleChatMessages.length === 0}
				<div class="chat-welcome">
					<Sparkles size={20} />
					<p class="chat-welcome-title">Talk to The Oracle</p>
					<p class="chat-welcome-hint">
						Ask about your pipeline, get advice on architecture decisions, or
						discuss optimization strategies.
					</p>
				</div>
			{:else}
				{#each $oracleChatMessages as msg (msg.id)}
					{#if msg.role === 'oracle' && msg.streaming && !msg.content}
						<ThinkingIndicator
							accentColor="#8b5cf6"
							messages={[
								'Observing patterns...',
								'Reading the tea leaves...',
								'The cookies say...',
								'Seeing what others cannot...',
								'Contemplating the construct...'
							]}
						/>
					{:else}
						<ChatMessage
							role={msg.role === 'oracle' ? 'assistant' : 'user'}
							content={renderMarkdown(msg.content)}
							agentName="Oracle"
							accentColor="#8b5cf6"
							timestamp={formatTime(msg.timestamp)}
						/>
					{/if}
				{/each}
			{/if}
		</div>
		<div class="chat-input-area">
			<textarea
				class="chat-input"
				placeholder="Ask The Oracle..."
				bind:value={chatInput}
				onkeydown={handleChatKeydown}
				disabled={!$oracleConnected || $oracleChatStreaming}
				rows="1"
			></textarea>
			<button
				class="chat-send-btn"
				onclick={handleSendChat}
				disabled={!chatInput.trim() || !$oracleConnected || $oracleChatStreaming}
			>
				<SendHorizonal size={14} />
			</button>
		</div>
	{/if}
</div>

<style>
	.oracle-panel {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	.oracle-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 10px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
		gap: 8px;
	}

	.oracle-tabs {
		display: flex;
		gap: 2px;
		background: rgba(255, 255, 255, 0.03);
		border-radius: 6px;
		padding: 2px;
	}

	.oracle-tab {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 4px 10px;
		border: none;
		border-radius: 4px;
		background: transparent;
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.oracle-tab:hover {
		color: var(--color-text-primary, #e8e8ed);
	}

	.oracle-tab.active {
		background: rgba(255, 255, 255, 0.08);
		color: var(--color-text-primary, #e8e8ed);
	}

	.tab-badge {
		min-width: 16px;
		height: 16px;
		padding: 0 4px;
		border-radius: 8px;
		background: var(--color-accent, #ff6b35);
		color: white;
		font-size: 9px;
		font-weight: 700;
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}

	.oracle-analyze-btn {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 4px 10px;
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
		background: rgba(255, 255, 255, 0.03);
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s, color 0.15s, border-color 0.15s;
	}

	.oracle-analyze-btn:hover:not(:disabled) {
		background: rgba(255, 255, 255, 0.06);
		color: var(--color-text-primary, #e8e8ed);
		border-color: var(--color-accent, #ff6b35);
	}

	.oracle-analyze-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.oracle-clear-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
		background: transparent;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.oracle-clear-btn:hover {
		background: rgba(239, 68, 68, 0.1);
		color: #ef4444;
	}

	:global(.oracle-spinner) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.oracle-content {
		flex: 1;
		overflow-y: auto;
		padding: 8px;
	}

	.oracle-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--color-text-secondary, #8888a0);
		gap: 8px;
		opacity: 0.5;
		text-align: center;
		padding: 20px;
	}

	.oracle-empty p {
		font-size: 12px;
		margin: 0;
	}
	.oracle-empty-hint {
		font-size: 11px;
		max-width: 280px;
		line-height: 1.5;
	}

	.insight-card {
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 8px;
		margin-bottom: 6px;
		overflow: hidden;
		transition: opacity 0.2s;
	}

	.insight-card.skipped {
		opacity: 0.5;
	}

	.insight-header {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 10px;
		cursor: pointer;
		transition: background 0.15s;
	}

	.insight-header:hover {
		background: rgba(255, 255, 255, 0.03);
	}

	.insight-severity {
		display: flex;
		align-items: center;
		flex-shrink: 0;
	}

	.insight-title {
		flex: 1;
		font-size: 11px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.insight-card.skipped .insight-title {
		text-decoration: line-through;
	}

	.insight-time {
		font-size: 9px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.6;
		flex-shrink: 0;
	}

	.insight-body {
		padding: 0 10px 8px;
	}

	.insight-desc {
		font-size: 11px;
		line-height: 1.5;
		color: var(--color-text-secondary, #8888a0);
		margin: 0;
	}

	.insight-actions {
		display: flex;
		gap: 4px;
		padding: 0 8px 8px;
	}

	.insight-btn {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px 10px;
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 4px;
		background: transparent;
		font-size: 10px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s, border-color 0.15s, color 0.15s;
	}

	.insight-btn.approve {
		color: #22c55e;
		border-color: rgba(34, 197, 94, 0.3);
	}

	.insight-btn.approve:hover {
		background: rgba(34, 197, 94, 0.1);
		border-color: rgba(34, 197, 94, 0.5);
	}

	.insight-btn.skip {
		color: var(--color-text-secondary, #8888a0);
	}

	.insight-btn.skip:hover {
		background: rgba(255, 255, 255, 0.05);
	}

	.insight-status-badge {
		font-size: 9px;
		font-weight: 600;
		padding: 3px 10px 6px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.approved-badge {
		color: #22c55e;
	}
	.skipped-badge {
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.5;
	}

	/* Chat tab styles */
	.oracle-chat {
		flex: 1;
		overflow-y: auto;
		padding: 12px;
		display: flex;
		flex-direction: column;
		gap: 12px;
		background: linear-gradient(
			180deg,
			rgba(139, 92, 246, 0.02) 0%,
			var(--color-bg-primary, #1a1a2e) 100%
		);
	}

	.oracle-chat::-webkit-scrollbar {
		width: 5px;
	}
	.oracle-chat::-webkit-scrollbar-track {
		background: transparent;
	}
	.oracle-chat::-webkit-scrollbar-thumb {
		background: var(--color-border, #2a2a3a);
		border-radius: 3px;
	}

	.chat-welcome {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--color-text-secondary, #8888a0);
		gap: 8px;
		opacity: 0.6;
		text-align: center;
		padding: 20px;
	}

	.chat-welcome-title {
		font-size: 13px;
		font-weight: 600;
		margin: 0;
		color: var(--color-text-primary, #e8e8ed);
	}

	.chat-welcome-hint {
		font-size: 11px;
		max-width: 260px;
		line-height: 1.5;
		margin: 0;
	}

	.chat-input-area {
		display: flex;
		align-items: flex-end;
		gap: 6px;
		padding: 8px 10px;
		border-top: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
	}

	.chat-input {
		flex: 1;
		min-height: 32px;
		max-height: 80px;
		padding: 6px 10px;
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 8px;
		background: rgba(255, 255, 255, 0.03);
		color: var(--color-text-primary, #e8e8ed);
		font-family: var(--font-sans);
		font-size: 12px;
		resize: none;
		outline: none;
		transition: border-color 0.15s;
	}

	.chat-input:focus {
		border-color: rgba(139, 92, 246, 0.5);
	}

	.chat-input::placeholder {
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.5;
	}

	.chat-input:disabled {
		opacity: 0.4;
	}

	.chat-send-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: none;
		border-radius: 8px;
		background: rgba(139, 92, 246, 0.2);
		color: #8b5cf6;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
		flex-shrink: 0;
	}

	.chat-send-btn:hover:not(:disabled) {
		background: rgba(139, 92, 246, 0.35);
		color: #a78bfa;
	}

	.chat-send-btn:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}
</style>
