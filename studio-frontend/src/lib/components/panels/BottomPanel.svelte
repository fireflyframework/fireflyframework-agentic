<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Terminal, Code, Clock, Plug, FlaskConical, GitBranch, Rocket, Activity, FolderOpen, History, Eye, ListChecks, ChevronDown, ChevronUp } from 'lucide-svelte';
	import type { BottomPanelTab } from '$lib/stores/ui';
	import { bottomPanelOpen, bottomPanelTab } from '$lib/stores/ui';
	import { executionEvents, checkpoints } from '$lib/stores/execution';
	import ConsoleTab from './ConsoleTab.svelte';
	import CodeTab from './CodeTab.svelte';
	import TimelineTab from './TimelineTab.svelte';
	import HistoryPanel from './HistoryPanel.svelte';
	import IntegrationsPanel from './IntegrationsPanel.svelte';
	import EvaluatePanel from './EvaluatePanel.svelte';
	import ExperimentsPanel from './ExperimentsPanel.svelte';
	import DeployPanel from './DeployPanel.svelte';
	import MonitorPanel from './MonitorPanel.svelte';
	import FilesPanel from './FilesPanel.svelte';
	import OraclePanel from './OraclePanel.svelte';
	import ExecutionsPanel from './ExecutionsPanel.svelte';
	import { oracleInsights } from '$lib/stores/oracle';

	const errorCount = $derived($executionEvents.filter(e => e.type === 'node_error').length);
	const checkpointCount = $derived($checkpoints.length);
	const oraclePendingCount = $derived($oracleInsights.filter(i => i.status === 'pending').length);

	const tabs: Array<{ id: BottomPanelTab; label: string; icon: typeof Terminal }> = [
		{ id: 'console', label: 'Console', icon: Terminal },
		{ id: 'code', label: 'Code', icon: Code },
		{ id: 'timeline', label: 'Timeline', icon: Clock },
		{ id: 'integrations', label: 'Integrate', icon: Plug },
		{ id: 'evaluate', label: 'Evaluate', icon: FlaskConical },
		{ id: 'experiments', label: 'Experiments', icon: GitBranch },
		{ id: 'deploy', label: 'Deploy', icon: Rocket },
		{ id: 'monitor', label: 'Monitor', icon: Activity },
		{ id: 'files', label: 'Files', icon: FolderOpen },
		{ id: 'history', label: 'History', icon: History },
		{ id: 'oracle', label: 'Oracle', icon: Eye },
		{ id: 'executions', label: 'Executions', icon: ListChecks },
	];

	let panelHeight = $state(320);
	let isDragging = $state(false);
	let dragStartY = $state(0);
	let dragStartHeight = $state(0);

	const MIN_HEIGHT = 120;
	// Max height will be computed as 60% of viewport

	function togglePanel() {
		bottomPanelOpen.update((v) => !v);
	}

	function selectTab(tabId: BottomPanelTab) {
		bottomPanelTab.set(tabId);
		if (!$bottomPanelOpen) {
			bottomPanelOpen.set(true);
		}
	}

	function onDragStart(event: MouseEvent) {
		event.preventDefault();
		isDragging = true;
		dragStartY = event.clientY;
		dragStartHeight = panelHeight;
		document.addEventListener('mousemove', onDragMove);
		document.addEventListener('mouseup', onDragEnd);
	}

	function onDragMove(event: MouseEvent) {
		if (!isDragging) return;
		const maxHeight = Math.floor(window.innerHeight * 0.6);
		const delta = dragStartY - event.clientY;
		const newHeight = Math.max(MIN_HEIGHT, Math.min(maxHeight, dragStartHeight + delta));
		panelHeight = newHeight;
	}

	function onDragEnd() {
		isDragging = false;
		document.removeEventListener('mousemove', onDragMove);
		document.removeEventListener('mouseup', onDragEnd);
	}

	onDestroy(() => {
		// Safety cleanup in case component destroys mid-drag
		document.removeEventListener('mousemove', onDragMove);
		document.removeEventListener('mouseup', onDragEnd);
	});
</script>

<div
	class="bottom-panel"
	class:dragging={isDragging}
	style:height={$bottomPanelOpen ? `${panelHeight}px` : '36px'}
