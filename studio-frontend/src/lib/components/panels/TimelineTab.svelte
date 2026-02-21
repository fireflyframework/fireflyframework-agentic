<script lang="ts">
	import { Clock, Trash2, SkipBack, GitBranch, GitCompare, ChevronRight, ChevronDown } from 'lucide-svelte';
	import { checkpoints } from '$lib/stores/execution';
	import { addToast } from '$lib/stores/notifications';
	import { api } from '$lib/api/client';
	import type { Checkpoint } from '$lib/types/graph';
	import { onMount } from 'svelte';

	let selectedIndex: number | null = $state(null);
	let compareIndex: number | null = $state(null);
	let diffResult: { added: string[]; removed: string[]; changed: string[] } | null = $state(null);
	let timelineContainer: HTMLDivElement | undefined = $state();
	let prevCheckpointCount = $state(0);
	let expandedState = $state(true);
	let expandedInputs = $state(false);

	let selectedCheckpoint: Checkpoint | undefined = $derived(
		selectedIndex !== null ? $checkpoints.find((cp) => cp.index === selectedIndex) : undefined
	);

	let compareCheckpoint: Checkpoint | undefined = $derived(
		compareIndex !== null ? $checkpoints.find((cp) => cp.index === compareIndex) : undefined
	);

	// Auto-scroll to latest checkpoint when new ones arrive
	$effect(() => {
		const cps = $checkpoints;
		if (cps.length > prevCheckpointCount && timelineContainer) {
			requestAnimationFrame(() => {
				if (timelineContainer) {
					timelineContainer.scrollLeft = timelineContainer.scrollWidth;
				}
			});
		}
		prevCheckpointCount = cps.length;
	});

	// Fetch checkpoints on mount
	onMount(async () => {
		try {
			const data = await api.checkpoints.list();
			checkpoints.set(data);
		} catch {
			// API may not be available during development
		}
	});

	function handleCheckpointClick(cp: Checkpoint, event: MouseEvent) {
		if (event.shiftKey && selectedIndex !== null && selectedIndex !== cp.index) {
			compareIndex = cp.index;
			loadDiff();
		} else {
			selectedIndex = cp.index;
			compareIndex = null;
			diffResult = null;
		}
	}

	async function loadDiff() {
		if (selectedIndex === null || compareIndex === null) return;
		try {
			diffResult = await api.checkpoints.diff(selectedIndex, compareIndex);
		} catch {
			diffResult = null;
		}
	}

	async function handleClear() {
		try {
			await api.checkpoints.clear();
			checkpoints.set([]);
			selectedIndex = null;
			compareIndex = null;
			diffResult = null;
		} catch {
			// Clear locally anyway
			checkpoints.set([]);
			selectedIndex = null;
			compareIndex = null;
			diffResult = null;
		}
	}

	async function handleRewind() {
		if (!selectedCheckpoint || selectedIndex === null) return;
		try {
			await api.checkpoints.rewind(selectedIndex);
			// Trim local checkpoints to match rewound state
			checkpoints.update((cps) => cps.filter((cp) => cp.index <= selectedIndex!));
			compareIndex = null;
			diffResult = null;
			addToast(`Rewound to checkpoint #${selectedIndex}`, 'info');
		} catch {
			addToast('Failed to rewind checkpoint', 'error');
		}
	}

	async function handleFork() {
		if (!selectedCheckpoint || selectedIndex === null) return;
		try {
			const forked = await api.checkpoints.fork(selectedIndex, selectedCheckpoint.state);
			checkpoints.update((cps) => [...cps, forked]);
			selectedIndex = forked.index;
		} catch {
			// Fork failed silently
		}
	}

	function formatRelativeTime(timestamp: string): string {
		if (!timestamp) return '';
		const now = Date.now();
		const then = new Date(timestamp).getTime();
		const diffMs = now - then;
		const diffSec = Math.floor(diffMs / 1000);

		if (diffSec < 5) return 'just now';
		if (diffSec < 60) return `${diffSec}s ago`;
		const diffMin = Math.floor(diffSec / 60);
		if (diffMin < 60) return `${diffMin}m ago`;
		const diffHr = Math.floor(diffMin / 60);
		if (diffHr < 24) return `${diffHr}h ago`;
		return new Date(timestamp).toLocaleDateString();
	}

	function formatTimestamp(timestamp: string): string {
		if (!timestamp) return '';
		const d = new Date(timestamp);
		const h = String(d.getHours()).padStart(2, '0');
		const m = String(d.getMinutes()).padStart(2, '0');
		const s = String(d.getSeconds()).padStart(2, '0');
		return `${h}:${m}:${s}`;
	}

	function nodeColor(nodeId: string): string {
		if (nodeId.includes('agent')) return 'var(--color-node-agent, #6366f1)';
		if (nodeId.includes('tool')) return 'var(--color-node-tool, #8b5cf6)';
		if (nodeId.includes('reason')) return 'var(--color-node-reasoning, #ec4899)';
		if (nodeId.includes('pipeline')) return 'var(--color-node-pipeline, #06b6d4)';
		return 'var(--color-accent, #ff6b35)';
	}

	function dotColor(cp: Checkpoint): string {
		if (cp.branch_id) return 'var(--color-info, #3b82f6)';
		return 'var(--color-accent, #ff6b35)';
	}

	function renderValue(value: unknown): string {
		if (typeof value === 'string') return `"${value}"`;
		if (value === null) return 'null';
		if (value === undefined) return 'undefined';
		if (typeof value === 'object') return JSON.stringify(value, null, 2);
		return String(value);
	}
