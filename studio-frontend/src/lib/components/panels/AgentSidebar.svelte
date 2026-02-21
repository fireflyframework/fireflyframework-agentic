<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Bot, Code, Sparkles, PanelLeftClose } from 'lucide-svelte';
	import { agentSidebarOpen, activeAgentTab } from '$lib/stores/ui';
	import { oracleInsights } from '$lib/stores/oracle';
	import type { AgentTab } from '$lib/stores/ui';
	import ArchitectTab from './ArchitectTab.svelte';
	import SmithTab from './SmithTab.svelte';
	import OracleTab from './OracleTab.svelte';

	const oraclePendingCount = $derived($oracleInsights.filter(i => i.status === 'pending').length);

	const tabs: Array<{ id: AgentTab; label: string; icon: typeof Bot; color: string }> = [
		{ id: 'architect', label: 'Architect', icon: Bot, color: 'var(--color-accent, #ff6b35)' },
		{ id: 'smith', label: 'Smith', icon: Code, color: '#22c55e' },
		{ id: 'oracle', label: 'Oracle', icon: Sparkles, color: '#8b5cf6' },
	];

	function selectTab(id: AgentTab) {
		activeAgentTab.set(id);
	}

	function closeSidebar() {
		agentSidebarOpen.set(false);
	}

	// Resizable width
	let sidebarWidth = $state(380);
	let isDragging = $state(false);
	let dragStartX = $state(0);
	let dragStartWidth = $state(0);
	const MIN_WIDTH = 280;
	const MAX_WIDTH_RATIO = 0.5;

	function onResizeStart(event: MouseEvent) {
		event.preventDefault();
		isDragging = true;
		dragStartX = event.clientX;
		dragStartWidth = sidebarWidth;
		document.addEventListener('mousemove', onResizeMove);
		document.addEventListener('mouseup', onResizeEnd);
	}

	function onResizeMove(event: MouseEvent) {
		if (!isDragging) return;
		const maxWidth = Math.floor(window.innerWidth * MAX_WIDTH_RATIO);
		const delta = event.clientX - dragStartX;
		sidebarWidth = Math.max(MIN_WIDTH, Math.min(maxWidth, dragStartWidth + delta));
	}

	function onResizeEnd() {
		isDragging = false;
		document.removeEventListener('mousemove', onResizeMove);
		document.removeEventListener('mouseup', onResizeEnd);
	}

	onDestroy(() => {
		document.removeEventListener('mousemove', onResizeMove);
		document.removeEventListener('mouseup', onResizeEnd);
	});
</script>

{#if $agentSidebarOpen}
	<aside
		class="agent-sidebar"
		class:dragging={isDragging}
		style:width="{sidebarWidth}px"
	>
		<!-- Tab bar -->
		<div class="agent-tab-bar">
			<div class="tab-list">
				{#each tabs as tab (tab.id)}
					{@const TabIcon = tab.icon}
					<button
						class="agent-tab"
						class:active={$activeAgentTab === tab.id}
						style:--tab-color={tab.color}
						onclick={() => selectTab(tab.id)}
					>
						<span class="tab-dot" style:background={tab.color}></span>
						<span class="tab-label">{tab.label}</span>
						{#if tab.id === 'oracle' && oraclePendingCount > 0}
							<span class="tab-badge">{oraclePendingCount}</span>
						{/if}
					</button>
				{/each}
			</div>
			<button class="collapse-btn" onclick={closeSidebar} title="Collapse sidebar">
				<PanelLeftClose size={14} />
			</button>
		</div>

		<!-- Tab panels — all mounted, visibility toggled via CSS -->
		<div class="tab-panels">
			<div class="tab-panel" class:visible={$activeAgentTab === 'architect'}>
				<ArchitectTab />
			</div>
			<div class="tab-panel" class:visible={$activeAgentTab === 'smith'}>
				<SmithTab />
			</div>
			<div class="tab-panel" class:visible={$activeAgentTab === 'oracle'}>
				<OracleTab />
			</div>
		</div>

		<!-- Resize handle -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="resize-handle" onmousedown={onResizeStart}></div>
	</aside>
{/if}

<style>
	.agent-sidebar {
		position: relative;
		min-width: 280px;
		background: var(--color-bg-secondary, #12121a);
		border-right: 1px solid var(--color-border, #2a2a3a);
		display: flex;
		flex-direction: column;
		overflow: hidden;
		flex-shrink: 0;
		animation: sidebarSlideIn 0.2s ease-out;
	}

	.agent-sidebar.dragging {
		user-select: none;
	}

	@keyframes sidebarSlideIn {
		from { transform: translateX(-20px); opacity: 0; }
		to { transform: translateX(0); opacity: 1; }
	}

	/* Tab bar */
	.agent-tab-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		height: 36px;
		min-height: 36px;
		padding: 0 6px 0 4px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
	}

	.tab-list {
		display: flex;
		align-items: center;
		gap: 1px;
	}

	.agent-tab {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 6px 10px;
		border: none;
		background: transparent;
		border-bottom: 2px solid transparent;
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: color 0.15s, border-color 0.15s;
		margin-bottom: -1px;
	}

	.agent-tab:hover {
		color: var(--color-text-primary, #e8e8ed);
	}

	.agent-tab.active {
		color: var(--color-text-primary, #e8e8ed);
		border-bottom-color: var(--tab-color);
	}

	.tab-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		flex-shrink: 0;
		opacity: 0.6;
		transition: opacity 0.15s;
	}

	.agent-tab.active .tab-dot {
		opacity: 1;
		box-shadow: 0 0 4px var(--tab-color);
	}

	.tab-label {
		white-space: nowrap;
	}

	.tab-badge {
		min-width: 14px;
		height: 14px;
		padding: 0 3px;
		border-radius: 7px;
		background: #8b5cf6;
		color: white;
		font-size: 9px;
		font-weight: 700;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		line-height: 1;
	}

	.collapse-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: none;
		background: transparent;
		border-radius: 6px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
	}

	.collapse-btn:hover {
		background: oklch(from var(--color-text-primary) l c h / 5%);
		color: var(--color-text-primary, #e8e8ed);
	}

	/* Tab panels */
	.tab-panels {
		flex: 1;
		min-height: 0;
		position: relative;
	}

	.tab-panel {
		position: absolute;
		inset: 0;
		display: none;
		flex-direction: column;
	}

	.tab-panel.visible {
		display: flex;
	}

	/* Resize handle */
	.resize-handle {
		position: absolute;
		top: 0;
		right: -2px;
		width: 5px;
		height: 100%;
		cursor: ew-resize;
		z-index: 10;
	}

	.resize-handle:hover {
		background: oklch(from var(--color-accent, #ff6b35) l c h / 30%);
	}
</style>
