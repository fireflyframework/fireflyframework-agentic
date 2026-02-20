import { writable } from 'svelte/store';
import type { ExecutionEvent, Checkpoint } from '$lib/types/graph';

export const isRunning = writable(false);
export const isDebugging = writable(false);
export const executionEvents = writable<ExecutionEvent[]>([]);
export const activeNodes = writable<Set<string>>(new Set());
export const checkpoints = writable<Checkpoint[]>([]);

/** Push an event into the store, stamping it with the current time if it lacks a timestamp. */
export function pushExecutionEvent(event: Omit<ExecutionEvent, 'timestamp'> & { timestamp?: string }) {
	const stamped: ExecutionEvent = {
		...event,
		timestamp: event.timestamp ?? new Date().toISOString()
	};
	executionEvents.update((events) => [...events, stamped]);
}
