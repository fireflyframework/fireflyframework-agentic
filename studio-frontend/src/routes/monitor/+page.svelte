<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { Activity, Coins, TrendingUp, Zap, Timer, Users, Cpu, RefreshCw } from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import type { UsageSummary } from '$lib/types/graph';

	let data: UsageSummary | null = $state(null);
	let loading: boolean = $state(true);
	let error: string | null = $state(null);
	let autoRefresh: boolean = $state(false);
	let refreshInterval: ReturnType<typeof setInterval> | null = $state(null);

	function formatNumber(n: number): string {
		return n.toLocaleString('en-US');
	}

	function formatCost(n: number): string {
		return `$${n.toFixed(4)}`;
	}

	function formatLatency(totalMs: number, count: number): string {
		if (count === 0) return '0ms';
		return `${Math.round(totalMs / count)}ms`;
	}

	async function fetchUsage() {
		try {
			loading = data === null;
			error = null;
			data = await api.monitoring.usage();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to fetch usage data';
		} finally {
			loading = false;
		}
	}

	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			refreshInterval = setInterval(fetchUsage, 30000);
		} else if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	onMount(() => {
		fetchUsage();
	});

	onDestroy(() => {
		if (refreshInterval) {
			clearInterval(refreshInterval);
		}
	});

	let avgLatency = $derived(
		data ? formatLatency(data.total_latency_ms, data.record_count) : '0ms'
	);

	let agentEntries = $derived(data ? Object.entries(data.by_agent) : []);
	let modelEntries = $derived(data ? Object.entries(data.by_model) : []);
</script>

