import { writable } from 'svelte/store';

export const tunnelUrl = writable<string | null>(null);
export const tunnelActive = writable(false);
export const runtimeStatus = writable<'stopped' | 'starting' | 'running' | 'error'>('stopped');
