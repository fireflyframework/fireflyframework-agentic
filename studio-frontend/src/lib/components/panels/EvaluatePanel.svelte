<script lang="ts">
	import { RefreshCw, Upload, Play, CheckCircle, XCircle, FileText } from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { currentProject } from '$lib/stores/project';
	import { addToast } from '$lib/stores/notifications';
	import { getGraphSnapshot } from '$lib/stores/pipeline';
	import type { DatasetInfo, EvalRunResult } from '$lib/types/graph';

	let loading = $state(false);
	let datasets: DatasetInfo[] = $state([]);
	let selectedDataset: string | null = $state(null);
	let running = $state(false);
	let result: EvalRunResult | null = $state(null);

	let fileInput: HTMLInputElement | undefined = $state();

	async function loadDatasets() {
		const proj = $currentProject;
		if (!proj) return;
		loading = true;
		try {
			datasets = await api.evaluate.listDatasets(proj.name);
		} catch {
			datasets = [];
			addToast('Failed to load datasets', 'error');
		} finally {
			loading = false;
		}
	}

	async function uploadDataset() {
		const proj = $currentProject;
		if (!proj) {
			addToast('Select a project first', 'error');
			return;
		}
		fileInput?.click();
	}

	async function handleFileUpload(event: Event) {
		const proj = $currentProject;
		if (!proj) return;
		const target = event.target as HTMLInputElement;
		const file = target.files?.[0];
		if (!file) return;
		try {
			const res = await api.evaluate.uploadDataset(proj.name, file);
			addToast(`Dataset uploaded: ${res.test_cases} test cases`, 'success');
			await loadDatasets();
		} catch {
			addToast('Failed to upload dataset', 'error');
		}
		// Reset input so same file can be re-selected
		target.value = '';
	}

	async function runEvaluation() {
		const proj = $currentProject;
		if (!proj || !selectedDataset) return;
		running = true;
		result = null;
		try {
			const graph = getGraphSnapshot();
			result = await api.evaluate.run(proj.name, selectedDataset, graph);
			addToast(`Evaluation complete: ${result.pass_rate.toFixed(1)}% pass rate`, 'success');
		} catch {
			addToast('Evaluation failed', 'error');
		} finally {
			running = false;
		}
	}

	$effect(() => {
		if ($currentProject) loadDatasets();
	});
</script>

