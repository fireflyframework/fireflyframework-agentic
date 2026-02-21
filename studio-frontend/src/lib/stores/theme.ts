import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';

export type ThemeMode = 'dark' | 'light' | 'system';

const STORAGE_KEY = 'fireflyStudio:theme';

function getInitialTheme(): ThemeMode {
	if (!browser) return 'dark';
	const stored = localStorage.getItem(STORAGE_KEY);
	if (stored === 'dark' || stored === 'light' || stored === 'system') return stored;
	return 'dark';
}

export const themeMode = writable<ThemeMode>(getInitialTheme());

export const resolvedTheme = derived(themeMode, ($mode) => {
	if ($mode !== 'system') return $mode;
	if (!browser) return 'dark';
	return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
});

export function initTheme(): void {
	if (!browser) return;

	themeMode.subscribe(($mode) => {
		localStorage.setItem(STORAGE_KEY, $mode);
	});

	resolvedTheme.subscribe(($resolved) => {
		document.documentElement.setAttribute('data-theme', $resolved);
	});

	const mq = window.matchMedia('(prefers-color-scheme: dark)');
	mq.addEventListener('change', () => {
		themeMode.update((m) => m);
	});
}

export function cycleTheme(): void {
	themeMode.update((current) => {
		if (current === 'dark') return 'light';
		if (current === 'light') return 'system';
		return 'dark';
	});
}