>
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	{#if $bottomPanelOpen}
		<div class="drag-handle" onmousedown={onDragStart}>
			<div class="drag-indicator"></div>
		</div>
	{/if}

	<div class="tab-bar">
		<div class="tab-list">
			{#each tabs as tab (tab.id)}
				{@const TabIcon = tab.icon}
				<button
					class="tab-btn"
					class:active={$bottomPanelTab === tab.id}
					onclick={() => selectTab(tab.id)}
				>
					<TabIcon size={13} />
					<span>{tab.label}</span>
					{#if tab.id === 'console' && errorCount > 0}
						<span class="tab-badge error">{errorCount > 99 ? '99+' : errorCount}</span>
					{:else if tab.id === 'timeline' && checkpointCount > 0}
						<span class="tab-badge accent">{checkpointCount > 99 ? '99+' : checkpointCount}</span>
					{:else if tab.id === 'oracle' && oraclePendingCount > 0}
						<span class="tab-badge accent">{oraclePendingCount > 99 ? '99+' : oraclePendingCount}</span>
					{/if}
				</button>
			{/each}
		</div>

		<button class="toggle-btn" onclick={togglePanel} title={$bottomPanelOpen ? 'Collapse panel' : 'Expand panel'}>
			{#if $bottomPanelOpen}
				<ChevronDown size={14} />
			{:else}
				<ChevronUp size={14} />
			{/if}
		</button>
	</div>

	{#if $bottomPanelOpen}
		<div class="tab-content">
			{#if $bottomPanelTab === 'console'}
				<ConsoleTab />
			{:else if $bottomPanelTab === 'code'}
				<CodeTab />
			{:else if $bottomPanelTab === 'timeline'}
				<TimelineTab />
			{:else if $bottomPanelTab === 'integrations'}
				<IntegrationsPanel />
			{:else if $bottomPanelTab === 'evaluate'}
				<EvaluatePanel />
			{:else if $bottomPanelTab === 'experiments'}
				<ExperimentsPanel />
			{:else if $bottomPanelTab === 'deploy'}
				<DeployPanel />
			{:else if $bottomPanelTab === 'monitor'}
				<MonitorPanel />
			{:else if $bottomPanelTab === 'files'}
				<FilesPanel />
			{:else if $bottomPanelTab === 'history'}
				<HistoryPanel />
			{:else if $bottomPanelTab === 'oracle'}
				<OraclePanel />
			{:else if $bottomPanelTab === 'executions'}
				<ExecutionsPanel />
			{/if}
		</div>
	{/if}
</div>

<style>
	.bottom-panel {
		background: var(--color-bg-secondary, #12121a);
		border-top: 1px solid var(--color-border, #2a2a3a);
		display: flex;
		flex-direction: column;
		flex-shrink: 0;
		overflow: hidden;
		transition: height 0.2s ease;
	}

	.bottom-panel.dragging {
		transition: none;
		user-select: none;
	}

	.drag-handle {
		height: 12px;
		cursor: ns-resize;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.drag-handle:hover .drag-indicator {
		background: var(--color-text-secondary, #8888a0);
	}

	.drag-indicator {
		width: 40px;
		height: 2px;
		border-radius: 1px;
		background: var(--color-border, #2a2a3a);
		transition: background 0.15s ease;
	}

	.tab-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 8px;
		height: 36px;
		min-height: 36px;
		flex-shrink: 0;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
	}

	.tab-list {
		display: flex;
		align-items: center;
		gap: 2px;
		overflow-x: auto;
		scrollbar-width: none;
		flex: 1;
		min-width: 0;
	}

	.tab-list::-webkit-scrollbar {
		display: none;
	}

	.tab-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 12px;
		border: none;
		background: transparent;
		border-bottom: 2px solid transparent;
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: color 0.15s ease, border-color 0.15s ease;
		margin-bottom: -1px;
	}

	.tab-btn:hover {
		color: var(--color-text-primary, #e8e8ed);
	}

	.tab-btn.active {
		color: var(--color-text-primary, #e8e8ed);
		border-bottom-color: var(--color-accent, #ff6b35);
	}

	.tab-badge {
		min-width: 16px;
		height: 16px;
		padding: 0 4px;
		border-radius: 8px;
		font-size: 9px;
		font-weight: 700;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		line-height: 1;
	}

	.tab-badge.error {
		background: rgba(239, 68, 68, 0.2);
		color: var(--color-error, #ef4444);
		border: 1px solid rgba(239, 68, 68, 0.3);
	}

	.tab-badge.accent {
		background: oklch(from var(--color-accent, #ff6b35) l c h / 15%);
		color: var(--color-accent, #ff6b35);
		border: 1px solid oklch(from var(--color-accent, #ff6b35) l c h / 25%);
	}

	.toggle-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: none;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
	}

	.toggle-btn:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-text-primary, #e8e8ed);
	}

	.tab-content {
		flex: 1;
		overflow: hidden;
		position: relative;
	}

</style>
