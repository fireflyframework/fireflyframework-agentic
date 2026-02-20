<script lang="ts">
	import { Rocket, FileCode, Container, Globe, Cloud, ArrowRight, Clock, X, Copy, Check } from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { getGraphSnapshot } from '$lib/stores/pipeline';

	interface DeployTarget {
		name: string;
		description: string;
		icon: typeof Container;
		action: string;
		disabled: boolean;
	}

	const deployTargets: DeployTarget[] = [
		{
			name: 'Python Script',
			description: 'Generate a standalone Python script from your pipeline',
			icon: FileCode,
			action: 'Generate',
			disabled: false
		},
		{
			name: 'Docker Container',
			description: 'Generate a Dockerfile for your pipeline',
			icon: Container,
			action: 'Coming Soon',
			disabled: true
		},
		{
			name: 'REST API',
			description: 'Deploy as a FastAPI endpoint',
			icon: Globe,
			action: 'Coming Soon',
			disabled: true
		},
		{
			name: 'Cloud Function',
			description: 'Deploy to AWS Lambda / GCP Cloud Functions',
			icon: Cloud,
			action: 'Coming Soon',
			disabled: true
		}
	];

	let showCodeModal = $state(false);
	let generatedCode = $state('');
	let generating = $state(false);
	let generateError = $state('');
	let copied = $state(false);

	async function handleGenerate(target: DeployTarget) {
		if (target.disabled || target.name !== 'Python Script') return;

		generating = true;
		generateError = '';

		try {
			const graph = getGraphSnapshot();
			const result = await api.codegen.toCode(graph);
			generatedCode = result.code;
			showCodeModal = true;
		} catch (err) {
			generateError = err instanceof Error ? err.message : 'Failed to generate code';
		} finally {
			generating = false;
		}
	}

	async function copyCode() {
		await navigator.clipboard.writeText(generatedCode);
		copied = true;
		setTimeout(() => { copied = false; }, 2000);
	}
</script>

