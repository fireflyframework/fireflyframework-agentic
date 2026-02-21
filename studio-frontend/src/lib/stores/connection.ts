import { writable, derived } from 'svelte/store';

export type ConnectionState = 'connected' | 'disconnected' | 'checking';

const _state = writable<ConnectionState>('checking');
const _version = writable<string>('');

export const connectionState = { subscribe: _state.subscribe };
export const serverVersion = { subscribe: _version.subscribe };
export const isConnected = derived(_state, (s) => s === 'connected');

let intervalId: ReturnType<typeof setInterval> | null = null;

async function checkHealth(): Promise<void> {
	try {
		const resp = await fetch('/api/health', { signal: AbortSignal.timeout(3000) });
		if (resp.ok) {
			const data = await resp.json();
			_state.set('connected');
			_version.set(data.version ?? '');
		} else {
			_state.set('disconnected');
		}
	} catch {
		_state.set('disconnected');
	}
}

export function startHealthPolling(intervalMs = 10_000): void {
	if (intervalId) return;
	checkHealth();
	intervalId = setInterval(checkHealth, intervalMs);
}

export function stopHealthPolling(): void {
	if (intervalId) {
		clearInterval(intervalId);
		intervalId = null;
	}
}
