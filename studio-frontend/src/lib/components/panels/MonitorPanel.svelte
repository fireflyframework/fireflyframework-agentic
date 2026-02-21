<script lang="ts">
	import { RefreshCw, Activity, Zap, DollarSign, Clock, Hash } from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { addToast } from '$lib/stores/notifications';
	import type { UsageSummary } from '$lib/types/graph';

	let loading = $state(false);
	let usage: UsageSummary | null = $state(null);

	async function loadUsage() {
		loading = true;
		try {
			usage = await api.monitoring.usage();
		} catch {
			usage = null;
			addToast('Failed to load usage data', 'error');
		} finally {
			loading = false;
		}
	}

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return n.toString();
	}

	function formatCost(n: number): string {
		return `$${n.toFixed(4)}`;
	}

	function formatLatency(ms: number, count: number): string {
		if (count === 0) return '0ms';
		return `${Math.round(ms / count)}ms`;
	}

	$effect(() => {
		loadUsage();
	});
</script>

<div class="panel">
	<div class="header">
		<span class="title">Monitor</span>
		<button class="action-btn" onclick={loadUsage} disabled={loading} title="Refresh">
			<RefreshCw size={13} />
		</button>
	</div>

	<div class="content">
		{#if loading && !usage}
			<div class="empty-state">
				<RefreshCw size={16} />
				<span>Loading usage data...</span>
			</div>
		{:else if !usage}
			<div class="empty-state">
				<Activity size={16} />
				<span>No usage data available. Run a pipeline to see metrics.</span>
			</div>
		{:else}
			<div class="metrics-grid">
				<div class="metric-card">
					<div class="metric-icon"><Hash size={14} /></div>
					<div class="metric-body">
						<span class="metric-value">{formatNumber(usage.total_requests)}</span>
						<span class="metric-label">Total Requests</span>
					</div>
				</div>
				<div class="metric-card">
					<div class="metric-icon"><Zap size={14} /></div>
					<div class="metric-body">
						<span class="metric-value">{formatNumber(usage.total_tokens)}</span>
						<span class="metric-label">Total Tokens</span>
					</div>
				</div>
				<div class="metric-card">
					<div class="metric-icon"><DollarSign size={14} /></div>
					<div class="metric-body">
						<span class="metric-value">{formatCost(usage.total_cost_usd)}</span>
						<span class="metric-label">Total Cost</span>
					</div>
				</div>
				<div class="metric-card">
					<div class="metric-icon"><Clock size={14} /></div>
					<div class="metric-body">
						<span class="metric-value">{formatLatency(usage.total_latency_ms, usage.total_requests)}</span>
						<span class="metric-label">Avg Latency</span>
					</div>
				</div>
			</div>

			<div class="breakdown-section">
				{#if Object.keys(usage.by_model).length > 0}
					<div class="breakdown-group">
						<div class="breakdown-title">By Model</div>
						<div class="breakdown-table">
							<div class="table-header">
								<span class="col-name">Model</span>
								<span class="col-num">Requests</span>
								<span class="col-num">Tokens</span>
								<span class="col-num">Cost</span>
							</div>
							{#each Object.entries(usage.by_model) as [model, data] (model)}
								<div class="table-row">
									<span class="col-name">{model}</span>
									<span class="col-num">{formatNumber(data.requests)}</span>
									<span class="col-num">{formatNumber(data.total_tokens)}</span>
									<span class="col-num">{formatCost(data.cost_usd)}</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				{#if Object.keys(usage.by_agent).length > 0}
					<div class="breakdown-group">
						<div class="breakdown-title">By Agent</div>
						<div class="breakdown-table">
							<div class="table-header">
								<span class="col-name">Agent</span>
								<span class="col-num">Requests</span>
								<span class="col-num">Tokens</span>
								<span class="col-num">Cost</span>
							</div>
							{#each Object.entries(usage.by_agent) as [agent, data] (agent)}
								<div class="table-row">
									<span class="col-name">{agent}</span>
									<span class="col-num">{formatNumber(data.requests)}</span>
									<span class="col-num">{formatNumber(data.total_tokens)}</span>
									<span class="col-num">{formatCost(data.cost_usd)}</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>

<style>
	.panel {
		height: 100%;
		display: flex;
		flex-direction: column;
		background: var(--color-bg-primary, #0a0a12);
		font-family: var(--font-sans, system-ui, -apple-system, sans-serif);
	}

	.header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 12px;
		height: 40px;
		min-height: 40px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
	}

	.title {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.action-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 26px;
		height: 26px;
		border: none;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
	}

	.action-btn:hover:not(:disabled) {
		background: oklch(from var(--color-text-primary) l c h / 5%);
		color: var(--color-text-primary, #e8e8ed);
	}

	.action-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}

	.content {
		flex: 1;
		overflow-y: auto;
		padding: 10px 12px;
	}

	.content::-webkit-scrollbar {
		width: 6px;
	}

	.content::-webkit-scrollbar-track {
		background: transparent;
	}

	.content::-webkit-scrollbar-thumb {
		background: var(--color-border, #2a2a3a);
		border-radius: 3px;
	}

	.empty-state {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		height: 100%;
		color: var(--color-text-secondary, #8888a0);
		font-size: 12px;
		opacity: 0.6;
	}

	.metrics-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 8px;
		margin-bottom: 14px;
	}

	.metric-card {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 10px 12px;
		background: var(--color-bg-secondary, #12121a);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
	}

	.metric-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		border-radius: 6px;
		background: var(--color-bg-elevated, #1a1a2a);
		color: var(--color-accent, #ff6b35);
		flex-shrink: 0;
	}

	.metric-body {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.metric-value {
		font-size: 16px;
		font-weight: 700;
		color: var(--color-text-primary, #e8e8ed);
		line-height: 1.1;
	}

	.metric-label {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	.breakdown-section {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.breakdown-group {
		/* No additional styling needed */
	}

	.breakdown-title {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary, #8888a0);
		margin-bottom: 6px;
	}

	.breakdown-table {
		background: var(--color-bg-secondary, #12121a);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
		overflow: hidden;
	}

	.table-header {
		display: flex;
		padding: 6px 10px;
		background: var(--color-bg-elevated, #1a1a2a);
		border-bottom: 1px solid var(--color-border, #2a2a3a);
	}

	.table-header .col-name,
	.table-header .col-num {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		color: var(--color-text-secondary, #8888a0);
	}

	.table-row {
		display: flex;
		padding: 5px 10px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		transition: background 0.12s ease;
	}

	.table-row:last-child {
		border-bottom: none;
	}

	.table-row:hover {
		background: oklch(from var(--color-text-primary) l c h / 2%);
	}

	.col-name {
		flex: 2;
		font-size: 11px;
		color: var(--color-text-primary, #e8e8ed);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}

	.col-num {
		flex: 1;
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
		text-align: right;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
	}
</style>