<div class="page">
	<div class="page-header">
		<div class="page-title">
			<Rocket size={20} class="text-accent" />
			<h1>Deploy</h1>
		</div>
	</div>

	<div class="page-content">
		{#if generateError}
			<div class="error-banner">
				{generateError}
				<button class="error-dismiss" onclick={() => generateError = ''}>
					<X size={14} />
				</button>
			</div>
		{/if}

		<!-- Deployment Targets -->
		<div class="section">
			<h2 class="section-title">Deployment Targets</h2>
			<div class="targets-grid">
				{#each deployTargets as target}
					<div class="target-card" class:disabled={target.disabled}>
						<div class="target-icon">
							<target.icon size={28} />
						</div>
						<div class="target-info">
							<h3 class="target-name">{target.name}</h3>
							<p class="target-description">{target.description}</p>
						</div>
						<div class="target-action">
							{#if target.disabled}
								<span class="coming-soon-badge">
									<Clock size={12} />
									Coming Soon
								</span>
							{:else}
								<button class="btn-secondary" disabled={generating} onclick={() => handleGenerate(target)}>
									{#if generating}
										Generating...
									{:else}
										{target.action}
										<ArrowRight size={14} />
									{/if}
								</button>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>

		<!-- Recent Deployments -->
		<div class="section">
			<h2 class="section-title">Recent Deployments</h2>
			<div class="empty-state-card">
				<div class="empty-icon">
					<Rocket size={36} />
				</div>
				<h3 class="empty-title">No deployments yet</h3>
				<p class="empty-subtitle">
					Generate a Python script above to export your pipeline
				</p>
			</div>
		</div>
	</div>
</div>

<!-- Code Generation Modal -->
{#if showCodeModal}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="modal-overlay" onclick={() => showCodeModal = false} onkeydown={(e) => e.key === 'Escape' && (showCodeModal = false)}>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="modal" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
			<div class="modal-header">
				<h2 class="modal-title">
					<FileCode size={18} />
					Generated Python Script
				</h2>
				<div class="modal-actions">
					<button class="btn-copy" onclick={copyCode}>
						{#if copied}
							<Check size={14} />
							Copied
						{:else}
							<Copy size={14} />
							Copy
						{/if}
					</button>
					<button class="btn-close" onclick={() => showCodeModal = false}>
						<X size={16} />
					</button>
				</div>
			</div>
			<div class="modal-body">
				<pre class="code-block"><code>{generatedCode}</code></pre>
			</div>
		</div>
	</div>
{/if}

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

	.page-content {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 32px;
	}

	/* Error Banner */
	.error-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 14px;
		background: oklch(from var(--color-error) l c h / 10%);
		border: 1px solid oklch(from var(--color-error) l c h / 30%);
		border-radius: 8px;
		color: var(--color-error);
		font-size: 13px;
	}

	.error-dismiss {
		background: none;
		border: none;
		color: var(--color-error);
		cursor: pointer;
		padding: 2px;
	}

	/* Section */
	.section {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.section-title {
		font-size: 14px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	/* Buttons */
	.btn-secondary {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 16px;
		background: transparent;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		color: var(--color-text-primary);
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		transition: border-color 0.15s;
	}

	.btn-secondary:hover:not(:disabled) {
		border-color: var(--color-accent);
	}

	.btn-secondary:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	/* Targets Grid */
	.targets-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
		gap: 16px;
	}

	.target-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 16px;
		padding: 28px 20px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		text-align: center;
		transition: border-color 0.15s;
	}

	.target-card:not(.disabled):hover {
		border-color: oklch(from var(--color-accent) l c h / 40%);
	}

	.target-card.disabled {
		opacity: 0.6;
	}

	.target-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 56px;
		height: 56px;
		border-radius: 14px;
		background: oklch(from var(--color-accent) l c h / 10%);
		color: var(--color-accent);
	}

	.target-info {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.target-name {
		font-size: 15px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	.target-description {
		font-size: 12px;
		color: var(--color-text-secondary);
		margin: 0;
		line-height: 1.5;
	}

	.target-action {
		margin-top: 4px;
	}

	.coming-soon-badge {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 6px 12px;
		border-radius: 6px;
		font-size: 11px;
		font-weight: 500;
		background: oklch(from var(--color-text-secondary) l c h / 10%);
		color: var(--color-text-secondary);
	}

	/* Empty State */
	.empty-state-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 40px 24px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		text-align: center;
		gap: 12px;
	}

	.empty-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 64px;
		height: 64px;
		border-radius: 14px;
		background: oklch(from var(--color-text-secondary) l c h / 8%);
		color: var(--color-text-secondary);
	}

	.empty-title {
		font-size: 15px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	.empty-subtitle {
		font-size: 13px;
		color: var(--color-text-secondary);
		margin: 0;
		max-width: 360px;
		line-height: 1.5;
	}

	/* Code Modal */
	.modal-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
		backdrop-filter: blur(4px);
	}

	.modal {
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		width: 90%;
		max-width: 720px;
		max-height: 80vh;
		display: flex;
		flex-direction: column;
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
	}

	.modal-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 20px;
		border-bottom: 1px solid var(--color-border);
	}

	.modal-title {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 15px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	.modal-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.btn-copy {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 6px 12px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		color: var(--color-text-secondary);
		font-size: 12px;
		cursor: pointer;
		transition: border-color 0.15s, color 0.15s;
	}

	.btn-copy:hover {
		border-color: var(--color-accent);
		color: var(--color-text-primary);
	}

	.btn-close {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		background: none;
		border: none;
		color: var(--color-text-secondary);
		cursor: pointer;
		border-radius: 6px;
		transition: background 0.15s;
	}

	.btn-close:hover {
		background: var(--color-bg-elevated);
		color: var(--color-text-primary);
	}

	.modal-body {
		flex: 1;
		overflow: auto;
		padding: 0;
	}

	.code-block {
		margin: 0;
		padding: 20px;
		background: var(--color-bg-primary);
		font-family: var(--font-mono);
		font-size: 13px;
		line-height: 1.6;
		color: var(--color-text-primary);
		white-space: pre;
		overflow-x: auto;
		tab-size: 4;
	}
</style>
