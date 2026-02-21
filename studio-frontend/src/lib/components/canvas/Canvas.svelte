<script lang="ts">
	import {
		SvelteFlow,
		Controls,
		MiniMap,
		Background,
		BackgroundVariant
	} from '@xyflow/svelte';
	import { nodes, edges, selectedNodeId } from '$lib/stores/pipeline';
	import Workflow from 'lucide-svelte/icons/workflow';
	import Boxes from 'lucide-svelte/icons/boxes';
	import Bot from 'lucide-svelte/icons/bot';
	import Wrench from 'lucide-svelte/icons/wrench';
	import Cable from 'lucide-svelte/icons/cable';
	import AgentNode from './nodes/AgentNode.svelte';
	import ToolNode from './nodes/ToolNode.svelte';
	import ReasoningNode from './nodes/ReasoningNode.svelte';
	import ConditionNode from './nodes/ConditionNode.svelte';
	import MemoryNode from './nodes/MemoryNode.svelte';
	import ValidatorNode from './nodes/ValidatorNode.svelte';
	import CustomCodeNode from './nodes/CustomCodeNode.svelte';
	import FanOutNode from './nodes/FanOutNode.svelte';
	import FanInNode from './nodes/FanInNode.svelte';
	import InputNode from './nodes/InputNode.svelte';
	import OutputNode from './nodes/OutputNode.svelte';
	import { resolvedTheme } from '$lib/stores/theme';

	const nodeTypes = {
		input: InputNode,
		output: OutputNode,
		agent: AgentNode,
		tool: ToolNode,
		reasoning: ReasoningNode,
		condition: ConditionNode,
		memory: MemoryNode,
		validator: ValidatorNode,
		custom_code: CustomCodeNode,
		fan_out: FanOutNode,
		fan_in: FanInNode
	};

	let isEmpty = $derived($nodes.length === 0);
	let totalNodes = $derived($nodes.length);
	let agentCount = $derived($nodes.filter((n) => n.type === 'agent').length);
	let toolCount = $derived($nodes.filter((n) => n.type === 'tool').length);
	let connectionCount = $derived($edges.length);
</script>

<div class="canvas-wrapper">
	<SvelteFlow
		{nodeTypes}
		bind:nodes={$nodes}
		bind:edges={$edges}
		fitView
		colorMode={$resolvedTheme === 'light' ? 'light' : 'dark'}
		defaultEdgeOptions={{
			type: 'smoothstep',
			animated: true,
			style: 'stroke: #cbd5e1; stroke-width: 2.5px;'
		}}
		onnodeclick={({ node }) => selectedNodeId.set(node.id)}
		onpaneclick={() => selectedNodeId.set(null)}
	>
		<Controls position="bottom-left" />
		<MiniMap position="bottom-right" />
		<Background variant={BackgroundVariant.Dots} gap={24} size={1} color={$resolvedTheme === 'light' ? '#c8ccd4' : '#2a2a3a'} />
	</SvelteFlow>

	{#if !isEmpty}
		<div class="stats-bar">
			<div class="stat-item">
				<Boxes size={12} />
				<span class="stat-label">Nodes</span>
				<span class="stat-value">{totalNodes}</span>
			</div>
			<div class="stat-divider"></div>
			<div class="stat-item">
				<Bot size={12} />
				<span class="stat-label">Agents</span>
				<span class="stat-value">{agentCount}</span>
			</div>
			<div class="stat-divider"></div>
			<div class="stat-item">
				<Wrench size={12} />
				<span class="stat-label">Tools</span>
				<span class="stat-value">{toolCount}</span>
			</div>
			<div class="stat-divider"></div>
			<div class="stat-item">
				<Cable size={12} />
				<span class="stat-label">Links</span>
				<span class="stat-value">{connectionCount}</span>
			</div>
		</div>
	{/if}

	{#if isEmpty}
		<div class="empty-overlay">
			<div class="empty-container">
				<Workflow size={40} />
				<h2 class="empty-headline">Start building your pipeline</h2>
				<p class="empty-hint">Click components in the left panel to add them, or press Cmd+K to search</p>
			</div>
		</div>
	{/if}
</div>

<style>
	.canvas-wrapper {
		width: 100%;
		height: 100%;
		position: relative;
	}

	.stats-bar {
		position: absolute;
		top: 12px;
		left: 50%;
		transform: translateX(-50%);
		z-index: 5;
		display: flex;
		align-items: center;
		gap: 0;
		background: oklch(from var(--color-bg-secondary) l c h / 85%);
		backdrop-filter: blur(12px);
		-webkit-backdrop-filter: blur(12px);
		border: 1px solid var(--color-border);
		border-radius: 20px;
		padding: 5px 14px;
		box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
		pointer-events: none;
		user-select: none;
	}

	.stat-item {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 0 8px;
		color: var(--color-text-secondary);
		font-size: 11px;
		font-family: var(--font-sans, system-ui, sans-serif);
		white-space: nowrap;
	}

	.stat-label {
		color: var(--color-text-muted);
		font-weight: 500;
	}

	.stat-value {
		color: var(--color-text-primary);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.stat-divider {
		width: 1px;
		height: 14px;
		background: var(--color-border);
		flex-shrink: 0;
	}

	.empty-overlay {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		pointer-events: none;
		z-index: 1;
	}

	.empty-container {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
		padding: 40px 48px;
		border: 2px dashed var(--color-border, #2a2a3a);
		border-radius: 16px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.6;
	}

	.empty-headline {
		font-size: 16px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
		margin: 0;
	}

	.empty-hint {
		font-size: 12px;
		color: var(--color-text-secondary, #8888a0);
		margin: 0;
	}
</style>
