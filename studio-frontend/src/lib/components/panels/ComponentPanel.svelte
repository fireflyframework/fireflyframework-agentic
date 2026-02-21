<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		Bot,
		Wrench,
		Brain,
		Database,
		Shield,
		Code,
		CircleDot,
		GitFork,
		GitMerge,
		Blocks,
		SlidersHorizontal,
		LogIn,
		LogOut
	} from 'lucide-svelte';
	import { addNode, selectedNodeId } from '$lib/stores/pipeline';
	import ConfigPanel from './ConfigPanel.svelte';
	import Tooltip from '$lib/components/shared/Tooltip.svelte';
	import type { Component } from 'svelte';

	// Resizable width
	let panelWidth = $state(320);
	let isDragging = $state(false);
	let dragStartX = $state(0);
	let dragStartWidth = $state(0);

	function onResizeStart(e: MouseEvent) {
		e.preventDefault();
		isDragging = true;
		dragStartX = e.clientX;
		dragStartWidth = panelWidth;
		document.addEventListener('mousemove', onResizeMove);
		document.addEventListener('mouseup', onResizeEnd);
	}

	function onResizeMove(e: MouseEvent) {
		if (!isDragging) return;
		panelWidth = Math.max(240, Math.min(480, dragStartWidth + (dragStartX - e.clientX)));
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

	interface PaletteItem {
		type: string;
		label: string;
		icon: Component<{ size?: number }>;
		color: string;
		group?: string;
		description: string;
	}

	const palette: PaletteItem[] = [
		{ type: 'input', label: 'Input', icon: LogIn, color: '#22c55e', group: 'io', description: 'Pipeline entry point. Triggers: manual, HTTP, queue, schedule, file upload.' },
		{ type: 'output', label: 'Output', icon: LogOut, color: '#ef4444', group: 'io', description: 'Pipeline exit point. Destinations: response, queue, webhook, storage.' },
		{ type: 'agent', label: 'Agent', icon: Bot, color: '#6366f1', description: 'An AI agent powered by an LLM. Configure model, instructions, and personality.' },
		{ type: 'tool', label: 'Tool', icon: Wrench, color: '#8b5cf6', description: 'A registered tool the agent can use: search, calculator, HTTP, database, etc.' },
		{ type: 'reasoning', label: 'Reasoning', icon: Brain, color: '#ec4899', description: 'A reasoning pattern: ReAct, Chain of Thought, Plan and Execute, Reflexion, etc.' },
		{ type: 'condition', label: 'Condition', icon: CircleDot, color: '#f59e0b', description: 'Routes the pipeline based on a condition. Define branches for different paths.' },
		{ type: 'memory', label: 'Memory', icon: Database, color: '#06b6d4', description: 'Store, retrieve, or clear data in the pipeline memory system.' },
		{ type: 'validator', label: 'Validator', icon: Shield, color: '#f59e0b', description: 'Validates pipeline output: check for empty, type, or custom rules.' },
		{ type: 'custom_code', label: 'Code', icon: Code, color: '#3b82f6', description: 'Run custom Python code. Define an async execute function.' },
		{ type: 'fan_out', label: 'Fan Out', icon: GitFork, color: '#64748b', description: 'Split input into parallel branches for concurrent processing.' },
		{ type: 'fan_in', label: 'Fan In', icon: GitMerge, color: '#64748b', description: 'Merge results from parallel branches back into a single flow.' }
	];

	function iconBg(hex: string): string {
		const r = parseInt(hex.slice(1, 3), 16);
		const g = parseInt(hex.slice(3, 5), 16);
		const b = parseInt(hex.slice(5, 7), 16);
		return `rgba(${r}, ${g}, ${b}, 0.15)`;
	}

	let activeView = $derived($selectedNodeId ? 'properties' : 'components');
</script>

<aside class="component-panel" class:dragging={isDragging} style:width="{panelWidth}px">
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="resize-handle" onmousedown={onResizeStart}></div>
	<!-- Tab header -->
	<div class="panel-tab-header">
		<button
			class="panel-tab-btn"
			class:active={activeView === 'components'}
			onclick={() => { if ($selectedNodeId) selectedNodeId.set(null); }}
		>
			<Blocks size={12} />
			<span>Components</span>
		</button>
		{#if $selectedNodeId}
			<button
				class="panel-tab-btn"
				class:active={activeView === 'properties'}
				onclick={() => {}}
			>
				<SlidersHorizontal size={12} />
				<span>Properties</span>
			</button>
		{/if}
	</div>

	<!-- Content -->
	<div class="panel-content">
		{#if activeView === 'properties' && $selectedNodeId}
			<ConfigPanel />
		{:else}
			<div class="palette-items">
				<div class="palette-group-label">Pipeline I/O</div>
				{#each palette.filter(i => i.group === 'io') as item}
					<Tooltip text={item.label} description={item.description} position="left" delay={300}>
						<button
							class="palette-item"
							onclick={() => addNode(item.type, item.label)}
						>
							<div
								class="palette-icon"
								style:background={iconBg(item.color)}
								style:color={item.color}
							>
								<item.icon size={14} />
							</div>
							<span class="palette-label">{item.label}</span>
						</button>
					</Tooltip>
				{/each}
				<div class="palette-group-label" style="margin-top: 8px;">Processing</div>
				{#each palette.filter(i => !i.group) as item}
					<Tooltip text={item.label} description={item.description} position="left" delay={300}>
						<button
							class="palette-item"
							onclick={() => addNode(item.type, item.label)}
						>
							<div
								class="palette-icon"
								style:background={iconBg(item.color)}
								style:color={item.color}
							>
								<item.icon size={14} />
							</div>
							<span class="palette-label">{item.label}</span>
						</button>
					</Tooltip>
				{/each}
			</div>
		{/if}
	</div>
</aside>

<style>
	.component-panel {
		min-width: 240px;
		background: var(--color-bg-secondary, #12121a);
		border-left: 1px solid var(--color-border, #2a2a3a);
		display: flex;
		flex-direction: column;
		overflow: hidden;
		flex-shrink: 0;
		position: relative;
	}

	.component-panel.dragging {
		user-select: none;
	}

	.resize-handle {
		position: absolute;
		top: 0;
		left: -2px;
		width: 5px;
		height: 100%;
		cursor: ew-resize;
		z-index: 10;
	}

	.resize-handle:hover {
		background: oklch(from var(--color-accent, #ff6b35) l c h / 30%);
	}

	.panel-tab-header {
		display: flex;
		align-items: center;
		gap: 2px;
		padding: 0 8px;
		height: 36px;
		min-height: 36px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
	}

	.panel-tab-btn {
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
		transition: color 0.15s ease, border-color 0.15s ease;
		margin-bottom: -1px;
	}

	.panel-tab-btn:hover {
		color: var(--color-text-primary, #e8e8ed);
	}

	.panel-tab-btn.active {
		color: var(--color-text-primary, #e8e8ed);
		border-bottom-color: var(--color-accent, #ff6b35);
	}

	.panel-content {
		flex: 1;
		overflow-y: auto;
	}

	/* Palette items */
	.palette-items {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 8px;
	}

	.palette-items :global(.tooltip-wrapper) {
		display: flex;
		width: 100%;
	}

	.palette-item {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 8px;
		border: none;
		background: transparent;
		border-radius: 8px;
		cursor: pointer;
		transition: background 0.15s ease, transform 0.1s ease;
		width: 100%;
		text-align: left;
	}

	.palette-item:hover {
		background: rgba(255, 255, 255, 0.05);
	}

	.palette-item:active {
		transform: scale(0.97);
	}

	.palette-icon {
		width: 28px;
		height: 28px;
		border-radius: 6px;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.palette-label {
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-primary, #e8e8ed);
	}

	.palette-group-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-text-secondary, #8888a0);
		padding: 6px 8px 2px;
		opacity: 0.7;
	}
</style>
