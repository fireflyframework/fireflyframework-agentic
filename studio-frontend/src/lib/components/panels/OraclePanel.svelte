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
	} from 'lucide-svelte';
	import {
		oracleInsights,
		oracleConnected,
		oracleAnalyzing,
		requestAnalysis,
		approveInsight,
		skipInsight,
	} from '$lib/stores/oracle';
	import { currentProject } from '$lib/stores/project';
	import type { OracleInsight } from '$lib/stores/oracle';

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
</script>

<div class="oracle-panel">
	<div class="oracle-header">
		<div class="header-left">
			<Eye size={13} />
			<span class="header-title">Insights</span>
		</div>
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
	</div>

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

	.header-left {
		display: flex;
		align-items: center;
		gap: 6px;
		color: var(--color-text-secondary, #8888a0);
	}

	.header-title {
		font-size: 11px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.oracle-analyze-btn {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 4px 10px;
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
		background: oklch(from var(--color-text-primary) l c h / 3%);
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s, color 0.15s, border-color 0.15s;
	}

	.oracle-analyze-btn:hover:not(:disabled) {
		background: var(--color-overlay-subtle);
		color: var(--color-text-primary, #e8e8ed);
		border-color: var(--color-accent, #ff6b35);
	}

	.oracle-analyze-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	:global(.oracle-spinner) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to { transform: rotate(360deg); }
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
		background: oklch(from var(--color-text-primary) l c h / 2%);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 8px;
		margin-bottom: 6px;
		overflow: hidden;
		transition: opacity 0.2s;
	}

	.insight-card.skipped { opacity: 0.5; }

	.insight-header {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 10px;
		cursor: pointer;
		transition: background 0.15s;
	}
	.insight-header:hover { background: oklch(from var(--color-text-primary) l c h / 3%); }

	.insight-severity { display: flex; align-items: center; flex-shrink: 0; }

	.insight-title {
		flex: 1;
		font-size: 11px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.insight-card.skipped .insight-title { text-decoration: line-through; }

	.insight-time {
		font-size: 9px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.6;
		flex-shrink: 0;
	}

	.insight-body { padding: 0 10px 8px; }
	.insight-desc { font-size: 11px; line-height: 1.5; color: var(--color-text-secondary, #8888a0); margin: 0; }

	.insight-actions { display: flex; gap: 4px; padding: 0 8px 8px; }

	.insight-btn {
		display: flex; align-items: center; gap: 4px;
		padding: 4px 10px; border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 4px; background: transparent;
		font-size: 10px; font-weight: 500; cursor: pointer;
		transition: background 0.15s, border-color 0.15s, color 0.15s;
	}
	.insight-btn.approve { color: #22c55e; border-color: rgba(34, 197, 94, 0.3); }
	.insight-btn.approve:hover { background: rgba(34, 197, 94, 0.1); border-color: rgba(34, 197, 94, 0.5); }
	.insight-btn.skip { color: var(--color-text-secondary, #8888a0); }
	.insight-btn.skip:hover { background: oklch(from var(--color-text-primary) l c h / 5%); }

	.insight-status-badge {
		font-size: 9px; font-weight: 600; padding: 3px 10px 6px;
		text-transform: uppercase; letter-spacing: 0.04em;
	}
	.approved-badge { color: #22c55e; }
	.skipped-badge { color: var(--color-text-secondary, #8888a0); opacity: 0.5; }
</style>
