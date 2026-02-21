import { writable, derived, get } from 'svelte/store';
import type { Node, Edge } from '@xyflow/svelte';

export const nodes = writable<Node[]>([]);
export const edges = writable<Edge[]>([]);

/**
 * Whether the current canvas has unsaved changes relative to the last save.
 */
export const isDirty = writable<boolean>(false);

// Auto-save: debounce pipeline changes and persist to backend.
let _autoSaveTimer: ReturnType<typeof setTimeout> | null = null;
let _autoSaveEnabled = false;
const AUTO_SAVE_DELAY = 2000; // 2 seconds after last change

function _scheduleAutoSave(): void {
	if (!_autoSaveEnabled) return;
	isDirty.set(true);
	if (_autoSaveTimer) clearTimeout(_autoSaveTimer);
	_autoSaveTimer = setTimeout(() => {
		_performAutoSave();
	}, AUTO_SAVE_DELAY);
}

async function _performAutoSave(): Promise<void> {
	// Dynamically import to avoid circular dependency
	const { currentProject } = await import('$lib/stores/project');
	const { api } = await import('$lib/api/client');
	const proj = get(currentProject);
	if (!proj) return;
	const graph = getGraphSnapshot();
	const nodeCount = get(nodes).length;
	if (nodeCount === 0) return; // Don't auto-save empty canvas
	try {
		await api.projects.savePipeline(proj.name, 'main', graph);
		isDirty.set(false);
	} catch {
		// Silent failure — user can manually save
	}
}

/**
 * Enable auto-save subscriptions. Call once after stores are initialised.
 */
export function enableAutoSave(): void {
	if (_autoSaveEnabled) return;
	_autoSaveEnabled = true;
	nodes.subscribe(() => { _scheduleAutoSave(); });
	edges.subscribe(() => { _scheduleAutoSave(); });
}

/**
 * Temporarily suppress auto-save (e.g. during pipeline load from backend).
 * Returns a function to re-enable.
 */
export function suppressAutoSave(): () => void {
	_autoSaveEnabled = false;
	if (_autoSaveTimer) { clearTimeout(_autoSaveTimer); _autoSaveTimer = null; }
	return () => { _autoSaveEnabled = true; };
}

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

export type NodeExecutionState = 'idle' | 'running' | 'complete' | 'error' | 'skipped';

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
	// Set counter past any existing node IDs to avoid collisions with templates
	const currentNodes = get(nodes);
	let max = 0;
	for (const node of currentNodes) {
		const match = node.id.match(/-(\d+)$/);
		if (match) {
			const num = parseInt(match[1], 10);
			if (num > max) max = num;
		}
	}
	_nodeIdCounter = max;
}

export function addNode(type: string, label: string): void {
	_nodeIdCounter++;
	const id = `${type}-${_nodeIdCounter}`;
	const currentNodes = get(nodes);
	const selId = get(selectedNodeId);

	// Smart placement: position relative to selected or rightmost node
	let x = 250;
	let y = 200;
	const H_GAP = 280;
	const V_OFFSET = 0;

	if (selId) {
		const sel = currentNodes.find((n) => n.id === selId);
		if (sel) {
			x = sel.position.x + H_GAP;
			y = sel.position.y + V_OFFSET;
		}
	} else if (currentNodes.length > 0) {
		// Place after the rightmost node
		let maxX = -Infinity;
		let maxY = 200;
		for (const n of currentNodes) {
			if (n.position.x > maxX) {
				maxX = n.position.x;
				maxY = n.position.y;
			}
		}
		x = maxX + H_GAP;
		y = maxY;
	}

	// Avoid exact overlap if a node already occupies this position
	const occupied = currentNodes.some(
		(n) => Math.abs(n.position.x - x) < 20 && Math.abs(n.position.y - y) < 20
	);
	if (occupied) {
		y += 120;
	}

	nodes.update((n) => [
		...n,
		{
			id,
			type,
			position: { x, y },
			data: { label: `${label} ${_nodeIdCounter}`, origin: 'user' }
		}
	]);
}

export function updateNodeData(nodeId: string, key: string, value: unknown) {
	nodes.update((ns) =>
		ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, [key]: value } } : n))
	);
}
