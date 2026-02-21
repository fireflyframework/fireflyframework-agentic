import { writable } from 'svelte/store';

export interface Toast {
	id: string;
	message: string;
	type: 'success' | 'error' | 'warning' | 'info';
	duration: number;
}

export const toasts = writable<Toast[]>([]);

let _counter = 0;

export function addToast(
	message: string,
	type: Toast['type'] = 'info',
	duration = 5000
): string {
	const id = `toast-${++_counter}`;
	toasts.update((t) => [...t, { id, message, type, duration }]);

	if (duration > 0) {
		setTimeout(() => removeToast(id), duration);
	}
	return id;
}

export function removeToast(id: string): void {
	toasts.update((t) => t.filter((toast) => toast.id !== id));
}
