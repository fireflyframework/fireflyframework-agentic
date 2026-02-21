<script lang="ts">
	import { Rocket, Copy, Download, Play, RefreshCw, Check } from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { getGraphSnapshot } from '$lib/stores/pipeline';
	import { addToast } from '$lib/stores/notifications';

	let loading = $state(false);
	let generatedCode = $state('');
	let copied = $state(false);

	async function generateCode() {
		loading = true;
		generatedCode = '';
		try {
			const graph = getGraphSnapshot();
			const result = await api.codegen.smith(graph);
			generatedCode = result.code;
			addToast('Code generated successfully', 'success');
		} catch {
			addToast('Failed to generate code', 'error');
		} finally {
			loading = false;
		}
	}

	async function copyCode() {
		if (!generatedCode) return;
		try {
			await navigator.clipboard.writeText(generatedCode);
			copied = true;
			addToast('Copied to clipboard', 'info');
			setTimeout(() => (copied = false), 2000);
		} catch {
			addToast('Failed to copy', 'error');
		}
	}

	function downloadCode() {
		if (!generatedCode) return;
		const blob = new Blob([generatedCode], { type: 'text/x-python' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = 'pipeline.py';
		a.click();
		URL.revokeObjectURL(url);
		addToast('Download started', 'info');
	}
</script>

<div class="panel">
	<div class="header">
		<span class="title">Deploy / Export</span>
		<div class="header-actions">
			{#if generatedCode}
				<button class="action-btn text-btn" onclick={copyCode} title="Copy code">
					{#if copied}
						<Check size={12} />
						Copied
					{:else}
						<Copy size={12} />
						Copy
					{/if}
				</button>
				<button class="action-btn text-btn" onclick={downloadCode} title="Download as .py">
					<Download size={12} />
					Download
				</button>
			{/if}
			<button class="export-btn" onclick={generateCode} disabled={loading}>
				{#if loading}
					<RefreshCw size={12} />
					Generating...
				{:else}
					<Rocket size={12} />
					Export as Python
				{/if}
			</button>
		</div>
	</div>

	<div class="content">
		{#if generatedCode}
			<div class="code-container">
				<pre class="code-block"><code>{generatedCode}</code></pre>
			</div>
		{:else if loading}
			<div class="empty-state">
				<RefreshCw size={16} />
				<span>Generating Python code...</span>
			</div>
		{:else}
			<div class="empty-state">
				<Rocket size={16} />
				<span>Click "Export as Python" to generate deployable code from your pipeline.</span>
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
		gap: 6px;
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
		background: oklch(from var(--color-text-primary) l c h / 5%);
		color: var(--color-text-primary, #e8e8ed);
	}

	.text-btn {
		width: auto;
		gap: 5px;
		padding: 0 8px;
		font-size: 11px;
		font-weight: 500;
	}

	.export-btn {
		display: flex;
		align-items: center;
		gap: 5px;
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

	.export-btn:hover:not(:disabled) {
		filter: brightness(1.1);
	}

	.export-btn:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.content {
		flex: 1;
		overflow: hidden;
		display: flex;
		flex-direction: column;
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

	.code-container {
		flex: 1;
		overflow: auto;
	}

	.code-container::-webkit-scrollbar {
		width: 6px;
		height: 6px;
	}

	.code-container::-webkit-scrollbar-track {
		background: transparent;
	}

	.code-container::-webkit-scrollbar-thumb {
		background: var(--color-border, #2a2a3a);
		border-radius: 3px;
	}

	.code-block {
		margin: 0;
		padding: 12px;
		background: var(--color-bg-secondary, #12121a);
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		font-size: 12px;
		line-height: 1.6;
		color: var(--color-text-primary, #e8e8ed);
		white-space: pre;
		tab-size: 4;
		min-height: 100%;
		box-sizing: border-box;
	}

	.code-block code {
		font-family: inherit;
	}
</style>