</script>

<div class="timeline-tab">
	{#if $checkpoints.length === 0}
		<!-- Empty state -->
		<div class="empty-state">
			<div class="empty-icon">
				<Clock size={32} />
			</div>
			<span class="empty-text">Run your pipeline to see the execution timeline</span>
		</div>
	{:else}
		<!-- Toolbar -->
		<div class="timeline-toolbar">
			<div class="toolbar-left">
				<span class="toolbar-label">Timeline</span>
				<span class="checkpoint-count">{$checkpoints.length} checkpoint{$checkpoints.length === 1 ? '' : 's'}</span>
			</div>
			<button class="toolbar-btn" onclick={handleClear} title="Clear checkpoints">
				<Trash2 size={13} />
			</button>
		</div>

		<!-- Timeline visualization -->
		<div class="timeline-scroll" bind:this={timelineContainer}>
			<div class="timeline-track">
				<div class="timeline-line"></div>
				{#each $checkpoints as cp (cp.index)}
					{@const isSelected = selectedIndex === cp.index}
					{@const isCompare = compareIndex === cp.index}
					<button
						class="checkpoint-dot-wrapper"
						class:selected={isSelected}
						class:compare={isCompare}
						onclick={(e) => handleCheckpointClick(cp, e)}
						title="{cp.node_id} - {formatTimestamp(cp.timestamp)}{cp.branch_id ? ` (branch: ${cp.branch_id})` : ''}"
					>
						<div
							class="checkpoint-dot"
							class:selected={isSelected}
							class:compare={isCompare}
							class:forked={!!cp.branch_id}
							style="--dot-color: {dotColor(cp)}"
						></div>
						<span class="dot-label">{cp.index}</span>
					</button>
				{/each}
			</div>
		</div>

		<!-- Debugging controls -->
		{#if selectedCheckpoint}
			<div class="debug-controls">
				<button class="debug-btn" onclick={handleRewind} title="Rewind to this checkpoint">
					<SkipBack size={13} />
					<span>Rewind</span>
				</button>
				<button class="debug-btn" onclick={handleFork} title="Fork from this checkpoint">
					<GitBranch size={13} />
					<span>Fork</span>
				</button>
				{#if compareIndex !== null}
					<button class="debug-btn active" onclick={loadDiff} title="Compare checkpoints">
						<GitCompare size={13} />
						<span>Compare #{selectedIndex} vs #{compareIndex}</span>
					</button>
				{:else}
					<span class="debug-hint">Shift+click another checkpoint to compare</span>
				{/if}
			</div>
		{/if}

		<!-- Diff result -->
		{#if diffResult}
			<div class="diff-panel">
				<div class="diff-header">Diff: #{selectedIndex} vs #{compareIndex}</div>
				<div class="diff-body">
					{#if diffResult.added.length > 0}
						<div class="diff-section">
							<span class="diff-label diff-added">Added</span>
							{#each diffResult.added as key}
								<span class="diff-key">{key}</span>
							{/each}
						</div>
					{/if}
					{#if diffResult.removed.length > 0}
						<div class="diff-section">
							<span class="diff-label diff-removed">Removed</span>
							{#each diffResult.removed as key}
								<span class="diff-key">{key}</span>
							{/each}
						</div>
					{/if}
					{#if diffResult.changed.length > 0}
						<div class="diff-section">
							<span class="diff-label diff-changed">Changed</span>
							{#each diffResult.changed as key}
								<span class="diff-key">{key}</span>
							{/each}
						</div>
					{/if}
					{#if diffResult.added.length === 0 && diffResult.removed.length === 0 && diffResult.changed.length === 0}
						<span class="diff-empty">No differences</span>
					{/if}
				</div>
			</div>
		{/if}

		<!-- Selected checkpoint detail -->
		{#if selectedCheckpoint}
			<div class="detail-panel">
				<div class="detail-header">
					<span class="detail-node-badge" style="background: {nodeColor(selectedCheckpoint.node_id)}20; color: {nodeColor(selectedCheckpoint.node_id)}">
						{selectedCheckpoint.node_id}
					</span>
					<span class="detail-time">{formatRelativeTime(selectedCheckpoint.timestamp)}</span>
					<span class="detail-timestamp">{formatTimestamp(selectedCheckpoint.timestamp)}</span>
				</div>

				{#if selectedCheckpoint.branch_id}
					<div class="detail-branch">
						<GitBranch size={12} />
						<span>Branch: {selectedCheckpoint.branch_id}</span>
						{#if selectedCheckpoint.parent_index !== null && selectedCheckpoint.parent_index !== undefined}
							<span class="branch-parent">from checkpoint #{selectedCheckpoint.parent_index}</span>
						{/if}
					</div>
				{/if}

				<!-- State viewer -->
				<div class="json-section">
					<button class="json-toggle" onclick={() => (expandedState = !expandedState)}>
						{#if expandedState}
							<ChevronDown size={12} />
						{:else}
							<ChevronRight size={12} />
						{/if}
						<span class="json-label">State</span>
						<span class="json-count">{Object.keys(selectedCheckpoint.state).length} keys</span>
					</button>
					{#if expandedState}
						<div class="json-tree">
							{#each Object.entries(selectedCheckpoint.state) as [key, value]}
								<div class="json-row">
									<span class="json-key">{key}:</span>
									<span class="json-value">{renderValue(value)}</span>
								</div>
							{/each}
							{#if Object.keys(selectedCheckpoint.state).length === 0}
								<span class="json-empty">empty</span>
							{/if}
						</div>
					{/if}
				</div>

				<!-- Inputs viewer -->
				<div class="json-section">
					<button class="json-toggle" onclick={() => (expandedInputs = !expandedInputs)}>
						{#if expandedInputs}
							<ChevronDown size={12} />
						{:else}
							<ChevronRight size={12} />
						{/if}
						<span class="json-label">Inputs</span>
						<span class="json-count">{Object.keys(selectedCheckpoint.inputs).length} keys</span>
					</button>
					{#if expandedInputs}
						<div class="json-tree">
							{#each Object.entries(selectedCheckpoint.inputs) as [key, value]}
								<div class="json-row">
									<span class="json-key">{key}:</span>
									<span class="json-value">{renderValue(value)}</span>
								</div>
							{/each}
							{#if Object.keys(selectedCheckpoint.inputs).length === 0}
								<span class="json-empty">empty</span>
							{/if}
						</div>
					{/if}
				</div>
			</div>
		{/if}
	{/if}
</div>

<style>
	.timeline-tab {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	/* Empty state */
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: 12px;
		padding: 24px;
	}

	.empty-icon {
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.4;
	}

	.empty-text {
		font-size: 12px;
		color: var(--color-text-secondary, #8888a0);
		text-align: center;
	}

	/* Toolbar */
	.timeline-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 12px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
	}

	.toolbar-left {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.toolbar-label {
		font-size: 11px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.checkpoint-count {
		font-size: 11px;
		color: var(--color-accent, #ff6b35);
		font-weight: 500;
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

	/* Timeline track */
	.timeline-scroll {
		flex-shrink: 0;
		overflow-x: auto;
		overflow-y: hidden;
		padding: 12px 16px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
	}

	.timeline-track {
		display: flex;
		align-items: center;
		gap: 24px;
		position: relative;
		min-width: max-content;
		padding: 8px 0;
	}

	.timeline-line {
		position: absolute;
		top: 50%;
		left: 0;
		right: 0;
		height: 2px;
		background: var(--color-border, #2a2a3a);
		transform: translateY(-50%);
		pointer-events: none;
	}

	.checkpoint-dot-wrapper {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
		position: relative;
		z-index: 1;
		background: none;
		border: none;
		padding: 4px;
		cursor: pointer;
	}

	.checkpoint-dot {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		background: var(--dot-color);
		transition: transform 0.15s ease, box-shadow 0.15s ease;
		flex-shrink: 0;
	}

	.checkpoint-dot-wrapper:hover .checkpoint-dot {
		transform: scale(1.3);
	}

	.checkpoint-dot.selected {
		width: 16px;
		height: 16px;
		box-shadow: 0 0 0 3px rgba(255, 107, 53, 0.3), 0 0 12px rgba(255, 107, 53, 0.2);
	}

	.checkpoint-dot.compare {
		width: 16px;
		height: 16px;
		box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.3), 0 0 12px rgba(59, 130, 246, 0.2);
	}

	.checkpoint-dot.forked {
		border: 2px solid var(--color-info, #3b82f6);
		background: var(--color-bg-elevated, #1a1a26);
	}

	.dot-label {
		font-size: 9px;
		color: var(--color-text-secondary, #8888a0);
		font-weight: 500;
	}

	.checkpoint-dot-wrapper.selected .dot-label {
		color: var(--color-accent, #ff6b35);
		font-weight: 700;
	}

	.checkpoint-dot-wrapper.compare .dot-label {
		color: var(--color-info, #3b82f6);
		font-weight: 700;
	}

	/* Debug controls */
	.debug-controls {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 12px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
	}

	.debug-btn {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px 10px;
		border: 1px solid var(--color-border, #2a2a3a);
		background: var(--color-bg-elevated, #1a1a26);
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
	}

	.debug-btn:hover {
		background: oklch(from var(--color-text-primary) l c h / 5%);
		color: var(--color-text-primary, #e8e8ed);
		border-color: var(--color-text-secondary, #8888a0);
	}

	.debug-btn.active {
		border-color: var(--color-info, #3b82f6);
		color: var(--color-info, #3b82f6);
	}

	.debug-hint {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.6;
		margin-left: 4px;
	}

	/* Diff panel */
	.diff-panel {
		flex-shrink: 0;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		padding: 8px 12px;
	}

	.diff-header {
		font-size: 11px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
		margin-bottom: 6px;
	}

	.diff-body {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.diff-section {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-wrap: wrap;
	}

	.diff-label {
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.05em;
		padding: 1px 6px;
		border-radius: 3px;
	}

	.diff-added {
		background: rgba(34, 197, 94, 0.15);
		color: var(--color-success, #22c55e);
	}

	.diff-removed {
		background: rgba(239, 68, 68, 0.15);
		color: var(--color-error, #ef4444);
	}

	.diff-changed {
		background: rgba(245, 158, 11, 0.15);
		color: var(--color-warning, #f59e0b);
	}

	.diff-key {
		font-size: 11px;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		color: var(--color-text-primary, #e8e8ed);
		background: var(--color-bg-elevated, #1a1a26);
		padding: 1px 6px;
		border-radius: 3px;
	}

	.diff-empty {
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
	}

	/* Detail panel */
	.detail-panel {
		flex: 1;
		overflow-y: auto;
		padding: 10px 12px;
	}

	.detail-header {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
	}

	.detail-node-badge {
		font-size: 11px;
		font-weight: 600;
		padding: 2px 8px;
		border-radius: 4px;
	}

	.detail-time {
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
	}

	.detail-timestamp {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.6;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
	}

	.detail-branch {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 11px;
		color: var(--color-info, #3b82f6);
		margin-bottom: 10px;
		padding: 4px 8px;
		background: rgba(59, 130, 246, 0.08);
		border-radius: 4px;
	}

	.branch-parent {
		color: var(--color-text-secondary, #8888a0);
		font-size: 10px;
	}

	/* JSON tree */
	.json-section {
		margin-bottom: 6px;
	}

	.json-toggle {
		display: flex;
		align-items: center;
		gap: 4px;
		width: 100%;
		padding: 4px 6px;
		border: none;
		background: transparent;
		border-radius: 4px;
		cursor: pointer;
		color: var(--color-text-primary, #e8e8ed);
		transition: background 0.15s ease;
	}

	.json-toggle:hover {
		background: oklch(from var(--color-text-primary) l c h / 3%);
	}

	.json-label {
		font-size: 11px;
		font-weight: 600;
	}

	.json-count {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		margin-left: 4px;
	}

	.json-tree {
		padding: 4px 8px 4px 20px;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		font-size: 11px;
		line-height: 1.6;
	}

	.json-row {
		display: flex;
		gap: 6px;
		padding: 1px 0;
	}

	.json-key {
		color: var(--color-accent, #ff6b35);
		flex-shrink: 0;
	}

	.json-value {
		color: var(--color-text-primary, #e8e8ed);
		opacity: 0.8;
		white-space: pre-wrap;
		word-break: break-all;
	}

	.json-empty {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.6;
		font-style: italic;
	}
</style>