<div class="panel">
	<div class="header">
		<span class="title">Evaluate</span>
		<div class="header-actions">
			<button class="action-btn text-btn" onclick={uploadDataset}>
				<Upload size={12} />
				Upload Dataset
			</button>
			<button class="action-btn" onclick={loadDatasets} title="Refresh">
				<RefreshCw size={13} />
			</button>
		</div>
		<input
			type="file"
			accept=".json,.jsonl,.csv"
			style="display:none"
			bind:this={fileInput}
			onchange={handleFileUpload}
		/>
	</div>

	<div class="content">
		<div class="section">
			<div class="section-label">Datasets</div>
			{#if loading}
				<div class="mini-empty">
					<RefreshCw size={13} />
					<span>Loading...</span>
				</div>
			{:else if datasets.length === 0}
				<div class="mini-empty">
					<FileText size={13} />
					<span>No datasets. Upload a JSON or CSV file to get started.</span>
				</div>
			{:else}
				<div class="dataset-list">
					{#each datasets as ds (ds.filename)}
						<button
							class="dataset-item"
							class:selected={selectedDataset === ds.filename}
							onclick={() => (selectedDataset = ds.filename)}
						>
							<FileText size={12} />
							<span class="ds-name">{ds.filename}</span>
							<span class="ds-meta">{ds.test_cases} cases</span>
						</button>
					{/each}
				</div>
			{/if}
		</div>

		<div class="run-section">
			<button
				class="run-btn"
				onclick={runEvaluation}
				disabled={!selectedDataset || running || !$currentProject}
			>
				<Play size={12} />
				{running ? 'Running...' : 'Run Evaluation'}
			</button>
		</div>

		{#if result}
			<div class="section">
				<div class="section-label">Results</div>
				<div class="metrics-row">
					<div class="metric-card">
						<span class="metric-value">{result.total}</span>
						<span class="metric-label">Total</span>
					</div>
					<div class="metric-card success">
						<span class="metric-value">{result.passed}</span>
						<span class="metric-label">Passed</span>
					</div>
					<div class="metric-card error">
						<span class="metric-value">{result.failed}</span>
						<span class="metric-label">Failed</span>
					</div>
					<div class="metric-card">
						<span class="metric-value">{result.pass_rate.toFixed(1)}%</span>
						<span class="metric-label">Pass Rate</span>
					</div>
				</div>

				{#if result.results.length > 0}
					<div class="results-list">
						{#each result.results as r, i (i)}
							<div class="result-row" class:passed={r.passed} class:failed={!r.passed}>
								<span class="result-icon">
									{#if r.passed}
										<CheckCircle size={12} />
									{:else}
										<XCircle size={12} />
									{/if}
								</span>
								<span class="result-input">{r.input}</span>
								{#if r.error}
									<span class="result-error">{r.error}</span>
								{/if}
							</div>
						{/each}
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

	.header-actions {
		display: flex;
		align-items: center;
		gap: 4px;
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

	.action-btn:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-text-primary, #e8e8ed);
	}

	.text-btn {
		width: auto;
		gap: 5px;
		padding: 0 8px;
		font-size: 11px;
		font-weight: 500;
	}

	.content {
		flex: 1;
		overflow-y: auto;
		padding: 8px 12px;
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

	.section {
		margin-bottom: 12px;
	}

	.section-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary, #8888a0);
		margin-bottom: 6px;
	}

	.mini-empty {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 12px;
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		opacity: 0.6;
	}

	.dataset-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.dataset-item {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 5px 8px;
		border: 1px solid transparent;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		font-size: 12px;
		cursor: pointer;
		text-align: left;
		transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;
	}

	.dataset-item:hover {
		background: var(--color-bg-secondary, #12121a);
		color: var(--color-text-primary, #e8e8ed);
	}

	.dataset-item.selected {
		background: var(--color-bg-elevated, #1a1a2a);
		border-color: var(--color-accent, #ff6b35);
		color: var(--color-text-primary, #e8e8ed);
	}

	.ds-name {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.ds-meta {
		font-size: 10px;
		opacity: 0.6;
		flex-shrink: 0;
	}

	.run-section {
		margin-bottom: 12px;
	}

	.run-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 14px;
		border: none;
		background: var(--color-accent, #ff6b35);
		border-radius: 4px;
		color: #fff;
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		transition: filter 0.15s ease, opacity 0.15s ease;
	}

	.run-btn:hover:not(:disabled) {
		filter: brightness(1.1);
	}

	.run-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}

	.metrics-row {
		display: flex;
		gap: 8px;
		margin-bottom: 10px;
	}

	.metric-card {
		flex: 1;
		padding: 8px 10px;
		background: var(--color-bg-secondary, #12121a);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
	}

	.metric-card.success {
		border-color: rgba(34, 197, 94, 0.3);
	}

	.metric-card.error {
		border-color: rgba(239, 68, 68, 0.3);
	}

	.metric-value {
		font-size: 16px;
		font-weight: 700;
		color: var(--color-text-primary, #e8e8ed);
	}

	.metric-card.success .metric-value {
		color: #22c55e;
	}

	.metric-card.error .metric-value {
		color: #ef4444;
	}

	.metric-label {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	.results-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.result-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 4px 8px;
		border-radius: 4px;
		font-size: 11px;
	}

	.result-row.passed {
		color: #22c55e;
	}

	.result-row.failed {
		color: #ef4444;
	}

	.result-icon {
		display: flex;
		align-items: center;
		flex-shrink: 0;
	}

	.result-input {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--color-text-primary, #e8e8ed);
	}

	.result-error {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.7;
		flex-shrink: 0;
		max-width: 200px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
