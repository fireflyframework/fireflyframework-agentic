<script lang="ts">
	import { onMount } from 'svelte';
	import { FlaskConical, Plus, CheckCircle2, XCircle, Loader2, Calendar, Upload, Play, ChevronDown, ChevronRight, AlertCircle } from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { currentProject } from '$lib/stores/project';
	import { getGraphSnapshot } from '$lib/stores/pipeline';
	import type { DatasetInfo, EvalRunResult, EvalTestResult } from '$lib/types/graph';
	import type { ProjectInfo } from '$lib/types/graph';

	let datasets: DatasetInfo[] = $state([]);
	let loading = $state(false);
	let error: string | null = $state(null);

	// Upload state
	let fileInput: HTMLInputElement | undefined = $state();
	let uploading = $state(false);

	// Run state
	let selectedDataset: string | null = $state(null);
	let running = $state(false);
	let evalResult: EvalRunResult | null = $state(null);
	let expandedResults = $state(false);

	let project: ProjectInfo | null = $state(null);

	onMount(() => {
		const unsub = currentProject.subscribe((p) => {
			project = p;
			if (p) loadDatasets(p.name);
		});
		return unsub;
	});

	async function loadDatasets(projectName: string) {
		loading = true;
		error = null;
		try {
			datasets = await api.evaluate.listDatasets(projectName);
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to load datasets';
		} finally {
			loading = false;
		}
	}

	async function handleUpload() {
		if (!fileInput?.files?.length || !project) return;
		const file = fileInput.files[0];
		uploading = true;
		error = null;
		try {
			await api.evaluate.uploadDataset(project.name, file);
			await loadDatasets(project.name);
			fileInput.value = '';
		} catch (err) {
			error = err instanceof Error ? err.message : 'Upload failed';
		} finally {
			uploading = false;
		}
	}

	async function runEvaluation() {
		if (!selectedDataset || !project) return;
		running = true;
		error = null;
		evalResult = null;
		try {
			const graph = getGraphSnapshot();
			evalResult = await api.evaluate.run(project.name, selectedDataset, graph);
		} catch (err) {
			error = err instanceof Error ? err.message : 'Evaluation failed';
		} finally {
			running = false;
		}
	}

	function passRate(passed: number, total: number): number {
		if (total === 0) return 0;
		return Math.round((passed / total) * 100);
	}

	function statusColor(passed: boolean): string {
		return passed ? 'var(--color-success)' : 'var(--color-error)';
	}

	function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}
</script>

