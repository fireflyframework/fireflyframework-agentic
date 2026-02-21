<script lang="ts">
	import { onMount } from 'svelte';

	let {
		text = '',
		description = '',
		shortcut = '',
		position = 'bottom' as 'top' | 'bottom' | 'left' | 'right',
		delay = 400,
		children,
	}: {
		text?: string;
		description?: string;
		shortcut?: string;
		position?: 'top' | 'bottom' | 'left' | 'right';
		delay?: number;
		children?: any;
	} = $props();

	let visible = $state(false);
	let tipEl: HTMLDivElement | undefined = $state(undefined);
	let wrapperEl: HTMLDivElement | undefined = $state(undefined);
	let timeoutId: ReturnType<typeof setTimeout> | null = null;
	let tipX = $state(0);
	let tipY = $state(0);

	function show() {
		timeoutId = setTimeout(() => {
			if (wrapperEl && tipEl) {
				positionTip();
			}
			visible = true;
		}, delay);
	}

	function hide() {
		if (timeoutId) {
			clearTimeout(timeoutId);
			timeoutId = null;
		}
		visible = false;
	}

	function positionTip() {
		if (!wrapperEl || !tipEl) return;
		const rect = wrapperEl.getBoundingClientRect();
		const tipRect = tipEl.getBoundingClientRect();
		const gap = 6;

		switch (position) {
			case 'top':
				tipX = rect.left + rect.width / 2 - tipRect.width / 2;
				tipY = rect.top - tipRect.height - gap;
				break;
			case 'bottom':
				tipX = rect.left + rect.width / 2 - tipRect.width / 2;
				tipY = rect.bottom + gap;
				break;
			case 'left':
				tipX = rect.left - tipRect.width - gap;
				tipY = rect.top + rect.height / 2 - tipRect.height / 2;
				break;
			case 'right':
				tipX = rect.right + gap;
				tipY = rect.top + rect.height / 2 - tipRect.height / 2;
				break;
		}

		// Clamp to viewport
		const pad = 8;
		tipX = Math.max(pad, Math.min(tipX, window.innerWidth - tipRect.width - pad));
		tipY = Math.max(pad, Math.min(tipY, window.innerHeight - tipRect.height - pad));
	}

	onMount(() => {
		return () => {
			if (timeoutId) clearTimeout(timeoutId);
		};
	});
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="tooltip-wrapper"
	bind:this={wrapperEl}
	onmouseenter={show}
	onmouseleave={hide}
	onfocusin={show}
	onfocusout={hide}
>
	{@render children?.()}
</div>

<div
	class="tooltip-portal"
	class:visible
	bind:this={tipEl}
	style="left: {tipX}px; top: {tipY}px;"
	role="tooltip"
>
	{#if text}
		<span class="tip-text">{text}</span>
	{/if}
	{#if shortcut}
		<kbd class="tip-kbd">{shortcut}</kbd>
	{/if}
	{#if description}
		<span class="tip-desc">{description}</span>
	{/if}
</div>

<style>
	.tooltip-wrapper {
		display: inline-flex;
	}

	.tooltip-portal {
		position: fixed;
		z-index: 99999;
		pointer-events: none;
		padding: 6px 10px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-overlay-medium);
		border-radius: 8px;
		box-shadow: var(--shadow-lg), 0 0 0 1px oklch(from var(--color-text-primary) l c h / 3%);
		display: flex;
		flex-direction: column;
		gap: 3px;
		max-width: 240px;
		opacity: 0;
		transform: translateY(2px);
		transition: opacity 0.15s ease, transform 0.15s ease;
	}

	.tooltip-portal.visible {
		opacity: 1;
		transform: translateY(0);
	}

	.tip-text {
		font-family: var(--font-sans, system-ui);
		font-size: 11px;
		font-weight: 600;
		color: var(--color-text-primary);
		white-space: nowrap;
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.tip-kbd {
		display: inline-flex;
		align-items: center;
		font-family: var(--font-mono, monospace);
		font-size: 10px;
		font-weight: 500;
		color: var(--color-text-secondary);
		background: var(--color-overlay-subtle);
		border: 1px solid var(--color-overlay-light);
		border-radius: 4px;
		padding: 1px 5px;
		line-height: 1.4;
	}

	.tip-desc {
		font-family: var(--font-sans, system-ui);
		font-size: 10px;
		font-weight: 400;
		color: var(--color-text-secondary);
		line-height: 1.4;
		white-space: normal;
	}
</style>
