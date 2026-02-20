<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { scale } from 'svelte/transition';
	import CircleDot from 'lucide-svelte/icons/circle-dot';
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

<div class="condition-node">
	<div
		class="diamond"
		class:exec-running={execState === 'running'}
		class:exec-complete={execState === 'complete'}
		class:exec-error={execState === 'error'}
	>
		<div class="diamond-content">
			<div class="icon-wrapper condition-icon">
				<CircleDot size={12} />
			</div>
			<span class="node-label">{data.label || 'Condition'}</span>
			{#if showComplete}
				<span class="state-icon state-complete" transition:scale={{ duration: 200, start: 0.6 }}>
					<CheckCircle2 size={10} />
				</span>
			{/if}
			{#if execState === 'error'}
				<span class="state-icon state-error">
					<AlertCircle size={10} />
				</span>
			{/if}
		</div>
	</div>
	<Handle type="target" position={Position.Left} class="handle-left" />
	<Handle type="source" position={Position.Right} id="true" class="handle-true" style="top: 35%;" />
	<Handle type="source" position={Position.Right} id="false" class="handle-false" style="top: 65%;" />
	<span class="handle-label true-label">T</span>
	<span class="handle-label false-label">F</span>
</div>

<style>
	.condition-node {
		position: relative;
		min-width: 120px;
		min-height: 80px;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.diamond {
		background: #1a1a26;
		border: 1px solid rgba(136, 136, 160, 0.3);
		width: 100px;
		height: 100px;
		transform: rotate(45deg);
		display: flex;
		align-items: center;
		justify-content: center;
		box-shadow: 0 4px 12px rgba(136, 136, 160, 0.05);
		transition: border-color 0.3s ease, box-shadow 0.3s ease;
		position: relative;
	}
	.diamond.exec-running {
		border-color: transparent;
	}
	.diamond.exec-running::after {
		content: '';
		position: absolute;
		inset: -2px;
		padding: 2px;
		background: conic-gradient(
			from 0deg,
			transparent 0%,
			#8888a0 30%,
			transparent 60%
		);
		-webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		-webkit-mask-composite: xor;
		mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		mask-composite: exclude;
		animation: spin-border 1.2s linear infinite;
		pointer-events: none;
	}
	.diamond.exec-complete {
		border-color: var(--color-success);
		box-shadow: 0 0 12px rgba(34, 197, 94, 0.3);
	}
	.diamond.exec-error {
		border-color: var(--color-error);
		box-shadow: 0 0 12px rgba(239, 68, 68, 0.3);
	}
	@keyframes spin-border {
		to {
			transform: rotate(360deg);
		}
	}
	.diamond-content {
		transform: rotate(-45deg);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		white-space: nowrap;
	}
	.icon-wrapper {
		width: 20px;
		height: 20px;
		border-radius: 5px;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.condition-icon {
		background: rgba(136, 136, 160, 0.2);
		color: #8888a0;
	}
	.node-label {
		font-size: 10px;
		font-weight: 600;
		color: #e8e8ed;
	}
	.handle-label {
		position: absolute;
		font-size: 8px;
		font-weight: 700;
		font-family: 'JetBrains Mono', monospace;
		right: -4px;
	}
	.true-label {
		top: 25%;
		color: #22c55e;
	}
	.false-label {
		top: 58%;
		color: #ef4444;
	}
	.state-icon {
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