<div class="page">
	<div class="page-header">
		<div class="page-title">
			<FlaskConical size={20} class="text-accent" />
			<h1>Evaluation Lab</h1>
			{#if project}
				<span class="project-badge">{project.name}</span>
			{/if}
		</div>
	</div>

	{#if error}
		<div class="error-banner">
			<AlertCircle size={14} />
			<span>{error}</span>
			<button class="dismiss-btn" onclick={() => error = null}>&times;</button>
		</div>
	{/if}

	<div class="page-content">
		{#if !project}
			<div class="empty-state-card">
				<div class="empty-icon">
					<FlaskConical size={48} />
				</div>
				<h2 class="empty-title">No project selected</h2>
				<p class="empty-subtitle">Select or create a project to start evaluating your pipelines</p>
			</div>
		{:else if loading}
			<div class="loading-state">
				<Loader2 size={24} class="spin" />
				<span>Loading datasets...</span>
			</div>
		{:else}
			<!-- Upload Section -->
			<div class="section-card">
				<h2 class="section-title">
					<Upload size={16} />
					Upload Dataset
				</h2>
				<p class="section-description">
					Upload a JSONL file where each line has an <code>"input"</code> field and optionally an <code>"expected_output"</code> field.
				</p>
				<div class="upload-row">
					<input
						bind:this={fileInput}
						type="file"
						accept=".jsonl,.json"
						class="file-input"
					/>
					<button class="btn-primary" onclick={handleUpload} disabled={uploading}>
						{#if uploading}
							<Loader2 size={14} class="spin" />
							Uploading...
						{:else}
							<Upload size={14} />
							Upload
						{/if}
					</button>
				</div>
			</div>

			<!-- Datasets Section -->
			{#if datasets.length === 0}
				<div class="empty-state-card">
					<div class="empty-icon">
						<FlaskConical size={48} />
					</div>
					<h2 class="empty-title">No datasets yet</h2>
					<p class="empty-subtitle">
						Upload a JSONL dataset to evaluate your pipeline against test cases
					</p>
				</div>
			{:else}
				<div class="section-card">
					<h2 class="section-title">
						<FlaskConical size={16} />
						Datasets
					</h2>
					<div class="dataset-list">
						{#each datasets as ds}
							<button
								class="dataset-row"
								class:selected={selectedDataset === ds.filename}
								onclick={() => selectedDataset = ds.filename}
							>
								<div class="dataset-info">
									<span class="dataset-name">{ds.filename}</span>
									<span class="dataset-meta">{ds.test_cases} test cases &middot; {formatSize(ds.size)}</span>
								</div>
								{#if selectedDataset === ds.filename}
									<CheckCircle2 size={16} class="text-accent" />
								{/if}
							</button>
						{/each}
					</div>

					<div class="run-section">
						<button
							class="btn-primary btn-run"
							disabled={!selectedDataset || running}
							onclick={runEvaluation}
						>
							{#if running}
								<Loader2 size={14} class="spin" />
								Running evaluation...
							{:else}
								<Play size={14} />
								Run Evaluation
							{/if}
						</button>
						{#if selectedDataset}
							<span class="run-hint">Will run the current canvas pipeline against <strong>{selectedDataset}</strong></span>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Results Section -->
			{#if evalResult}
				<div class="section-card results-card">
					<div class="results-header">
						<h2 class="section-title">
							{#if evalResult.pass_rate >= 80}
								<CheckCircle2 size={16} style="color: var(--color-success)" />
							{:else}
								<XCircle size={16} style="color: var(--color-error)" />
							{/if}
							Results
						</h2>
						<span class="results-dataset">{evalResult.dataset}</span>
					</div>

					<div class="results-summary">
						<div class="summary-stat">
							<span class="summary-value">{evalResult.pass_rate}%</span>
							<span class="summary-label">Pass Rate</span>
						</div>
						<div class="summary-stat">
							<span class="summary-value">{evalResult.passed}</span>
							<span class="summary-label">Passed</span>
						</div>
						<div class="summary-stat">
							<span class="summary-value">{evalResult.failed}</span>
							<span class="summary-label">Failed</span>
						</div>
						<div class="summary-stat">
							<span class="summary-value">{evalResult.error_count}</span>
							<span class="summary-label">Errors</span>
						</div>
					</div>

					<div class="progress-bar">
						<div class="progress-fill progress-pass" style="width: {passRate(evalResult.passed, evalResult.total)}%"></div>
						<div class="progress-fill progress-fail" style="width: {passRate(evalResult.failed + evalResult.error_count, evalResult.total)}%"></div>
					</div>

					<!-- Expandable detail -->
					<button class="expand-btn" onclick={() => expandedResults = !expandedResults}>
						{#if expandedResults}
							<ChevronDown size={14} />
						{:else}
							<ChevronRight size={14} />
						{/if}
						{expandedResults ? 'Hide' : 'Show'} individual results ({evalResult.total})
					</button>

					{#if expandedResults}
						<div class="results-detail">
							{#each evalResult.results as r, i}
								<div class="result-row" class:result-pass={r.passed} class:result-fail={!r.passed}>
									<div class="result-status">
										{#if r.passed}
											<CheckCircle2 size={14} style="color: var(--color-success)" />
										{:else}
											<XCircle size={14} style="color: var(--color-error)" />
										{/if}
										<span class="result-index">#{i + 1}</span>
									</div>
									<div class="result-content">
										<div class="result-field">
											<span class="field-label">Input:</span>
											<span class="field-value">{r.input}</span>
										</div>
										{#if r.expected_output}
											<div class="result-field">
												<span class="field-label">Expected:</span>
												<span class="field-value">{r.expected_output}</span>
											</div>
										{/if}
										<div class="result-field">
											<span class="field-label">Actual:</span>
											<span class="field-value">{r.actual_output || '(empty)'}</span>
										</div>
										{#if r.error}
											<div class="result-field result-error">
												<span class="field-label">Error:</span>
												<span class="field-value">{r.error}</span>
											</div>
										{/if}
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/if}
		{/if}
	</div>
</div>

<style>
	.page {
		display: flex;
		flex-direction: column;
		height: 100%;
		padding: 24px;
		gap: 24px;
		overflow-y: auto;
		background: var(--color-bg-primary);
	}

	.page-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
	}

	.page-title {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.page-title h1 {
		font-size: 20px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	.project-badge {
		font-size: 11px;
		font-weight: 500;
		padding: 2px 8px;
		border-radius: 4px;
		background: oklch(from var(--color-accent) l c h / 15%);
		color: var(--color-accent);
	}

	.page-content {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 20px;
	}

	/* Error banner */
	.error-banner {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 14px;
		background: oklch(from var(--color-error) l c h / 12%);
		border: 1px solid oklch(from var(--color-error) l c h / 30%);
		border-radius: 8px;
		color: var(--color-error);
		font-size: 13px;
	}

	.dismiss-btn {
		margin-left: auto;
		background: none;
		border: none;
		color: var(--color-error);
		cursor: pointer;
		font-size: 16px;
		padding: 0 4px;
	}

	/* Buttons */
	.btn-primary {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 16px;
		background: var(--color-accent);
		border: none;
		border-radius: 8px;
		color: white;
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		transition: opacity 0.15s;
	}

	.btn-primary:hover:not(:disabled) {
		opacity: 0.9;
	}

	.btn-primary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-run {
		padding: 10px 20px;
	}

	/* Section cards */
	.section-card {
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		padding: 20px;
		display: flex;
		flex-direction: column;
		gap: 14px;
	}

	.section-title {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 14px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	.section-description {
		font-size: 12px;
		color: var(--color-text-secondary);
		margin: 0;
		line-height: 1.5;
	}

	.section-description code {
		font-family: var(--font-mono);
		font-size: 11px;
		padding: 1px 5px;
		background: var(--color-bg-secondary);
		border-radius: 3px;
	}

	/* Upload */
	.upload-row {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.file-input {
		flex: 1;
		font-size: 13px;
		color: var(--color-text-primary);
	}

	/* Dataset list */
	.dataset-list {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.dataset-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 14px;
		background: var(--color-bg-secondary);
		border: 1px solid transparent;
		border-radius: 8px;
		cursor: pointer;
		transition: border-color 0.15s;
		text-align: left;
		width: 100%;
	}

	.dataset-row:hover {
		border-color: var(--color-border);
	}

	.dataset-row.selected {
		border-color: var(--color-accent);
		background: oklch(from var(--color-accent) l c h / 8%);
	}

	.dataset-info {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.dataset-name {
		font-size: 13px;
		font-weight: 500;
		color: var(--color-text-primary);
		font-family: var(--font-mono);
	}

	.dataset-meta {
		font-size: 11px;
		color: var(--color-text-secondary);
	}

	/* Run section */
	.run-section {
		display: flex;
		align-items: center;
		gap: 14px;
		padding-top: 6px;
		border-top: 1px solid var(--color-border);
	}

	.run-hint {
		font-size: 12px;
		color: var(--color-text-secondary);
	}

	/* Results */
	.results-card {
		gap: 16px;
	}

	.results-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.results-dataset {
		font-size: 12px;
		color: var(--color-text-secondary);
		font-family: var(--font-mono);
	}

	.results-summary {
		display: flex;
		gap: 32px;
	}

	.summary-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.summary-value {
		font-size: 28px;
		font-weight: 700;
		color: var(--color-text-primary);
		font-family: var(--font-mono);
		line-height: 1;
	}

	.summary-label {
		font-size: 10px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary);
	}

	/* Progress bar */
	.progress-bar {
		display: flex;
		height: 6px;
		border-radius: 3px;
		overflow: hidden;
		background: var(--color-bg-secondary);
	}

	.progress-fill {
		height: 100%;
		transition: width 0.3s ease;
	}

	.progress-pass {
		background: var(--color-success);
	}

	.progress-fail {
		background: var(--color-error);
	}

	/* Expand button */
	.expand-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 0;
		background: none;
		border: none;
		color: var(--color-text-secondary);
		font-size: 12px;
		cursor: pointer;
		transition: color 0.15s;
	}

	.expand-btn:hover {
		color: var(--color-text-primary);
	}

	/* Results detail */
	.results-detail {
		display: flex;
		flex-direction: column;
		gap: 8px;
		max-height: 400px;
		overflow-y: auto;
	}

	.result-row {
		display: flex;
		gap: 10px;
		padding: 10px 12px;
		border-radius: 6px;
		background: var(--color-bg-secondary);
		border-left: 3px solid transparent;
	}

	.result-pass {
		border-left-color: var(--color-success);
	}

	.result-fail {
		border-left-color: var(--color-error);
	}

	.result-status {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
	}

	.result-index {
		font-size: 11px;
		font-weight: 500;
		color: var(--color-text-secondary);
		font-family: var(--font-mono);
	}

	.result-content {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}

	.result-field {
		display: flex;
		gap: 8px;
		font-size: 12px;
	}

	.field-label {
		flex-shrink: 0;
		font-weight: 500;
		color: var(--color-text-secondary);
		min-width: 60px;
	}

	.field-value {
		color: var(--color-text-primary);
		font-family: var(--font-mono);
		font-size: 11px;
		word-break: break-word;
	}

	.result-error .field-value {
		color: var(--color-error);
	}

	/* Empty state */
	.empty-state-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 48px 24px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		text-align: center;
		gap: 16px;
	}

	.empty-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 80px;
		height: 80px;
		border-radius: 16px;
		background: oklch(from var(--color-accent) l c h / 10%);
		color: var(--color-accent);
	}

	.empty-title {
		font-size: 18px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	.empty-subtitle {
		font-size: 13px;
		color: var(--color-text-secondary);
		margin: 0;
		max-width: 400px;
		line-height: 1.5;
	}

	/* Loading */
	.loading-state {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		padding: 48px;
		color: var(--color-text-secondary);
		font-size: 13px;
	}

	:global(.spin) {
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		from { transform: rotate(0deg); }
		to { transform: rotate(360deg); }
	}
</style>
