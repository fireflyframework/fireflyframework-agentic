<script lang="ts">
	import { X, Bot, Wrench, Brain, CircleDot } from 'lucide-svelte';
	import { selectedNode, selectedNodeId, updateNodeData } from '$lib/stores/pipeline';
	import FormField from './FormField.svelte';

	const iconMap: Record<string, typeof Bot> = {
		agent: Bot,
		tool: Wrench,
		reasoning: Brain,
		condition: CircleDot
	};

	const nodeColorMap: Record<string, string> = {
		agent: '#6366f1',
		tool: '#8b5cf6',
		reasoning: '#ec4899',
		condition: '#06b6d4'
	};

	const modelOptions = [
		'openai:gpt-4o',
		'openai:gpt-4o-mini',
		'anthropic:claude-sonnet-4-20250514',
		'anthropic:claude-haiku-4-5-20251001',
		'google:gemini-2.0-flash'
	];

	const patternOptions = [
		'react',
		'chain_of_thought',
		'plan_and_execute',
		'reflexion',
		'tree_of_thoughts',
		'goal_decomposition'
	];

	// Local field state bound to inputs
	let nameVal = $state('');
	let modelVal = $state('');
	let instructionsVal = $state('');
	let descriptionVal = $state('');
	let timeoutVal = $state('');
	let patternVal = $state('');
	let maxStepsVal = $state('');
	let conditionVal = $state('');

	// Track which node we're showing to re-sync when selection changes
	let lastNodeId = $state<string | null>(null);

	// Flag to prevent syncing back while we're loading from store
	let syncing = false;

	// Sync local state from store when selected node changes
	$effect(() => {
		const node = $selectedNode;
		if (node && node.id !== lastNodeId) {
			syncing = true;
			lastNodeId = node.id;
			nameVal = (node.data.label as string) ?? '';
			modelVal = (node.data.model as string) ?? '';
			instructionsVal = (node.data.instructions as string) ?? '';
			descriptionVal = (node.data.description as string) ?? '';
			timeoutVal = node.data.timeout != null ? String(node.data.timeout) : '';
			patternVal = (node.data.pattern as string) ?? '';
			maxStepsVal = node.data.maxSteps != null ? String(node.data.maxSteps) : '';
			conditionVal = (node.data.condition as string) ?? '';
			syncing = false;
		}
		if (!node) {
			lastNodeId = null;
		}
	});

	// Push individual field changes to the store
	function pushField(key: string, val: string) {
		if (syncing) return;
		const node = $selectedNode;
		if (!node) return;
		if (key === 'timeout' || key === 'maxSteps') {
			updateNodeData(node.id, key, val === '' ? undefined : Number(val));
		} else {
			updateNodeData(node.id, key, val);
		}
	}

	// Watch each field value and push to store
	$effect(() => { pushField('label', nameVal); });
	$effect(() => { pushField('model', modelVal); });
	$effect(() => { pushField('instructions', instructionsVal); });
	$effect(() => { pushField('description', descriptionVal); });
	$effect(() => { pushField('timeout', timeoutVal); });
	$effect(() => { pushField('pattern', patternVal); });
	$effect(() => { pushField('maxSteps', maxStepsVal); });
	$effect(() => { pushField('condition', conditionVal); });

	function close() {
		selectedNodeId.set(null);
	}
</script>

{#if $selectedNode}
	{@const node = $selectedNode}
	{@const NodeIcon = iconMap[node.type ?? ''] ?? Bot}

	<aside class="config-panel">
		<div class="panel-header">
			<div class="header-left">
				<div
					class="header-icon"
					style:--node-color={nodeColorMap[node.type ?? ''] ?? '#ff6b35'}
				>
					<NodeIcon size={14} />
				</div>
				<span class="header-title">Node Properties</span>
			</div>
			<button class="close-btn" onclick={close} title="Close panel">
				<X size={14} />
			</button>
		</div>

		<div class="panel-body">
			<!-- Node type badge -->
			<div class="node-type-badge">
				<span class="badge-text">{node.type ?? 'unknown'}</span>
			</div>

			<div class="field-group">
				{#if node.type === 'agent'}
					<FormField
						label="Name"
						type="text"
						bind:value={nameVal}
						placeholder="Agent name"
					/>
					<FormField
						label="Model"
						type="datalist"
						bind:value={modelVal}
						placeholder="e.g. openai:gpt-4o"
						options={modelOptions}
					/>
					<FormField
						label="Instructions"
						type="textarea"
						bind:value={instructionsVal}
						placeholder="System instructions for this agent..."
					/>
					<FormField
						label="Description"
						type="text"
						bind:value={descriptionVal}
						placeholder="Agent description"
					/>
				{:else if node.type === 'tool'}
					<FormField
						label="Name"
						type="text"
						bind:value={nameVal}
						placeholder="Tool name"
					/>
					<FormField
						label="Description"
						type="text"
						bind:value={descriptionVal}
						placeholder="What this tool does"
					/>
					<FormField
						label="Timeout (seconds)"
						type="number"
						bind:value={timeoutVal}
						placeholder="30"
					/>
				{:else if node.type === 'reasoning'}
					<FormField
						label="Pattern"
						type="select"
						bind:value={patternVal}
						options={patternOptions}
					/>
					<FormField
						label="Max Steps"
						type="number"
						bind:value={maxStepsVal}
						placeholder="10"
					/>
				{:else if node.type === 'condition'}
					<FormField
						label="Condition Expression"
						type="text"
						bind:value={conditionVal}
						placeholder="result.status == 'success'"
					/>
				{:else}
					<FormField
						label="Name"
						type="text"
						bind:value={nameVal}
						placeholder="Node name"
					/>
				{/if}
			</div>
		</div>
	</aside>
{/if}

<style>
	.config-panel {
		width: 320px;
		min-width: 320px;
		background: var(--color-bg-secondary, #12121a);
		border-left: 1px solid var(--color-border, #2a2a3a);
		display: flex;
		flex-direction: column;
		overflow-y: auto;
		animation: slideIn 0.2s ease-out;
	}

	@keyframes slideIn {
		from {
			transform: translateX(20px);
			opacity: 0;
		}
		to {
			transform: translateX(0);
			opacity: 1;
		}
	}

	.panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 16px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.header-icon {
		width: 24px;
		height: 24px;
		border-radius: 6px;
		background: oklch(from var(--node-color, #ff6b35) l c h / 15%);
		color: var(--node-color, #ff6b35);
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.header-title {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.close-btn {
		width: 28px;
		height: 28px;
		border: none;
		background: transparent;
		border-radius: 6px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		transition:
			background 0.15s ease,
			color 0.15s ease;
	}

	.close-btn:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-text-primary, #e8e8ed);
	}

	.panel-body {
		padding: 16px;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.node-type-badge {
		display: inline-flex;
		align-self: flex-start;
		padding: 3px 10px;
		border-radius: 10px;
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid var(--color-border, #2a2a3a);
	}

	.badge-text {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary, #8888a0);
	}

	.field-group {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
</style>
