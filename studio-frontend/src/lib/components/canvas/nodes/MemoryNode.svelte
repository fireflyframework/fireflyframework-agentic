<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { scale } from 'svelte/transition';
	import Database from 'lucide-svelte/icons/database';
	import CheckCircle2 from 'lucide-svelte/icons/check-circle-2';
	import AlertCircle from 'lucide-svelte/icons/alert-circle';

	let { data } = $props();

	let execState = $derived((data._executionState as string) ?? 'idle');
	let showComplete = $state(false);

	$effect(() => {
		if (execState === 'complete') {
			showComplete = true;
			const timer = setTimeout(() => {
				showComplete = false;
			}, 3000);
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
		<Database size={12} />
		<span class="bp-title">{data.label || 'Memory'}</span>
		{#if showComplete}
			<span class="bp-state" transition:scale={{ duration: 200, start: 0.6 }}>
				<CheckCircle2 size={12} />
			</span>
		{/if}
		{#if execState === 'error'}
			<span class="bp-state bp-state-error">
				<AlertCircle size={12} />
			</span>
		{/if}
	</div>
	<div class="bp-body">
		<div class="bp-pins">
			<div class="bp-pin-in"><span class="bp-dot"></span><span class="bp-pin-label">Exec In</span></div>
			<div class="bp-pin-out"><span class="bp-pin-label">Exec Out</span><span class="bp-dot"></span></div>
		</div>
		{#if data.memory_action}
			<div class="bp-prop"><span class="bp-key">action</span><span class="bp-val">{data.memory_action}</span></div>
		{/if}
		{#if data.namespace}
			<div class="bp-prop"><span class="bp-key">namespace</span><span class="bp-val">{data.namespace}</span></div>
		{/if}
	</div>
	<Handle type="target" position={Position.Left} />
	<Handle type="source" position={Position.Right} />
</div>

<style>
	.bp-node {
		min-width: 200px;
		max-width: 260px;
		border-radius: 8px;
		overflow: hidden;
		box-shadow: 0 4px 16px rgba(6, 182, 212, 0.12), 0 0 0 1px rgba(6, 182, 212, 0.2);
		transition: box-shadow 0.3s ease;
		position: relative;
		font-family: var(--font-sans, system-ui, sans-serif);
	}
	.bp-node.exec-running {
		box-shadow: none;
	}
	.bp-node.exec-running::after {
		content: '';
		position: absolute;
		inset: -2px;
		border-radius: 10px;
		padding: 2px;
		background: conic-gradient(
			from 0deg,
			transparent 0%,
			#06b6d4 30%,
			transparent 60%
		);
		-webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		-webkit-mask-composite: xor;
		mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		mask-composite: exclude;
		animation: memory-spin 1.2s linear infinite;
		pointer-events: none;
	}
	.bp-node.exec-complete {
		box-shadow: 0 0 16px rgba(34, 197, 94, 0.4), 0 0 0 1px rgba(34, 197, 94, 0.5);
	}
	.bp-node.exec-error {
		box-shadow: 0 0 16px rgba(239, 68, 68, 0.4), 0 0 0 1px rgba(239, 68, 68, 0.5);
	}
	@keyframes memory-spin {
		to { transform: rotate(360deg); }
	}

	.bp-header {
		height: 32px;
		background: linear-gradient(135deg, #06b6d4 0%, #0891b2 100%);
		color: #fff;
		display: flex;
		flex-direction: row;
		align-items: center;
		gap: 6px;
		padding: 0 10px;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.bp-title {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.bp-state {
		display: flex;
		align-items: center;
		color: #22c55e;
	}
	.bp-state-error {
		color: #ef4444;
	}

	.bp-body {
		background: var(--color-bg-elevated, #1a1a26);
		padding: 8px 0;
	}
	.bp-pins {
		display: flex;
		justify-content: space-between;
		padding: 0 10px;
		margin-bottom: 6px;
	}
	.bp-pin-in,
	.bp-pin-out {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: 9px;
		color: var(--color-text-muted);
	}
	.bp-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: #06b6d4;
	}
	.bp-prop {
		display: flex;
		justify-content: space-between;
		padding: 2px 10px;
		font-size: 10px;
	}
	.bp-key {
		color: var(--color-text-muted);
		font-family: 'JetBrains Mono', monospace;
	}
	.bp-val {
		color: var(--color-text-secondary);
		font-family: 'JetBrains Mono', monospace;
		text-overflow: ellipsis;
		overflow: hidden;
		white-space: nowrap;
		max-width: 140px;
		text-align: right;
	}
</style>
