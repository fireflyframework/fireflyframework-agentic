<script lang="ts">
	import { onMount } from 'svelte';
	import { GitBranch, Plus, Trash2, Play, Loader2, AlertCircle } from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { currentProject } from '$lib/stores/project';
	import { getGraphSnapshot } from '$lib/stores/pipeline';
	import type { Experiment } from '$lib/types/graph';
	import type { ProjectInfo } from '$lib/types/graph';

	let experiments: Experiment[] = $state([]);
	let loading = $state(false);
	let error: string | null = $state(null);

	// Create form
	let showCreateForm = $state(false);
	let newName = $state('');
	let newVariants: Array<{ name: string; pipeline: string; traffic: number }> = $state([
		{ name: 'Variant A', pipeline: '', traffic: 50 },
		{ name: 'Variant B', pipeline: '', traffic: 50 }
	]);
	let creating = $state(false);

	// Run state
	let runningVariant: string | null = $state(null);
	let variantOutput: string | null = $state(null);

	let project: ProjectInfo | null = $state(null);

	onMount(() => {
		const unsub = currentProject.subscribe((p) => {
			project = p;
			if (p) loadExperiments(p.name);
		});
		return unsub;
	});

	async function loadExperiments(projectName: string) {
		loading = true;
		error = null;
		try {
			experiments = await api.experiments.list(projectName);
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to load experiments';
		} finally {
			loading = false;
		}
	}

	async function createExperiment() {
		if (!project || !newName.trim()) return;
		creating = true;
		error = null;
		try {
			await api.experiments.create(project.name, newName.trim(), newVariants);
			await loadExperiments(project.name);
			showCreateForm = false;
			newName = '';
			newVariants = [
				{ name: 'Variant A', pipeline: '', traffic: 50 },
				{ name: 'Variant B', pipeline: '', traffic: 50 }
			];
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to create experiment';
		} finally {
			creating = false;
		}
	}

	async function deleteExperiment(expId: string) {
		if (!project) return;
		error = null;
		try {
			await api.experiments.delete(project.name, expId);
			experiments = experiments.filter((e) => e.id !== expId);
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to delete experiment';
		}
	}

	async function runVariant(expId: string, variantName: string) {
		if (!project) return;
		runningVariant = `${expId}:${variantName}`;
		variantOutput = null;
		error = null;
		try {
			const graph = getGraphSnapshot();
			const result = await api.experiments.runVariant(project.name, expId, variantName, graph);
			variantOutput = result.output;
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to run variant';
		} finally {
			runningVariant = null;
		}
	}

	function statusColor(status: string): string {
		if (status === 'running') return 'var(--color-success)';
		if (status === 'completed') return 'var(--color-info)';
		return 'var(--color-text-secondary)';
	}
</script>

