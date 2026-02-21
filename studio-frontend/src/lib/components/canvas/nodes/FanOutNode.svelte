<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { scale } from 'svelte/transition';
	import GitFork from 'lucide-svelte/icons/git-fork';
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
		<GitFork size={12} />
		<span class="bp-title">{data.label || 'Fan Out'}</span>
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
				<div class="bp-pin-in"><span class="bp-dot"></span><span class="bp-pin-label">In</span></div>
			</div>
			<div class="bp-pin-col-right">
				<div class="bp-pin-out"><span class="bp-pin-label">Out 1</span><span class="bp-dot"></span></div>
				<div class="bp-pin-out"><span class="bp-pin-label">Out 2</span><span class="bp-dot"></span></div>
			</div>
		</div>
		{#if data.split_expression}
			<div class="bp-prop"><span class="bp-key">split</span><span class="bp-val">{data.split_expression}</span></div>
		{/if}
		{#if data.max_concurrent}
			<div class="bp-prop"><span class="bp-key">max</span><span class="bp-val">{data.max_concurrent}</span></div>
		{/if}
	</div>
	<Handle type="target" position={Position.Left} />
	<Handle type="source" position={Position.Right} id="out-1" style="top: 33%;" />
	<Handle type="source" position={Position.Right} id="out-2" style="top: 66%;" />
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
		background: #1a1a26;
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
		gap: 6px;
	}

	.bp-pin-in, .bp-pin-out { display: flex; align-items: center; gap: 4px; font-size: 9px; color: #8888a0; }
	.bp-dot { width: 6px; height: 6px; border-radius: 50%; background: #64748b; flex-shrink: 0; }

	.bp-prop {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		padding: 2px 10px;
		gap: 8px;
	}
	.bp-key { font-size: 10px; color: #6a6a80; font-family: var(--font-mono, monospace); white-space: nowrap; }
	.bp-val {
		font-size: 10px;
		color: #a0a0b8;
		font-family: var(--font-mono, monospace);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 140px;
		text-align: right;
	}
</style>
