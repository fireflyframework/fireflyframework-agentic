<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { scale } from 'svelte/transition';
	import Download from 'lucide-svelte/icons/download';
	import Settings from 'lucide-svelte/icons/settings';
	import CheckCircle2 from 'lucide-svelte/icons/check-circle-2';
	import AlertCircle from 'lucide-svelte/icons/alert-circle';

	let { data } = $props();

	let execState = $derived((data._executionState as string) ?? 'idle');
	let destinationType = $derived((data.destination_type as string) ?? 'Response');
	let showComplete = $state(false);

	let configSummary = $derived(() => {
		switch (destinationType.toLowerCase()) {
			case 'response':
				return data.format ? `Format: ${data.format}` : 'Direct response';
			case 'queue':
				return data.queue_name ? `Queue: ${data.queue_name}` : 'Message queue';
			case 'webhook':
				return data.webhook_url ? `URL: ${data.webhook_url}` : 'Webhook delivery';
			case 'store':
				return data.store_path ? `Path: ${data.store_path}` : 'Persistent store';
			default:
				return 'Output destination';
		}
	});

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
	class="output-node"
	class:exec-running={execState === 'running'}
	class:exec-complete={execState === 'complete'}
	class:exec-error={execState === 'error'}
>
	<!-- Header -->
	<div class="output-header">
		<div class="header-top-row">
			<div class="header-badges">
				<span class="dest-badge">{destinationType}</span>
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
			<div class="icon-wrap">
				<Download size={14} />
			</div>
			<span class="output-title">{data.label || 'Output'}</span>
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
	<div class="output-body">
		<!-- Pins row: input only (sink node) -->
		<div class="pins-row">
			<div class="pin pin-in"><span class="pin-dot"></span><span class="pin-label">Exec In</span></div>
			<div class="pin-spacer"></div>
		</div>

		{#if data.description}
			<div class="description-text">{String(data.description).slice(0, 80)}{String(data.description).length > 80 ? '\u2026' : ''}</div>
		{/if}

		<div class="config-section">
			<span class="section-label">Destination Config</span>
			<p class="config-text">{configSummary()}</p>
		</div>
	</div>

	<!-- Input handle only (sink/exit node) -->
	<Handle type="target" position={Position.Left} />
</div>

<style>
	.output-node {
		width: 220px;
		border-radius: 10px;
		overflow: hidden;
		box-shadow:
			0 4px 20px rgba(59, 130, 246, 0.10),
			0 0 0 1px rgba(59, 130, 246, 0.18);
		transition: box-shadow 0.3s ease;
		position: relative;
		font-family: var(--font-sans, system-ui, sans-serif);
	}

	.output-node.exec-running {
		box-shadow: none;
	}
	.output-node.exec-running::after {
		content: '';
		position: absolute;
		inset: -2px;
		border-radius: 12px;
		padding: 2px;
		background: conic-gradient(
			from 0deg,
			transparent 0%,
			#3b82f6 30%,
			transparent 60%
		);
		-webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		-webkit-mask-composite: xor;
		mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		mask-composite: exclude;
		animation: output-spin 1.2s linear infinite;
		pointer-events: none;
	}
	.output-node.exec-complete {
		box-shadow: 0 0 20px rgba(34, 197, 94, 0.35), 0 0 0 1px rgba(34, 197, 94, 0.45);
	}
	.output-node.exec-error {
		box-shadow: 0 0 20px rgba(239, 68, 68, 0.35), 0 0 0 1px rgba(239, 68, 68, 0.45);
	}
	@keyframes output-spin {
		to { transform: rotate(360deg); }
	}

	/* --- Header --- */
	.output-header {
		background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
		padding: 6px 10px 8px;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.output-node.exec-running .output-header {
		background: linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%);
	}
	.output-node.exec-error .output-header {
		background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 50%, #ef4444 100%);
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

	.dest-badge {
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
		text-transform: capitalize;
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

	.icon-wrap {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		background: rgba(255, 255, 255, 0.15);
		border-radius: 6px;
		flex-shrink: 0;
	}

	.output-title {
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
	.output-body {
		background: #1a1a26;
		padding: 8px 0 6px;
	}

	.pins-row {
		display: flex;
		justify-content: space-between;
		padding: 0 10px;
		margin-bottom: 6px;
	}
	.pin-spacer {
		flex: 1;
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
		background: #3b82f6;
		transition: transform 0.15s ease, box-shadow 0.15s ease;
	}
	.pin:hover .pin-dot {
		transform: scale(1.4);
		box-shadow: 0 0 6px rgba(59, 130, 246, 0.5);
	}

	.description-text {
		font-size: 10px;
		color: #a0a0b8;
		padding: 2px 10px 4px;
		line-height: 1.4;
	}

	.config-section {
		margin: 4px 8px 2px;
		padding: 5px 7px;
		background: rgba(59, 130, 246, 0.04);
		border: 1px solid rgba(59, 130, 246, 0.08);
		border-radius: 5px;
	}

	.section-label {
		font-size: 8px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #3b82f6;
		opacity: 0.6;
	}

	.config-text {
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
