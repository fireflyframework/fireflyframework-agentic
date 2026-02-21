<script lang="ts">
	import { RefreshCw, Plus, Trash2, Play, GitBranch, FlaskConical } from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { currentProject } from '$lib/stores/project';
	import { addToast } from '$lib/stores/notifications';
	import type { Experiment } from '$lib/types/graph';

	let loading = $state(false);
	let experiments: Experiment[] = $state([]);
	let showCreateForm = $state(false);

	// Create form state
	let newName = $state('');
	let variants: Array<{ name: string; pipeline: string; traffic: number }> = $state([
		{ name: 'Control', pipeline: 'default', traffic: 50 },
		{ name: 'Variant A', pipeline: 'default', traffic: 50 }
	]);

	async function loadExperiments() {
		const proj = $currentProject;
		if (!proj) return;
		loading = true;
		try {
			experiments = await api.experiments.list(proj.name);
		} catch {
			experiments = [];
			addToast('Failed to load experiments', 'error');
		} finally {
			loading = false;
		}
	}

	async function createExperiment() {
		const proj = $currentProject;
		if (!proj || !newName.trim()) return;
		try {
			await api.experiments.create(proj.name, newName.trim(), variants);
			addToast('Experiment created', 'success');
			newName = '';
			showCreateForm = false;
			variants = [
				{ name: 'Control', pipeline: 'default', traffic: 50 },
				{ name: 'Variant A', pipeline: 'default', traffic: 50 }
			];
			await loadExperiments();
		} catch {
			addToast('Failed to create experiment', 'error');
		}
	}

	async function deleteExperiment(id: string) {
		const proj = $currentProject;
		if (!proj) return;
		try {
			await api.experiments.delete(proj.name, id);
			addToast('Experiment deleted', 'success');
			await loadExperiments();
		} catch {
			addToast('Failed to delete experiment', 'error');
		}
	}

	function addVariant() {
		const idx = variants.length + 1;
		variants = [...variants, { name: `Variant ${String.fromCharCode(64 + idx)}`, pipeline: 'default', traffic: 0 }];
	}

	function removeVariant(index: number) {
		variants = variants.filter((_, i) => i !== index);
	}

	function statusBadgeClass(status: Experiment['status']): string {
		switch (status) {
			case 'running': return 'badge-running';
			case 'completed': return 'badge-completed';
			default: return 'badge-draft';
		}
	}

	$effect(() => {
		if ($currentProject) loadExperiments();
	});
</script>

