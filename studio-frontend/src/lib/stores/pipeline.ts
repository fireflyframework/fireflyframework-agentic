import { writable, derived, get } from 'svelte/store';
import type { Node, Edge } from '@xyflow/svelte';

export const nodes = writable<Node[]>([]);
export const edges = writable<Edge[]>([]);

/**
 * Snapshot the current canvas graph into the format expected by the backend
 * GraphModel (nodes + edges + metadata).
 */
export function getGraphSnapshot(): object {
	const currentNodes = get(nodes);
	const currentEdges = get(edges);
	return {
		nodes: currentNodes.map((n) => ({
			id: n.id,
			type: n.type ?? 'pipeline_step',
			label: n.data?.label ?? n.id,
			position: n.position,
			data: n.data ?? {},
			width: n.measured?.width ?? n.width ?? null,
			height: n.measured?.height ?? n.height ?? null
		})),
		edges: currentEdges.map((e) => ({
			id: e.id,
			source: e.source,
			target: e.target,
			source_handle: e.sourceHandle ?? 'output',
			target_handle: e.targetHandle ?? 'input',
			label: e.label ?? null
		})),
		metadata: {}
	};
}
export const selectedNodeId = writable<string | null>(null);

export const selectedNode = derived(
	[nodes, selectedNodeId],
	([$nodes, $id]) => ($id ? $nodes.find((n) => n.id === $id) ?? null : null)
);

export type NodeExecutionState = 'idle' | 'running' | 'complete' | 'error';

export const nodeStates = writable<Map<string, NodeExecutionState>>(new Map());

export function setNodeState(nodeId: string, state: NodeExecutionState) {
	nodeStates.update((map) => {
		const next = new Map(map);
		next.set(nodeId, state);
		return next;
	});
	updateNodeData(nodeId, '_executionState', state);
}

export function clearNodeStates() {
	nodeStates.update((map) => {
		const next = new Map<string, NodeExecutionState>();
		for (const [id] of map) {
			next.set(id, 'idle');
		}
		return next;
	});
	// Also clear _executionState from all nodes
	nodes.update((ns) =>
		ns.map((n) => ({ ...n, data: { ...n.data, _executionState: 'idle' } }))
	);
}

let _nodeIdCounter = 0;

export function resetNodeCounter(): void {
	_nodeIdCounter = 0;
}

export function addNode(type: string, label: string): void {
	_nodeIdCounter++;
	const id = `${type}-${_nodeIdCounter}`;
	nodes.update((n) => [
		...n,
		{
			id,
			type,
			position: { x: 250 + Math.random() * 200, y: 100 + Math.random() * 200 },
			data: { label: `${label} ${_nodeIdCounter}` }
		}
	]);
}

export function updateNodeData(nodeId: string, key: string, value: unknown) {
	nodes.update((ns) =>
		ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, [key]: value } } : n))
	);
}
