<script lang="ts">
	import { Trash2 } from 'lucide-svelte';
	import { executionEvents } from '$lib/stores/execution';
	import type { ExecutionEvent } from '$lib/types/graph';

	let scrollContainer: HTMLDivElement | undefined = $state();
	let prevEventCount = $state(0);

	// Auto-scroll to bottom when new events arrive
	$effect(() => {
		const events = $executionEvents;
		if (events.length > prevEventCount && scrollContainer) {
			// Use tick-like delay to let DOM update
			requestAnimationFrame(() => {
				if (scrollContainer) {
					scrollContainer.scrollTop = scrollContainer.scrollHeight;
				}
			});
		}
		prevEventCount = events.length;
	});

	function clearEvents() {
		executionEvents.set([]);
	}

	function formatTimestamp(iso: string): string {
		const d = new Date(iso);
		const h = String(d.getHours()).padStart(2, '0');
		const m = String(d.getMinutes()).padStart(2, '0');
		const s = String(d.getSeconds()).padStart(2, '0');
		const ms = String(d.getMilliseconds()).padStart(3, '0');
		return `${h}:${m}:${s}.${ms}`;
	}

	function badgeClass(type: ExecutionEvent['type']): string {
		switch (type) {
			case 'node_start':
				return 'badge-info';
			case 'node_complete':
			case 'pipeline_complete':
			case 'pipeline_result':
				return 'badge-success';
			case 'node_error':
				return 'badge-error';
			case 'node_skip':
				return 'badge-warning';
			default:
				return '';
		}
	}

	function badgeLabel(type: ExecutionEvent['type']): string {
		switch (type) {
			case 'node_start':
				return 'START';
			case 'node_complete':
				return 'DONE';
			case 'node_error':
				return 'ERROR';
			case 'node_skip':
				return 'SKIP';
			case 'pipeline_complete':
				return 'COMPLETE';
			case 'pipeline_result':
				return 'RESULT';
			default:
				return type;
		}
	}

	function extraInfo(event: ExecutionEvent): string {
		if (event.type === 'node_complete' && event.latency_ms != null) {
			return `${event.latency_ms}ms`;
		}
		if (event.type === 'node_error' && event.error) {
			return event.error;
		}
		if (event.type === 'pipeline_complete' && event.duration_ms != null) {
			return `Total: ${event.duration_ms}ms`;
		}
		return '';
	}
</script>

<div class="console-tab">
	<div class="console-toolbar">
		<span class="event-count">{$executionEvents.length} events</span>
		<button class="toolbar-btn" onclick={clearEvents} title="Clear console">
			<Trash2 size={13} />
		</button>
	</div>

	<div class="console-output" bind:this={scrollContainer}>
		{#if $executionEvents.length === 0}
			<div class="empty-state">
				<span class="empty-text">No execution events yet. Run your pipeline to see logs here.</span>
			</div>
		{:else}
			{#each $executionEvents as event, i (i)}
				{@const extra = extraInfo(event)}
				<div class="log-line">
					<span class="log-timestamp">{formatTimestamp(event.timestamp ?? '')}</span>
					<span class="log-badge {badgeClass(event.type)}">{badgeLabel(event.type)}</span>
					{#if event.node_id}
						<span class="log-node">{event.node_id}</span>
					{/if}
					{#if event.pipeline_name}
						<span class="log-pipeline">{event.pipeline_name}</span>
					{/if}
					{#if extra}
						<span class="log-extra">{extra}</span>
					{/if}
				</div>
			{/each}
		{/if}
	</div>
</div>

<style>
	.console-tab {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	.console-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 12px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
	}

	.event-count {
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
	}

	.toolbar-btn {
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

	.toolbar-btn:hover {
		background: oklch(from var(--color-text-primary) l c h / 5%);
		color: var(--color-text-primary, #e8e8ed);
	}

	.console-output {
		flex: 1;
		overflow-y: auto;
		padding: 8px 12px;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		font-size: 11px;
		line-height: 1.6;
	}

	.empty-state {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		padding: 24px;
	}

	.empty-text {
		color: var(--color-text-secondary, #8888a0);
		font-size: 12px;
	}

	.log-line {
		display: flex;
		align-items: baseline;
		gap: 8px;
		padding: 2px 0;
		white-space: nowrap;
	}

	.log-timestamp {
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.6;
		flex-shrink: 0;
	}

	.log-badge {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.05em;
		padding: 1px 6px;
		border-radius: 3px;
		flex-shrink: 0;
	}

	.badge-info {
		background: rgba(59, 130, 246, 0.15);
		color: var(--color-info, #3b82f6);
	}

	.badge-success {
		background: rgba(34, 197, 94, 0.15);
		color: var(--color-success, #22c55e);
	}

	.badge-error {
		background: rgba(239, 68, 68, 0.15);
		color: var(--color-error, #ef4444);
	}

	.badge-warning {
		background: rgba(245, 158, 11, 0.15);
		color: var(--color-warning, #f59e0b);
	}

	.log-node {
		color: var(--color-accent, #ff6b35);
		font-weight: 500;
		flex-shrink: 0;
	}

	.log-pipeline {
		color: var(--color-text-secondary, #8888a0);
		flex-shrink: 0;
	}

	.log-extra {
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.8;
		overflow: hidden;
		text-overflow: ellipsis;
	}
</style>