<div class="panel">
	<div class="header">
		<span class="title">Experiments</span>
		<div class="header-actions">
			<button class="action-btn text-btn" onclick={() => (showCreateForm = !showCreateForm)}>
				<Plus size={12} />
				New
			</button>
			<button class="action-btn" onclick={loadExperiments} title="Refresh">
				<RefreshCw size={13} />
			</button>
		</div>
	</div>

	<div class="content">
		{#if showCreateForm}
			<div class="create-form">
				<div class="form-row">
					<label class="form-label">Name</label>
					<input
						class="form-input"
						type="text"
						placeholder="Experiment name"
						bind:value={newName}
					/>
				</div>
				<div class="form-row">
					<label class="form-label">Variants</label>
					<div class="variants-config">
						{#each variants as v, i (i)}
							<div class="variant-row">
								<input class="form-input small" type="text" bind:value={v.name} placeholder="Name" />
								<input class="form-input small" type="text" bind:value={v.pipeline} placeholder="Pipeline" />
								<div class="traffic-input">
									<input class="form-input tiny" type="number" bind:value={v.traffic} min={0} max={100} />
									<span class="traffic-pct">%</span>
								</div>
								{#if variants.length > 2}
									<button class="icon-btn" onclick={() => removeVariant(i)} title="Remove variant">
										<Trash2 size={11} />
									</button>
								{/if}
							</div>
						{/each}
						<button class="add-variant-btn" onclick={addVariant}>
							<Plus size={11} /> Add variant
						</button>
					</div>
				</div>
				<div class="form-actions">
					<button class="create-btn" onclick={createExperiment} disabled={!newName.trim()}>
						Create Experiment
					</button>
					<button class="cancel-btn" onclick={() => (showCreateForm = false)}>
						Cancel
					</button>
				</div>
			</div>
		{/if}

		{#if loading}
			<div class="empty-state">
				<RefreshCw size={16} />
				<span>Loading...</span>
			</div>
		{:else if experiments.length === 0 && !showCreateForm}
			<div class="empty-state">
				<FlaskConical size={16} />
				<span>No experiments yet. Create one to A/B test pipeline variants.</span>
			</div>
		{:else}
			<div class="experiment-list">
				{#each experiments as exp (exp.id)}
					<div class="experiment-card">
						<div class="exp-header">
							<GitBranch size={13} />
							<span class="exp-name">{exp.name}</span>
							<span class="status-badge {statusBadgeClass(exp.status)}">{exp.status}</span>
							<span class="exp-date">{new Date(exp.created_at).toLocaleDateString()}</span>
							<button class="icon-btn" onclick={() => deleteExperiment(exp.id)} title="Delete experiment">
								<Trash2 size={12} />
							</button>
						</div>
						<div class="variants-list">
							{#each exp.variants as variant (variant.name)}
								<div class="variant-item">
									<span class="variant-name">{variant.name}</span>
									<div class="traffic-bar-container">
										<div class="traffic-bar" style:width="{variant.traffic}%"></div>
									</div>
									<span class="variant-traffic">{variant.traffic}%</span>
								</div>
							{/each}
						</div>
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

	/* Create form */
	.create-form {
		padding: 10px;
		margin-bottom: 12px;
		background: var(--color-bg-secondary, #12121a);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
	}

	.form-row {
		margin-bottom: 8px;
	}

	.form-label {
		display: block;
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary, #8888a0);
		margin-bottom: 4px;
	}

	.form-input {
		width: 100%;
		padding: 5px 8px;
		border: 1px solid var(--color-border, #2a2a3a);
		background: var(--color-bg-primary, #0a0a12);
		border-radius: 4px;
		color: var(--color-text-primary, #e8e8ed);
		font-size: 12px;
		font-family: var(--font-sans, system-ui, -apple-system, sans-serif);
		outline: none;
		transition: border-color 0.15s ease;
		box-sizing: border-box;
	}

	.form-input:focus {
		border-color: var(--color-accent, #ff6b35);
	}

	.form-input.small {
		width: auto;
		flex: 1;
		min-width: 0;
	}

	.form-input.tiny {
		width: 50px;
		text-align: center;
	}

	.variants-config {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.variant-row {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.traffic-input {
		display: flex;
		align-items: center;
		gap: 2px;
		flex-shrink: 0;
	}

	.traffic-pct {
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
	}

	.add-variant-btn {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px 8px;
		border: 1px dashed var(--color-border, #2a2a3a);
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		cursor: pointer;
		transition: border-color 0.15s ease, color 0.15s ease;
		width: fit-content;
	}

	.add-variant-btn:hover {
		border-color: var(--color-text-secondary, #8888a0);
		color: var(--color-text-primary, #e8e8ed);
	}

	.form-actions {
		display: flex;
		gap: 6px;
		margin-top: 8px;
	}

	.create-btn {
		padding: 5px 12px;
		border: none;
		background: var(--color-accent, #ff6b35);
		border-radius: 4px;
		color: #fff;
		font-size: 11px;
		font-weight: 600;
		cursor: pointer;
		transition: filter 0.15s ease, opacity 0.15s ease;
	}

	.create-btn:hover:not(:disabled) {
		filter: brightness(1.1);
	}

	.create-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}

	.cancel-btn {
		padding: 5px 12px;
		border: 1px solid var(--color-border, #2a2a3a);
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
	}

	.cancel-btn:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-text-primary, #e8e8ed);
	}

	.icon-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		border: none;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
		flex-shrink: 0;
	}

	.icon-btn:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-text-primary, #e8e8ed);
	}

	/* Experiment cards */
	.experiment-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.experiment-card {
		padding: 10px;
		background: var(--color-bg-secondary, #12121a);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
	}

	.exp-header {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--color-text-secondary, #8888a0);
		margin-bottom: 8px;
	}

	.exp-name {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.status-badge {
		font-size: 9px;
		font-weight: 700;
		padding: 1px 6px;
		border-radius: 3px;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	.badge-draft {
		background: rgba(255, 255, 255, 0.06);
		color: var(--color-text-secondary, #8888a0);
	}

	.badge-running {
		background: rgba(59, 130, 246, 0.15);
		color: #3b82f6;
	}

	.badge-completed {
		background: rgba(34, 197, 94, 0.15);
		color: #22c55e;
	}

	.exp-date {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.6;
		margin-left: auto;
	}

	.variants-list {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.variant-item {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.variant-name {
		font-size: 11px;
		color: var(--color-text-primary, #e8e8ed);
		min-width: 80px;
		flex-shrink: 0;
	}

	.traffic-bar-container {
		flex: 1;
		height: 4px;
		background: var(--color-bg-primary, #0a0a12);
		border-radius: 2px;
		overflow: hidden;
	}

	.traffic-bar {
		height: 100%;
		background: var(--color-accent, #ff6b35);
		border-radius: 2px;
		transition: width 0.3s ease;
	}

	.variant-traffic {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		min-width: 28px;
		text-align: right;
		flex-shrink: 0;
	}
</style>
