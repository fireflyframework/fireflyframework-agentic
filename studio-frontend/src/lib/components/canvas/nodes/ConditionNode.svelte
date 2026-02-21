<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { scale } from 'svelte/transition';
	import GitBranch from 'lucide-svelte/icons/git-branch';
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
	class="cond-node"
	class:exec-running={execState === 'running'}
	class:exec-complete={execState === 'complete'}
	class:exec-error={execState === 'error'}
>
	<!-- Hexagonal-style header -->
	<div class="cond-header">
		<div class="hex-accent"></div>
		<div class="header-content">
			<span class="status-dot"
				class:dot-idle={execState === 'idle'}
				class:dot-running={execState === 'running'}
				class:dot-error={execState === 'error'}
				class:dot-complete={execState === 'complete' || showComplete}
			></span>
			<GitBranch size={13} />
			<span class="cond-title">{data.label || 'Condition'}</span>
			{#if showComplete}
				<span class="state-icon" transition:scale={{ duration: 200, start: 0.6 }}><CheckCircle2 size={12} /></span>
			{/if}
			{#if execState === 'error'}
				<span class="state-icon state-error"><AlertCircle size={12} /></span>
			{/if}
		</div>
	</div>

	<!-- Body -->
	<div class="cond-body">
		<!-- Condition expression -->
		{#if data.condition}
			<div class="condition-expr">
				<code class="expr-code">{data.condition}</code>
			</div>
		{/if}

		{#if data.description}
			<div class="cond-description">{String(data.description).slice(0, 60)}{String(data.description).length > 60 ? '\u2026' : ''}</div>
		{/if}

		<!-- Branch pins -->
		<div class="branch-pins">
			<div class="branch-in">
				<span class="pin-dot dot-in"></span>
				<span class="pin-label">In</span>
			</div>
			<div class="branch-outputs">
				<div class="branch-out branch-true">
					<span class="pin-label label-true">True</span>
					<span class="pin-dot dot-true"></span>
				</div>
				<div class="branch-out branch-false">
					<span class="pin-label label-false">False</span>
					<span class="pin-dot dot-false"></span>
				</div>
			</div>
		</div>
	</div>

	<Handle type="target" position={Position.Left} />
	<Handle type="source" position={Position.Right} id="true" style="top: 35%;" />
	<Handle type="source" position={Position.Right} id="false" style="top: 65%;" />
</div>

<style>
	.cond-node {
		width: 200px;
		border-radius: 10px;
		overflow: hidden;
		box-shadow:
			0 4px 20px rgba(245, 158, 11, 0.10),
			0 0 0 1px rgba(245, 158, 11, 0.18);
		transition: box-shadow 0.3s ease;
		position: relative;
		font-family: var(--font-sans, system-ui, sans-serif);
	}

	.cond-node.exec-running { box-shadow: none; }
	.cond-node.exec-running::after {
		content: '';
		position: absolute;
		inset: -2px;
		border-radius: 12px;
		padding: 2px;
		background: conic-gradient(from 0deg, transparent 0%, #f59e0b 30%, transparent 60%);
		-webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		-webkit-mask-composite: xor;
		mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
		mask-composite: exclude;
		animation: spin-border 1.2s linear infinite;
		pointer-events: none;
	}
	.cond-node.exec-complete { box-shadow: 0 0 20px rgba(34, 197, 94, 0.35), 0 0 0 1px rgba(34, 197, 94, 0.45); }
	.cond-node.exec-error { box-shadow: 0 0 20px rgba(239, 68, 68, 0.35), 0 0 0 1px rgba(239, 68, 68, 0.45); }
	@keyframes spin-border { to { transform: rotate(360deg); } }

	/* --- Hexagonal header --- */
	.cond-header {
		position: relative;
		background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
		padding: 8px 10px;
		overflow: hidden;
	}

	.cond-node.exec-running .cond-header {
		background: linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%);
	}
	.cond-node.exec-error .cond-header {
		background: linear-gradient(135deg, #f59e0b 0%, #ea580c 50%, #ef4444 100%);
	}

	.hex-accent {
		position: absolute;
		top: -6px;
		right: -6px;
		width: 28px;
		height: 28px;
		background: rgba(255, 255, 255, 0.08);
		transform: rotate(45deg);
		border-radius: 4px;
	}

	.header-content {
		display: flex;
		align-items: center;
		gap: 5px;
		color: #fff;
		position: relative;
		z-index: 1;
	}

	.cond-title {
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
	.dot-idle { background: rgba(255, 255, 255, 0.3); }
	.dot-running { background: #22c55e; animation: pulse-dot 1s ease-in-out infinite; }
	.dot-error { background: #ef4444; }
	.dot-complete { background: #22c55e; }
	@keyframes pulse-dot {
		0%, 100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.5; transform: scale(0.75); }
	}

	.state-icon { display: flex; align-items: center; color: #22c55e; }
	.state-error { color: #ef4444; }

	/* --- Body --- */
	.cond-body {
		background: var(--color-bg-elevated, #1a1a26);
		padding: 8px 0 6px;
	}

	.condition-expr {
		margin: 0 8px 6px;
		padding: 5px 7px;
		background: rgba(245, 158, 11, 0.05);
		border: 1px solid rgba(245, 158, 11, 0.10);
		border-radius: 5px;
	}

	.expr-code {
		font-size: 10px;
		font-family: 'JetBrains Mono', monospace;
		color: #fbbf24;
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.cond-description {
		font-size: 10px;
		color: var(--color-text-muted);
		padding: 0 10px 4px;
		line-height: 1.35;
	}

	/* Branch pins */
	.branch-pins {
		display: flex;
		justify-content: space-between;
		padding: 4px 10px 0;
	}

	.branch-in {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: 9px;
		color: var(--color-text-muted);
		align-self: center;
	}

	.branch-outputs {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 8px;
	}

	.branch-out {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: 9px;
		transition: opacity 0.15s ease;
	}
	.branch-out:hover {
		opacity: 0.8;
	}

	.pin-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		flex-shrink: 0;
		transition: transform 0.15s ease, box-shadow 0.15s ease;
	}
	.branch-out:hover .pin-dot,
	.branch-in:hover .pin-dot {
		transform: scale(1.3);
	}

	.dot-in { background: #f59e0b; }
	.dot-true { background: #22c55e; box-shadow: 0 0 4px rgba(34, 197, 94, 0.3); }
	.dot-false { background: #ef4444; box-shadow: 0 0 4px rgba(239, 68, 68, 0.3); }

	.pin-label { color: var(--color-text-muted); }
	.label-true { color: #4ade80; font-weight: 600; }
	.label-false { color: #f87171; font-weight: 600; }
</style>
