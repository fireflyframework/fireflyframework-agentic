<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { scale } from 'svelte/transition';
	import Bot from 'lucide-svelte/icons/bot';
	import Eye from 'lucide-svelte/icons/eye';
	import Settings from 'lucide-svelte/icons/settings';
	import CheckCircle2 from 'lucide-svelte/icons/check-circle-2';
	import AlertCircle from 'lucide-svelte/icons/alert-circle';

	let { data } = $props();

	let execState = $derived((data._executionState as string) ?? 'idle');
	let hasMultimodal = $derived(!!(data.multimodal as Record<string, unknown>)?.vision_enabled);
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
	class="agent-node"
	class:exec-running={execState === 'running'}
	class:exec-complete={execState === 'complete'}
	class:exec-error={execState === 'error'}
>
	<!-- Header -->
	<div class="agent-header">
		<div class="header-top-row">
			<div class="header-badges">
				{#if data.model}
					<span class="model-badge">{data.model}</span>
				{/if}
				{#if hasMultimodal}
					<span class="multimodal-badge" title="Multimodal enabled">
						<Eye size={10} />
					</span>
				{/if}
			</div>
			<span class="settings-icon">
				<Settings size={11} />
			</span>
		</div>
		<div class="header-main-row">
			<span class="status-dot"
				class:dot-idle={execState === 'idle'}
				class:dot-running={execState === 'running'}
				class:dot-error={execState === 'error'}
				class:dot-complete={execState === 'complete' || showComplete}
			></span>
			<Bot size={14} />
			<span class="agent-title">{data.label || 'Agent'}</span>
			{#if showComplete}
				<span class="state-icon" transition:scale={{ duration: 200, start: 0.6 }}>
					<CheckCircle2 size={13} />
				</span>
			{/if}
			{#if execState === 'error'}
				<span class="state-icon state-error">
					<AlertCircle size={13} />
				</span>
			{/if}
		</div>
	</div>

	<!-- Body -->
	<div class="agent-body">
		<!-- Pins row -->
		<div class="pins-row">
			<div class="pin pin-in"><span class="pin-dot"></span><span class="pin-label">Exec In</span></div>
			<div class="pin pin-out"><span class="pin-label">Exec Out</span><span class="pin-dot"></span></div>
		</div>

		{#if data.description}
			<div class="description-text">{String(data.description).slice(0, 80)}{String(data.description).length > 80 ? '\u2026' : ''}</div>
		{/if}

		{#if data.instructions}
			<div class="instructions-section">
				<span class="section-label">Instructions</span>
				<p class="instructions-text">{data.instructions}</p>
			</div>
		{/if}
	</div>

	<Handle type="target" position={Position.Left} />
	<Handle type="source" position={Position.Right} />
</div>

<style>
	.agent-node {
		width: 220px;
		border-radius: 10px;
		overflow: hidden;
		box-shadow:
			0 4px 20px rgba(99, 102, 241, 0.10),
			0 0 0 1px rgba(99, 102, 241, 0.18);
		transition: box-shadow 0.3s ease;
		position: relative;
		font-family: var(--font-sans, system-ui, sans-serif);
	}

	.agent-node.exec-running {
		box-shadow: none;
	}
	.agent-node.exec-running::after {
		content: '';
		position: absolute;
		inset: -2px;
		border-radius: 12px;
		padding: 2px;
		background: conic-gradient(
			from 0deg,
			transparent 0%,
			#6366f1 30%,
			transparent 60%
		);
		-webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		-webkit-mask-composite: xor;
		mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		mask-composite: exclude;
		animation: agent-spin 1.2s linear infinite;
		pointer-events: none;
	}
	.agent-node.exec-complete {
		box-shadow: 0 0 20px rgba(34, 197, 94, 0.35), 0 0 0 1px rgba(34, 197, 94, 0.45);
	}
	.agent-node.exec-error {
		box-shadow: 0 0 20px rgba(239, 68, 68, 0.35), 0 0 0 1px rgba(239, 68, 68, 0.45);
	}
	@keyframes agent-spin {
		to { transform: rotate(360deg); }
	}

	/* --- Header --- */
	.agent-header {
		background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
		padding: 6px 10px 8px;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.agent-node.exec-running .agent-header {
		background: linear-gradient(135deg, #6366f1 0%, #818cf8 100%);
	}
	.agent-node.exec-error .agent-header {
		background: linear-gradient(135deg, #6366f1 0%, #7c3aed 50%, #ef4444 100%);
	}

	.header-top-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		min-height: 16px;
	}

	.header-badges {
		display: flex;
		align-items: center;
		gap: 4px;
		min-width: 0;
	}

	.multimodal-badge {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 18px;
		height: 14px;
		border-radius: 7px;
		background: rgba(255, 255, 255, 0.12);
		color: rgba(255, 255, 255, 0.7);
		flex-shrink: 0;
	}

	.model-badge {
		font-size: 9px;
		font-weight: 600;
		color: rgba(255, 255, 255, 0.7);
		background: rgba(255, 255, 255, 0.12);
		padding: 1px 6px;
		border-radius: 8px;
		letter-spacing: 0.02em;
		line-height: 14px;
		text-overflow: ellipsis;
		overflow: hidden;
		white-space: nowrap;
		max-width: 140px;
	}

	.settings-icon {
		color: rgba(255, 255, 255, 0.35);
		display: flex;
		align-items: center;
		cursor: pointer;
		transition: color 0.15s ease;
	}
	.settings-icon:hover {
		color: rgba(255, 255, 255, 0.7);
	}

	.header-main-row {
		display: flex;
		align-items: center;
		gap: 6px;
		color: #fff;
	}

	.agent-title {
		flex: 1;
		font-size: 12px;
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
	.agent-body {
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
		background: #6366f1;
		transition: transform 0.15s ease, box-shadow 0.15s ease;
	}
	.pin:hover .pin-dot {
		transform: scale(1.4);
		box-shadow: 0 0 6px rgba(99, 102, 241, 0.5);
	}

	.description-text {
		font-size: 10px;
		color: #a0a0b8;
		padding: 2px 10px 4px;
		line-height: 1.4;
	}

	.instructions-section {
		margin: 4px 8px 2px;
		padding: 5px 7px;
		background: rgba(99, 102, 241, 0.04);
		border: 1px solid rgba(99, 102, 241, 0.08);
		border-radius: 5px;
	}

	.section-label {
		font-size: 8px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #6366f1;
		opacity: 0.6;
	}

	.instructions-text {
		font-size: 10px;
		color: #7a7a94;
		font-family: 'JetBrains Mono', monospace;
		line-height: 1.35;
		margin: 2px 0 0;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
</style>
