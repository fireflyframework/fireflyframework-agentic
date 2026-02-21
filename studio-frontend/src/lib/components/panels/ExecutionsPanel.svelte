<script lang="ts">
	import { RefreshCw, ListChecks, ChevronRight, ChevronDown } from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { currentProject } from '$lib/stores/project';
	import { addToast } from '$lib/stores/notifications';
	import { bottomPanelTab } from '$lib/stores/ui';

	type Execution = {
		execution_id: string;
		status: string;
		duration_ms: number | null;
	};

	let loading = $state(false);
	let executions = $state<Execution[]>([]);
	let expandedId = $state<string | null>(null);

	let projectName = $derived($currentProject?.name ?? '');
	let activeTab = $derived($bottomPanelTab);

	async function loadExecutions() {
		if (!projectName) return;
		loading = true;
		try {
			const result = await api.runtime.executions(projectName);
			executions = result.executions ?? [];
		} catch {
			executions = [];
			addToast('Failed to load executions', 'error');
		} finally {
			loading = false;
		}
	}

	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
	}

	function formatDuration(ms: number | null): string {
		if (ms === null || ms === undefined) return '--';
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(2)}s`;
	}

	function truncateId(id: string): string {
		if (id.length <= 12) return id;
		return id.slice(0, 8) + '...';
	}

	function statusColor(status: string): string {
		switch (status.toLowerCase()) {
			case 'completed':
			case 'success':
				return 'var(--color-success)';
			case 'running':
			case 'in_progress':
				return '#f59e0b';
			case 'failed':
			case 'error':
				return 'var(--color-error)';
			default:
				return 'var(--color-text-secondary)';
		}
	}

	// Auto-refresh when panel is visible and project changes
	$effect(() => {
		if (activeTab === 'executions' && projectName) {
			loadExecutions();
		}
	});

	// Periodic refresh while visible
	$effect(() => {
		if (activeTab !== 'executions' || !projectName) return;
		const interval = setInterval(loadExecutions, 10000);
		return () => clearInterval(interval);
	});
</script>

<div class="panel">
	<div class="header">
		<span class="title">Executions</span>
		<button class="action-btn" onclick={loadExecutions} disabled={loading} title="Refresh">
			<RefreshCw size={13} />
		</button>
	</div>

	<div class="content">
		{#if loading && executions.length === 0}
			<div class="empty-state">
				<RefreshCw size={16} />
				<span>Loading executions...</span>
			</div>
		{:else if executions.length === 0}
			<div class="empty-state">
				<ListChecks size={16} />
				<span>No executions yet. Start the runtime and trigger a pipeline to see results.</span>
			</div>
		{:else}
			<div class="exec-table">
				<div class="table-header">
					<span class="col-status">Status</span>
					<span class="col-id">Execution ID</span>
					<span class="col-duration">Duration</span>
					<span class="col-expand"></span>
				</div>
				{#each executions as exec (exec.execution_id)}
					<div class="table-row-wrapper">
						<button class="table-row" onclick={() => toggleExpand(exec.execution_id)}>
							<span class="col-status">
								<span class="status-dot" style:background={statusColor(exec.status)}></span>
							</span>
							<span class="col-id" title={exec.execution_id}>
								<code>{truncateId(exec.execution_id)}</code>
							</span>
							<span class="col-duration">
								<code>{formatDuration(exec.duration_ms)}</code>
							</span>
							<span class="col-expand">
								{#if expandedId === exec.execution_id}
									<ChevronDown size={12} />
								{:else}
									<ChevronRight size={12} />
								{/if}
							</span>
						</button>
						{#if expandedId === exec.execution_id}
							<div class="exec-detail">
								<div class="detail-row">
									<span class="detail-label">ID</span>
									<code class="detail-value">{exec.execution_id}</code>
								</div>
								<div class="detail-row">
									<span class="detail-label">Status</span>
									<span class="detail-value" style:color={statusColor(exec.status)}>{exec.status}</span>
								</div>
								<div class="detail-row">
									<span class="detail-label">Duration</span>
									<code class="detail-value">{formatDuration(exec.duration_ms)}</code>
								</div>
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

<style>
	.panel {
		height: 100%;
		display: flex;
		flex-direction: column;
		background: var(--color-bg-primary);
		font-family: var(--font-sans);
	}

	.header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 12px;
		height: 40px;
		min-height: 40px;
		border-bottom: 1px solid var(--color-border);
		flex-shrink: 0;
	}

	.title {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary);
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
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
	}

	.action-btn:hover:not(:disabled) {
		background: oklch(from var(--color-text-primary) l c h / 5%);
		color: var(--color-text-primary);
	}

	.action-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}

	.content {
		flex: 1;
		overflow-y: auto;
		padding: 0;
	}

	.content::-webkit-scrollbar {
		width: 6px;
	}

	.content::-webkit-scrollbar-track {
		background: transparent;
	}

	.content::-webkit-scrollbar-thumb {
		background: var(--color-border);
		border-radius: 3px;
	}

	.empty-state {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		height: 100%;
		color: var(--color-text-secondary);
		font-size: 12px;
		opacity: 0.6;
		padding: 20px;
		text-align: center;
	}

	/* Table */
	.exec-table {
		width: 100%;
	}

	.table-header {
		display: flex;
		align-items: center;
		padding: 8px 12px;
		background: var(--color-bg-elevated);
		border-bottom: 1px solid var(--color-border);
	}

	.table-header span {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-secondary);
	}

	.col-status {
		width: 48px;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.col-id {
		flex: 2;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.col-duration {
		flex: 1;
		text-align: right;
	}

	.col-expand {
		width: 28px;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		color: var(--color-text-secondary);
	}

	.table-row-wrapper {
		border-bottom: 1px solid var(--color-border);
	}

	.table-row-wrapper:last-child {
		border-bottom: none;
	}

	.table-row {
		display: flex;
		align-items: center;
		width: 100%;
		padding: 7px 12px;
		background: none;
		border: none;
		cursor: pointer;
		font-size: 11px;
		color: var(--color-text-primary);
		transition: background 0.12s ease;
		text-align: left;
	}

	.table-row:hover {
		background: oklch(from var(--color-text-primary) l c h / 2%);
	}

	.table-row code {
		font-family: var(--font-mono);
		font-size: 11px;
	}

	.status-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		display: inline-block;
	}

	/* Expanded detail */
	.exec-detail {
		padding: 8px 16px 12px 60px;
		background: var(--color-bg-secondary);
		border-top: 1px solid var(--color-border);
		display: flex;
		flex-direction: column;
		gap: 6px;
		animation: detail-in 0.1s ease-out;
	}

	@keyframes detail-in {
		from { opacity: 0; transform: translateY(-4px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.detail-row {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.detail-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-secondary);
		min-width: 60px;
	}

	.detail-value {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--color-text-primary);
		word-break: break-all;
	}
</style>