<div class="monitor-page">
	<!-- Header -->
	<div class="monitor-header">
		<div class="header-left">
			<Activity size={20} class="text-accent" />
			<h1 class="header-title">Monitoring</h1>
		</div>
		<div class="header-actions">
			<label class="auto-refresh-toggle">
				<input
					type="checkbox"
					checked={autoRefresh}
					onchange={toggleAutoRefresh}
				/>
				<span class="toggle-label">Auto-refresh (30s)</span>
			</label>
			<button class="refresh-btn" onclick={fetchUsage} disabled={loading}>
				<RefreshCw size={14} class={loading ? 'spin' : ''} />
				Refresh
			</button>
		</div>
	</div>

	<!-- Loading State -->
	{#if loading && !data}
		<div class="cards-grid">
			{#each Array(4) as _}
				<div class="metric-card skeleton">
					<div class="skeleton-icon"></div>
					<div class="skeleton-text-sm"></div>
					<div class="skeleton-text-lg"></div>
				</div>
			{/each}
		</div>
		<div class="table-section skeleton-table">
			<div class="skeleton-text-lg" style="width: 200px; margin-bottom: 16px;"></div>
			{#each Array(3) as _}
				<div class="skeleton-row"></div>
			{/each}
		</div>
	<!-- Error State -->
	{:else if error}
		<div class="error-banner">
			<p class="error-text">Failed to load monitoring data: {error}</p>
			<button class="refresh-btn" onclick={fetchUsage}>Retry</button>
		</div>
	<!-- Data State -->
	{:else if data}
		<!-- Metric Cards -->
		<div class="cards-grid">
			<div class="metric-card">
				<div class="card-icon icon-info">
					<Coins size={18} />
				</div>
				<span class="card-label">Total Tokens</span>
				<span class="card-value">{formatNumber(data.total_tokens)}</span>
			</div>
			<div class="metric-card">
				<div class="card-icon icon-success">
					<TrendingUp size={18} />
				</div>
				<span class="card-label">Total Cost</span>
				<span class="card-value">{formatCost(data.total_cost_usd)}</span>
			</div>
			<div class="metric-card">
				<div class="card-icon icon-accent">
					<Zap size={18} />
				</div>
				<span class="card-label">Total Requests</span>
				<span class="card-value">{formatNumber(data.total_requests)}</span>
			</div>
			<div class="metric-card">
				<div class="card-icon icon-warning">
					<Timer size={18} />
				</div>
				<span class="card-label">Avg Latency</span>
				<span class="card-value">{avgLatency}</span>
			</div>
		</div>

		<!-- Per-Agent Table -->
		<div class="table-section">
			<div class="table-header">
				<Users size={16} class="text-text-secondary" />
				<h2 class="table-title">Usage by Agent</h2>
			</div>
			{#if agentEntries.length === 0}
				<div class="empty-state">No agent data yet</div>
			{:else}
				<div class="table-wrapper">
					<table>
						<thead>
							<tr>
								<th>Agent</th>
								<th class="num">Input Tokens</th>
								<th class="num">Output Tokens</th>
								<th class="num">Total Tokens</th>
								<th class="num">Cost</th>
								<th class="num">Requests</th>
							</tr>
						</thead>
						<tbody>
							{#each agentEntries as [name, stats]}
								<tr>
									<td class="name-cell">{name}</td>
									<td class="num">{formatNumber(stats.input_tokens)}</td>
									<td class="num">{formatNumber(stats.output_tokens)}</td>
									<td class="num">{formatNumber(stats.total_tokens)}</td>
									<td class="num">{formatCost(stats.cost_usd)}</td>
									<td class="num">{formatNumber(stats.requests)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>

		<!-- Per-Model Table -->
		<div class="table-section">
			<div class="table-header">
				<Cpu size={16} class="text-text-secondary" />
				<h2 class="table-title">Usage by Model</h2>
			</div>
			{#if modelEntries.length === 0}
				<div class="empty-state">No model data yet</div>
			{:else}
				<div class="table-wrapper">
					<table>
						<thead>
							<tr>
								<th>Model</th>
								<th class="num">Input Tokens</th>
								<th class="num">Output Tokens</th>
								<th class="num">Total Tokens</th>
								<th class="num">Cost</th>
								<th class="num">Requests</th>
							</tr>
						</thead>
						<tbody>
							{#each modelEntries as [name, stats]}
								<tr>
									<td class="name-cell">{name}</td>
									<td class="num">{formatNumber(stats.input_tokens)}</td>
									<td class="num">{formatNumber(stats.output_tokens)}</td>
									<td class="num">{formatNumber(stats.total_tokens)}</td>
									<td class="num">{formatCost(stats.cost_usd)}</td>
									<td class="num">{formatNumber(stats.requests)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.monitor-page {
		display: flex;
		flex-direction: column;
		gap: 24px;
		padding: 24px;
		height: 100%;
		overflow-y: auto;
		background: var(--color-bg-primary);
	}

	/* Header */
	.monitor-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.header-title {
		font-size: 20px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: 16px;
	}

	.auto-refresh-toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		cursor: pointer;
	}

	.auto-refresh-toggle input {
		accent-color: var(--color-accent);
		width: 14px;
		height: 14px;
		cursor: pointer;
	}

	.toggle-label {
		font-size: 12px;
		color: var(--color-text-secondary);
	}

	.refresh-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 14px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		color: var(--color-text-primary);
		font-size: 12px;
		cursor: pointer;
		transition: border-color 0.15s;
	}

	.refresh-btn:hover {
		border-color: var(--color-accent);
	}

	.refresh-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	/* Metric Cards */
	.cards-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 16px;
	}

	@media (max-width: 1024px) {
		.cards-grid {
			grid-template-columns: repeat(2, 1fr);
		}
	}

	@media (max-width: 600px) {
		.cards-grid {
			grid-template-columns: 1fr;
		}
	}

	.metric-card {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 20px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 10px;
	}

	.card-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		border-radius: 8px;
	}

	.icon-info {
		background: oklch(from var(--color-info) l c h / 15%);
		color: var(--color-info);
	}

	.icon-success {
		background: oklch(from var(--color-success) l c h / 15%);
		color: var(--color-success);
	}

	.icon-accent {
		background: oklch(from var(--color-accent) l c h / 15%);
		color: var(--color-accent);
	}

	.icon-warning {
		background: oklch(from var(--color-warning) l c h / 15%);
		color: var(--color-warning);
	}

	.card-label {
		font-size: 11px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary);
	}

	.card-value {
		font-size: 28px;
		font-weight: 700;
		color: var(--color-text-primary);
		font-family: var(--font-mono);
		line-height: 1;
	}

	/* Tables */
	.table-section {
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		padding: 20px;
	}

	.table-header {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 16px;
	}

	.table-title {
		font-size: 14px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	.table-wrapper {
		overflow-x: auto;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}

	th {
		text-align: left;
		padding: 10px 12px;
		font-size: 11px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-secondary);
		border-bottom: 1px solid var(--color-border);
	}

	td {
		padding: 10px 12px;
		color: var(--color-text-primary);
		border-bottom: 1px solid oklch(from var(--color-border) l c h / 50%);
	}

	tbody tr:nth-child(even) {
		background: oklch(from var(--color-bg-secondary) l c h / 50%);
	}

	tbody tr:hover {
		background: oklch(from var(--color-border) l c h / 20%);
	}

	.num {
		text-align: right;
		font-family: var(--font-mono);
		font-size: 12px;
	}

	.name-cell {
		font-weight: 500;
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--color-accent);
	}

	.empty-state {
		text-align: center;
		padding: 32px;
		color: var(--color-text-secondary);
		font-size: 13px;
	}

	/* Error Banner */
	.error-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 20px;
		background: oklch(from var(--color-error) l c h / 10%);
		border: 1px solid oklch(from var(--color-error) l c h / 30%);
		border-radius: 10px;
	}

	.error-text {
		color: var(--color-error);
		font-size: 13px;
		margin: 0;
	}

	/* Skeleton Loading */
	.skeleton {
		animation: pulse 1.5s ease-in-out infinite;
	}

	.skeleton-icon {
		width: 36px;
		height: 36px;
		border-radius: 8px;
		background: var(--color-border);
	}

	.skeleton-text-sm {
		width: 80px;
		height: 12px;
		border-radius: 4px;
		background: var(--color-border);
	}

	.skeleton-text-lg {
		width: 120px;
		height: 28px;
		border-radius: 4px;
		background: var(--color-border);
	}

	.skeleton-table {
		animation: pulse 1.5s ease-in-out infinite;
	}

	.skeleton-row {
		height: 40px;
		border-radius: 4px;
		background: var(--color-border);
		margin-bottom: 8px;
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.5;
		}
	}

	/* Spin animation for refresh icon */
	:global(.spin) {
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		from {
			transform: rotate(0deg);
		}
		to {
			transform: rotate(360deg);
		}
	}
</style>