<div class="page">
	<div class="page-header">
		<div class="page-title">
			<GitBranch size={20} class="text-accent" />
			<h1>Experiments</h1>
			{#if project}
				<span class="project-badge">{project.name}</span>
			{/if}
		</div>
		<div class="page-actions">
			{#if project}
				<button class="btn-primary" onclick={() => showCreateForm = !showCreateForm}>
					<Plus size={14} />
					New Experiment
				</button>
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
					<GitBranch size={48} />
				</div>
				<h2 class="empty-title">No project selected</h2>
				<p class="empty-subtitle">Select or create a project to manage experiments</p>
			</div>
		{:else if loading}
			<div class="loading-state">
				<Loader2 size={24} class="spin" />
				<span>Loading experiments...</span>
			</div>
		{:else}
			<!-- Create Form -->
			{#if showCreateForm}
				<div class="section-card create-form">
					<h2 class="section-title">Create Experiment</h2>
					<div class="form-group">
						<label class="form-label" for="exp-name">Name</label>
						<input
							id="exp-name"
							class="form-input"
							type="text"
							placeholder="e.g. GPT-4o vs Claude Sonnet"
							bind:value={newName}
						/>
					</div>

					<div class="form-group">
						<!-- svelte-ignore a11y_label_has_associated_control -->
						<label class="form-label">Variants</label>
						{#each newVariants as variant, i}
							<div class="variant-input-row">
								<input
									class="form-input variant-name-input"
									type="text"
									placeholder="Variant name"
									bind:value={variant.name}
								/>
								<input
									class="form-input variant-pipeline-input"
									type="text"
									placeholder="Pipeline name"
									bind:value={variant.pipeline}
								/>
								<input
									class="form-input variant-traffic-input"
									type="number"
									min="0"
									max="100"
									bind:value={variant.traffic}
								/>
								<span class="traffic-pct">%</span>
							</div>
						{/each}
					</div>

					<div class="form-actions">
						<button class="btn-secondary" onclick={() => showCreateForm = false}>Cancel</button>
						<button
							class="btn-primary"
							disabled={creating || !newName.trim()}
							onclick={createExperiment}
						>
							{#if creating}
								<Loader2 size={14} class="spin" />
								Creating...
							{:else}
								Create
							{/if}
						</button>
					</div>
				</div>
			{/if}

			<!-- Experiments List -->
			{#if experiments.length === 0 && !showCreateForm}
				<div class="empty-state-card">
					<div class="empty-icon">
						<GitBranch size={48} />
					</div>
					<h2 class="empty-title">Design your first experiment</h2>
					<p class="empty-subtitle">
						Compare pipeline variants side-by-side. Create an experiment to get started.
					</p>
					<button class="btn-primary" onclick={() => showCreateForm = true}>
						<Plus size={14} />
						Get Started
					</button>
				</div>
			{:else}
				{#each experiments as exp}
					<div class="experiment-card">
						<div class="experiment-card-header">
							<div class="experiment-info">
								<h3 class="experiment-name">{exp.name}</h3>
								<span class="experiment-date">Created {exp.created_at.slice(0, 10)}</span>
							</div>
							<div class="experiment-actions">
								<span
									class="status-badge"
									style="--status-color: {statusColor(exp.status)}"
								>
									{#if exp.status === 'running'}
										<span class="pulse-dot"></span>
									{/if}
									{exp.status}
								</span>
								<button
									class="icon-btn"
									title="Delete experiment"
									onclick={() => deleteExperiment(exp.id)}
								>
									<Trash2 size={14} />
								</button>
							</div>
						</div>

						<!-- Traffic Split Visual -->
						<div class="traffic-split-bar">
							{#each exp.variants as variant, i}
								<div
									class="traffic-segment"
									style="width: {variant.traffic}%; --segment-color: {i === 0 ? 'var(--color-info)' : 'var(--color-accent)'}"
								>
									<span class="segment-label">{variant.name} ({variant.traffic}%)</span>
								</div>
							{/each}
						</div>

						<!-- Variant Rows -->
						<div class="variants-list">
							{#each exp.variants as variant, i}
								<div class="variant-row">
									<div class="variant-indicator" style="--indicator-color: {i === 0 ? 'var(--color-info)' : 'var(--color-accent)'}"></div>
									<div class="variant-details">
										<div class="variant-name-row">
											<span class="variant-name">{variant.name}</span>
											<span class="variant-pipeline">{variant.pipeline || 'No pipeline assigned'}</span>
										</div>
										<div class="variant-stats">
											<div class="stat">
												<span class="stat-label">Traffic</span>
												<span class="stat-value">{variant.traffic}%</span>
											</div>
										</div>
									</div>
									<button
										class="btn-secondary btn-sm"
										disabled={runningVariant === `${exp.id}:${variant.name}`}
										onclick={() => runVariant(exp.id, variant.name)}
									>
										{#if runningVariant === `${exp.id}:${variant.name}`}
											<Loader2 size={12} class="spin" />
											Running...
										{:else}
											<Play size={12} />
											Run
										{/if}
									</button>
								</div>
							{/each}
						</div>

						{#if variantOutput !== null}
							<div class="variant-output">
								<span class="output-label">Output:</span>
								<pre class="output-content">{variantOutput}</pre>
							</div>
						{/if}

						<div class="coming-soon-footer">
							<span class="coming-soon-badge">Coming Soon</span>
							<span class="coming-soon-text">Automatic traffic splitting, A/B metrics, and statistical significance testing</span>
						</div>
					</div>
				{/each}
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

	.btn-secondary {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 14px;
		background: transparent;
		border: 1px solid var(--color-border);
		border-radius: 6px;
		color: var(--color-text-primary);
		font-size: 12px;
		cursor: pointer;
		transition: border-color 0.15s;
	}

	.btn-secondary:hover:not(:disabled) {
		border-color: var(--color-accent);
	}

	.btn-secondary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-sm {
		padding: 4px 10px;
		font-size: 11px;
	}

	.icon-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: none;
		border-radius: 6px;
		background: transparent;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.icon-btn:hover {
		background: oklch(from var(--color-error) l c h / 15%);
		color: var(--color-error);
	}

	/* Section card */
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
		font-size: 14px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	/* Create form */
	.form-group {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.form-label {
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-secondary);
	}

	.form-input {
		padding: 8px 12px;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		font-size: 13px;
		color: var(--color-text-primary);
		outline: none;
	}

	.form-input:focus {
		border-color: var(--color-accent);
	}

	.variant-input-row {
		display: flex;
		gap: 8px;
		align-items: center;
	}

	.variant-name-input {
		flex: 1;
	}

	.variant-pipeline-input {
		flex: 2;
	}

	.variant-traffic-input {
		width: 60px;
		text-align: center;
	}

	.traffic-pct {
		font-size: 12px;
		color: var(--color-text-secondary);
	}

	.form-actions {
		display: flex;
		gap: 10px;
		justify-content: flex-end;
		padding-top: 6px;
	}

	/* Empty State */
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

	/* Experiment Card */
	.experiment-card {
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		padding: 20px;
		display: flex;
		flex-direction: column;
		gap: 20px;
	}

	.experiment-card-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}

	.experiment-info {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.experiment-name {
		font-size: 16px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	.experiment-date {
		font-size: 12px;
		color: var(--color-text-secondary);
	}

	.experiment-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.status-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 10px;
		border-radius: 6px;
		font-size: 11px;
		font-weight: 500;
		text-transform: capitalize;
		background: oklch(from var(--status-color) l c h / 15%);
		color: var(--status-color);
		flex-shrink: 0;
	}

	.pulse-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--color-success);
		animation: pulse-glow 2s ease-in-out infinite;
	}

	@keyframes pulse-glow {
		0%, 100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.5; transform: scale(1.3); }
	}

	/* Traffic Split Bar */
	.traffic-split-bar {
		display: flex;
		height: 32px;
		border-radius: 6px;
		overflow: hidden;
		gap: 2px;
	}

	.traffic-segment {
		display: flex;
		align-items: center;
		justify-content: center;
		background: oklch(from var(--segment-color) l c h / 20%);
		color: var(--segment-color);
		transition: width 0.3s ease;
	}

	.segment-label {
		font-size: 11px;
		font-weight: 500;
	}

	/* Variant Rows */
	.variants-list {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.variant-row {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 14px;
		background: var(--color-bg-secondary);
		border-radius: 8px;
		border: 1px solid oklch(from var(--color-border) l c h / 60%);
	}

	.variant-indicator {
		width: 4px;
		height: 100%;
		min-height: 40px;
		border-radius: 2px;
		background: var(--indicator-color);
		flex-shrink: 0;
	}

	.variant-details {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.variant-name-row {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.variant-name {
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.variant-pipeline {
		font-size: 12px;
		color: var(--color-text-secondary);
		font-family: var(--font-mono);
	}

	.variant-stats {
		display: flex;
		gap: 24px;
	}

	.stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.stat-label {
		font-size: 10px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary);
	}

	.stat-value {
		font-size: 16px;
		font-weight: 700;
		color: var(--color-text-primary);
		font-family: var(--font-mono);
	}

	/* Variant output */
	.variant-output {
		padding: 12px;
		background: var(--color-bg-secondary);
		border-radius: 8px;
		border: 1px solid var(--color-border);
	}

	.output-label {
		font-size: 11px;
		font-weight: 500;
		color: var(--color-text-secondary);
		display: block;
		margin-bottom: 6px;
	}

	.output-content {
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--color-text-primary);
		margin: 0;
		white-space: pre-wrap;
		word-break: break-word;
	}

	/* Coming soon footer */
	.coming-soon-footer {
		display: flex;
		align-items: center;
		gap: 10px;
		padding-top: 12px;
		border-top: 1px solid var(--color-border);
	}

	.coming-soon-badge {
		font-size: 10px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 2px 8px;
		border-radius: 4px;
		background: oklch(from var(--color-warning) l c h / 15%);
		color: var(--color-warning);
		flex-shrink: 0;
	}

	.coming-soon-text {
		font-size: 11px;
		color: var(--color-text-secondary);
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
