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
	<!-- Header -->
	<div class="tool-header">
		<div class="header-row">
			<span class="status-dot"
				class:dot-idle={execState === 'idle'}
				class:dot-running={execState === 'running'}
				class:dot-error={execState === 'error'}
				class:dot-complete={execState === 'complete' || showComplete}
			></span>
			<div class="tool-icon-wrap">
				<Wrench size={13} />
			</div>
			<span class="tool-title">{data.label || 'Tool'}</span>
			{#if showComplete}
				<span class="state-icon" transition:scale={{ duration: 200, start: 0.6 }}>
					<CheckCircle2 size={12} />
				</span>
			{/if}
			{#if execState === 'error'}
				<span class="state-icon state-error">
					<AlertCircle size={12} />
				</span>
			{/if}
		</div>
	</div>

	<!-- Body -->
	<div class="tool-body">
		<div class="pins-row">
			<div class="pin pin-in"><span class="pin-dot"></span><span class="pin-label">Exec In</span></div>
			<div class="pin pin-out"><span class="pin-label">Exec Out</span><span class="pin-dot"></span></div>
		</div>

		{#if data.tool_name}
			<div class="prop-row"><span class="prop-key">tool</span><span class="prop-val">{data.tool_name}</span></div>
		{/if}
		{#if data.description}
			<div class="tool-description">{String(data.description).slice(0, 60)}{String(data.description).length > 60 ? '\u2026' : ''}</div>
		{/if}
		{#if data.timeout}
			<div class="prop-row"><span class="prop-key">timeout</span><span class="prop-val">{data.timeout}s</span></div>
		{/if}
	</div>

	<Handle type="target" position={Position.Left} />
	<Handle type="source" position={Position.Right} />
</div>

<style>
	.tool-node {
		width: 180px;
		border-radius: 10px;
		overflow: hidden;
		box-shadow:
			0 4px 20px rgba(139, 92, 246, 0.10),
			0 0 0 1px rgba(139, 92, 246, 0.18);
		transition: box-shadow 0.3s ease;
		position: relative;
		font-family: var(--font-sans, system-ui, sans-serif);
	}

	.tool-node.exec-running {
		box-shadow: none;
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
		animation: tool-spin 1.2s linear infinite;
		pointer-events: none;
	}
	.tool-node.exec-complete {
		box-shadow: 0 0 20px rgba(34, 197, 94, 0.35), 0 0 0 1px rgba(34, 197, 94, 0.45);
	}
	.tool-node.exec-error {
		box-shadow: 0 0 20px rgba(239, 68, 68, 0.35), 0 0 0 1px rgba(239, 68, 68, 0.45);
	}
	@keyframes tool-spin {
		to { transform: rotate(360deg); }
	}

	/* --- Header --- */
	.tool-header {
		background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
		padding: 7px 10px;
	}

	.tool-node.exec-running .tool-header {
		background: linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%);
	}
	.tool-node.exec-error .tool-header {
		background: linear-gradient(135deg, #8b5cf6 0%, #9333ea 50%, #ef4444 100%);
	}

	.header-row {
		display: flex;
		align-items: center;
		gap: 5px;
		color: #fff;
	}

	.tool-icon-wrap {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		background: rgba(255, 255, 255, 0.15);
		border-radius: 5px;
		flex-shrink: 0;
	}

	.tool-title {
		flex: 1;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.02em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	/* Status dot */
	.status-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		flex-shrink: 0;
		transition: background 0.2s ease;
	}
	.dot-idle {
		background: rgba(255, 255, 255, 0.3);
	}
	.dot-running {
		background: #22c55e;
		animation: pulse-dot 1s ease-in-out infinite;
	}
	.dot-error {
		background: #ef4444;
	}
	.dot-complete {
		background: #22c55e;
	}
	@keyframes pulse-dot {
		0%, 100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.5; transform: scale(0.75); }
	}

	.state-icon {
		display: flex;
		align-items: center;
		color: #22c55e;
	}
	.state-error {
		color: #ef4444;
	}

	/* --- Body --- */
	.tool-body {
		background: #1a1a26;
		padding: 8px 0 6px;
	}

	.pins-row {
		display: flex;
		justify-content: space-between;
		padding: 0 10px;
		margin-bottom: 6px;
	}
	.pin {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: 9px;
		color: #8888a0;
		transition: color 0.15s ease;
	}
	.pin:hover {
		color: #b0b0c8;
	}
	.pin-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: #8b5cf6;
		transition: transform 0.15s ease, box-shadow 0.15s ease;
	}
	.pin:hover .pin-dot {
		transform: scale(1.4);
		box-shadow: 0 0 6px rgba(139, 92, 246, 0.5);
	}

	.prop-row {
		display: flex;
		justify-content: space-between;
		padding: 2px 10px;
		font-size: 10px;
	}
	.prop-key {
		color: #6a6a80;
		font-family: 'JetBrains Mono', monospace;
	}
	.prop-val {
		color: #a0a0b8;
		font-family: 'JetBrains Mono', monospace;
		text-overflow: ellipsis;
		overflow: hidden;
		white-space: nowrap;
		max-width: 100px;
		text-align: right;
	}

	.tool-description {
		font-size: 10px;
		color: #8888a0;
		padding: 2px 10px 4px;
		line-height: 1.35;
	}
</style>
