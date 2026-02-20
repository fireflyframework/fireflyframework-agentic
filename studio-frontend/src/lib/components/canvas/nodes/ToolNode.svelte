<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { scale } from 'svelte/transition';
	import Wrench from 'lucide-svelte/icons/wrench';
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
	class="tool-node"
	class:exec-running={execState === 'running'}
	class:exec-complete={execState === 'complete'}
	class:exec-error={execState === 'error'}
>
	<div class="node-header">
		<div class="icon-wrapper tool-icon">
			<Wrench size={12} />
		</div>
		<span class="node-label">{data.label || 'Tool'}</span>
		{#if showComplete}
			<span class="state-icon state-complete" transition:scale={{ duration: 200, start: 0.6 }}>
				<CheckCircle2 size={12} />
			</span>
		{/if}
		{#if execState === 'error'}
			<span class="state-icon state-error">
				<AlertCircle size={12} />
			</span>
		{/if}
	</div>
	{#if data.description}
		<div class="node-detail">{data.description}</div>
	{/if}
	<Handle type="target" position={Position.Left} />
	<Handle type="source" position={Position.Right} />
</div>

<style>
	.tool-node {
		background: #1a1a26;
		border: 1px solid rgba(139, 92, 246, 0.3);
		border-radius: 10px;
		padding: 8px 12px;
		min-width: 140px;
		box-shadow: 0 4px 12px rgba(139, 92, 246, 0.05);
		transition: border-color 0.3s ease, box-shadow 0.3s ease;
		position: relative;
	}
	.tool-node.exec-running {
		border-color: transparent;
	}
	.tool-node.exec-running::after {
		content: '';
		position: absolute;
		inset: -2px;
		border-radius: 12px;
		padding: 2px;
		background: conic-gradient(
			from 0deg,
			transparent 0%,
			#8b5cf6 30%,
			transparent 60%
		);
		-webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		-webkit-mask-composite: xor;
		mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		mask-composite: exclude;
		animation: spin-border 1.2s linear infinite;
		pointer-events: none;
	}
	.tool-node.exec-complete {
		border-color: var(--color-success);
		box-shadow: 0 0 12px rgba(34, 197, 94, 0.3);
	}
	.tool-node.exec-error {
		border-color: var(--color-error);
		box-shadow: 0 0 12px rgba(239, 68, 68, 0.3);
	}
	@keyframes spin-border {
		to {
			transform: rotate(360deg);
		}
	}
	.node-header {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 4px;
	}
	.icon-wrapper {
		width: 20px;
		height: 20px;
		border-radius: 5px;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.tool-icon {
		background: rgba(139, 92, 246, 0.2);
		color: #8b5cf6;
	}
	.node-label {
		font-size: 11px;
		font-weight: 600;
		color: #e8e8ed;
	}
	.node-detail {
		font-size: 9px;
		color: #8888a0;
		font-family: 'JetBrains Mono', monospace;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.state-icon {
		margin-left: auto;
		display: flex;
		align-items: center;
	}
	.state-complete {
		color: var(--color-success);
	}
	.state-error {
		color: var(--color-error);
	}
</style>
