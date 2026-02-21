<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { scale } from 'svelte/transition';
	import GitMerge from 'lucide-svelte/icons/git-merge';
	import CheckCircle2 from 'lucide-svelte/icons/check-circle-2';
	import AlertCircle from 'lucide-svelte/icons/alert-circle';

	let { data } = $props();

	let execState = $derived((data._executionState as string) ?? 'idle');
	let showComplete = $state(false);

	$effect(() => {
		if (execState === 'complete') {
			showComplete = true;
			const timer = setTimeout(() => { showComplete = false; }, 3000);
			return () => clearTimeout(timer);
		} else {
			showComplete = false;
		}
	});
</script>

<div
	class="bp-node"
	class:exec-running={execState === 'running'}
	class:exec-complete={execState === 'complete'}
	class:exec-error={execState === 'error'}
>
	<div class="bp-header">
		<GitMerge size={12} />
		<span class="bp-title">{data.label || 'Fan In'}</span>
		{#if showComplete}
			<span class="bp-state" transition:scale={{ duration: 200, start: 0.6 }}><CheckCircle2 size={12} /></span>
		{/if}
		{#if execState === 'error'}
			<span class="bp-state bp-state-error"><AlertCircle size={12} /></span>
		{/if}
	</div>
	<div class="bp-body">
		<div class="bp-pins-multi">
			<div class="bp-pin-col-left">
				<div class="bp-pin-in"><span class="bp-dot"></span><span class="bp-pin-label">In 1</span></div>
				<div class="bp-pin-in"><span class="bp-dot"></span><span class="bp-pin-label">In 2</span></div>
			</div>
			<div class="bp-pin-col-right">
				<div class="bp-pin-out"><span class="bp-pin-label">Out</span><span class="bp-dot"></span></div>
			</div>
		</div>
		{#if data.merge_expression}
			<div class="bp-prop"><span class="bp-key">merge</span><span class="bp-val">{data.merge_expression}</span></div>
		{/if}
		{#if data.merge_timeout}
			<div class="bp-prop"><span class="bp-key">timeout</span><span class="bp-val">{data.merge_timeout}s</span></div>
		{/if}
	</div>
	<Handle type="target" position={Position.Left} id="in-1" style="top: 33%;" />
	<Handle type="target" position={Position.Left} id="in-2" style="top: 66%;" />
	<Handle type="source" position={Position.Right} />
</div>

<style>
	.bp-node {
		min-width: 200px;
		max-width: 260px;
		border-radius: 8px;
		overflow: hidden;
		box-shadow: 0 4px 16px rgba(100, 116, 139, 0.12), 0 0 0 1px rgba(100, 116, 139, 0.2);
		transition: box-shadow 0.3s ease;
		position: relative;
		font-family: var(--font-sans, system-ui, sans-serif);
	}
	.bp-node.exec-running { box-shadow: none; }
	.bp-node.exec-running::after {
		content: '';
		position: absolute;
		inset: -2px;
		border-radius: 10px;
		padding: 2px;
		background: conic-gradient(from 0deg, transparent 0%, #64748b 30%, transparent 60%);
		-webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		-webkit-mask-composite: xor;
		mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		mask-composite: exclude;
		animation: spin-border 1.2s linear infinite;
		pointer-events: none;
	}
	.bp-node.exec-complete { box-shadow: 0 0 16px rgba(34, 197, 94, 0.4), 0 0 0 1px rgba(34, 197, 94, 0.5); }
	.bp-node.exec-error { box-shadow: 0 0 16px rgba(239, 68, 68, 0.4), 0 0 0 1px rgba(239, 68, 68, 0.5); }
	@keyframes spin-border { to { transform: rotate(360deg); } }

	.bp-header {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 0 10px;
		height: 32px;
		background: linear-gradient(135deg, #64748b 0%, color-mix(in srgb, #64748b 70%, #000) 100%);
		color: white;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.bp-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.bp-state { margin-left: auto; display: flex; align-items: center; color: var(--color-success, #22c55e); }
	.bp-state-error { color: var(--color-error, #ef4444); }

	.bp-body {
		background: var(--color-bg-elevated, #1a1a26);
		padding: 8px 0;
	}

	.bp-pins-multi {
		display: flex;
		justify-content: space-between;
		padding: 0 10px;
		margin-bottom: 6px;
	}

	.bp-pin-col-left {
		display: flex;
		flex-direction: column;
		justify-content: center;
		gap: 6px;
	}

	.bp-pin-col-right {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		justify-content: center;
		gap: 6px;
	}

	.bp-pin-in, .bp-pin-out { display: flex; align-items: center; gap: 4px; font-size: 9px; color: var(--color-text-muted); }
	.bp-dot { width: 6px; height: 6px; border-radius: 50%; background: #64748b; flex-shrink: 0; }

	.bp-prop {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		padding: 2px 10px;
		gap: 8px;
	}
	.bp-key { font-size: 10px; color: var(--color-text-muted); font-family: var(--font-mono, monospace); white-space: nowrap; }
	.bp-val {
		font-size: 10px;
		color: var(--color-text-secondary);
		font-family: var(--font-mono, monospace);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 140px;
		text-align: right;
	}
</style>
