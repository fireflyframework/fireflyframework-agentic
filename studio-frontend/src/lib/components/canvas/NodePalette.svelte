<script lang="ts">
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
		Antenna,
		Download
	} from 'lucide-svelte';
	import { addNode } from '$lib/stores/pipeline';
	import type { Component } from 'svelte';

	interface PaletteItem {
		type: string;
		label: string;
		icon: Component<{ size?: number }>;
		color: string;
	}

	const palette: PaletteItem[] = [
		{ type: 'input', label: 'Input', icon: Antenna, color: '#10b981' },
		{ type: 'output', label: 'Output', icon: Download, color: '#3b82f6' },
		{ type: 'agent', label: 'Agent', icon: Bot, color: '#6366f1' },
		{ type: 'tool', label: 'Tool', icon: Wrench, color: '#8b5cf6' },
		{ type: 'reasoning', label: 'Reasoning', icon: Brain, color: '#ec4899' },
		{ type: 'condition', label: 'Condition', icon: CircleDot, color: '#f59e0b' },
		{ type: 'memory', label: 'Memory', icon: Database, color: '#06b6d4' },
		{ type: 'validator', label: 'Validator', icon: Shield, color: '#f59e0b' },
		{ type: 'custom_code', label: 'Code', icon: Code, color: '#3b82f6' },
		{ type: 'fan_out', label: 'Fan Out', icon: GitFork, color: '#64748b' },
		{ type: 'fan_in', label: 'Fan In', icon: GitMerge, color: '#64748b' }
	];

	function iconBg(hex: string): string {
		const r = parseInt(hex.slice(1, 3), 16);
		const g = parseInt(hex.slice(3, 5), 16);
		const b = parseInt(hex.slice(5, 7), 16);
		return `rgba(${r}, ${g}, ${b}, 0.15)`;
	}
</script>

<aside class="node-palette">
	<div class="palette-header">
		<span class="palette-title">Components</span>
	</div>
	<div class="palette-items">
		{#each palette as item}
			<button
				class="palette-item"
				onclick={() => addNode(item.type, item.label)}
				title={`Add ${item.label} node`}
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
		{/each}
	</div>
</aside>

<style>
	.node-palette {
		width: 192px;
		min-width: 192px;
		background: var(--color-bg-secondary, #12121a);
		border-right: 1px solid var(--color-border, #2a2a3a);
		display: flex;
		flex-direction: column;
		overflow-y: auto;
	}
	.palette-header {
		padding: 16px 14px 8px;
	}
	.palette-title {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary, #8888a0);
	}
	.palette-items {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 4px 8px;
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
		transition:
			background 0.15s ease,
			transform 0.1s ease;
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
</style>
