import { StudioWebSocket } from '$lib/api/websocket';
import { isRunning, isDebugging, activeNodes, pushExecutionEvent } from '$lib/stores/execution';
import { setNodeState, clearNodeStates } from '$lib/stores/pipeline';
import type { ExecutionEvent } from '$lib/types/graph';

let ws: StudioWebSocket | null = null;
const unsubscribers: Array<() => void> = [];

/**
 * Connect to the execution WebSocket and wire up event listeners
 * that update the Svelte stores.
 */
export function connectExecution(): void {
	if (ws) return;

	ws = new StudioWebSocket('/ws/execution');
	ws.connect();

	unsubscribers.push(
		ws.on('node_start', (event: ExecutionEvent) => {
			if (event.node_id) {
				activeNodes.update((set) => {
					const next = new Set(set);
					next.add(event.node_id!);
					return next;
				});
				setNodeState(event.node_id, 'running');
			}
			pushExecutionEvent(event);
		})
	);

	unsubscribers.push(
		ws.on('node_complete', (event: ExecutionEvent) => {
			if (event.node_id) {
				activeNodes.update((set) => {
					const next = new Set(set);
					next.delete(event.node_id!);
					return next;
				});
				setNodeState(event.node_id, 'complete');
			}
			pushExecutionEvent(event);
		})
	);

	unsubscribers.push(
		ws.on('node_error', (event: ExecutionEvent) => {
			if (event.node_id) {
				activeNodes.update((set) => {
					const next = new Set(set);
					next.delete(event.node_id!);
					return next;
				});
				setNodeState(event.node_id, 'error');
			}
			pushExecutionEvent(event);
		})
	);

	unsubscribers.push(
		ws.on('pipeline_complete', (event: ExecutionEvent) => {
			activeNodes.set(new Set());
			isRunning.set(false);
			isDebugging.set(false);
			pushExecutionEvent(event);
		})
	);

	unsubscribers.push(
		ws.on('pipeline_result', (event: ExecutionEvent) => {
			activeNodes.set(new Set());
			isRunning.set(false);
			isDebugging.set(false);
			pushExecutionEvent(event);
		})
	);

	// Reset state on WebSocket close/error to prevent stuck UI
	unsubscribers.push(
		ws.on('_close', () => {
			activeNodes.set(new Set());
			isRunning.set(false);
			isDebugging.set(false);
		})
	);
	unsubscribers.push(
		ws.on('_error', () => {
			activeNodes.set(new Set());
			isRunning.set(false);
			isDebugging.set(false);
		})
	);
}

/**
 * Disconnect from the execution WebSocket and clean up listeners.
 */
export function disconnectExecution(): void {
	for (const unsub of unsubscribers) unsub();
	unsubscribers.length = 0;
	ws?.disconnect();
	ws = null;
}

/**
 * Send a "run" action with the current graph to the backend.
 */
export function runPipeline(graph: object, inputs?: string): boolean {
	if (!ws) {
		console.warn('[bridge] Cannot run pipeline: execution WebSocket not connected');
		return false;
	}
	clearNodeStates();
	isRunning.set(true);
	ws.send({ action: 'run', graph, inputs: inputs ?? null });
	return true;
}

/**
 * Send a "debug" action with the current graph to the backend.
 */
export function debugPipeline(graph: object, inputs?: string): boolean {
	if (!ws) {
		console.warn('[bridge] Cannot debug pipeline: execution WebSocket not connected');
		return false;
	}
	clearNodeStates();
	isDebugging.set(true);
	ws.send({ action: 'debug', graph, inputs: inputs ?? null });
	return true;
}
