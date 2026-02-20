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
	import AgentNode from './nodes/AgentNode.svelte';
	import ToolNode from './nodes/ToolNode.svelte';
	import ReasoningNode from './nodes/ReasoningNode.svelte';
	import ConditionNode from './nodes/ConditionNode.svelte';

	const nodeTypes = {
		agent: AgentNode,
		tool: ToolNode,
		reasoning: ReasoningNode,
		condition: ConditionNode
	};

	let isEmpty = $derived($nodes.length === 0);
</script>

<div class="canvas-wrapper">
	<SvelteFlow
		{nodeTypes}
		bind:nodes={$nodes}
		bind:edges={$edges}
		fitView
		colorMode="dark"
		defaultEdgeOptions={{ animated: true }}
		onnodeclick={({ node }) => selectedNodeId.set(node.id)}
		onpaneclick={() => selectedNodeId.set(null)}
	>
		<Controls position="bottom-left" />
		<MiniMap position="bottom-right" />
		<Background variant={BackgroundVariant.Dots} gap={20} size={1} />
	</SvelteFlow>

	{#if isEmpty}
		<div class="empty-overlay">
			<div class="empty-container">
				<Workflow size={40} />
				<h2 class="empty-headline">Start building your pipeline</h2>
				<p class="empty-hint">Drag components from the left panel, or press Cmd+K to search</p>
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
