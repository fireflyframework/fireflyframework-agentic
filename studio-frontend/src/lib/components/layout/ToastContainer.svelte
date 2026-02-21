<script lang="ts">
	import { toasts, removeToast } from '$lib/stores/notifications';
	import { fly } from 'svelte/transition';
	import Check from 'lucide-svelte/icons/check';
	import AlertCircle from 'lucide-svelte/icons/alert-circle';
	import AlertTriangle from 'lucide-svelte/icons/alert-triangle';
	import Info from 'lucide-svelte/icons/info';
	import X from 'lucide-svelte/icons/x';

	const iconMap = {
		success: Check,
		error: AlertCircle,
		warning: AlertTriangle,
		info: Info
	};

	const colorMap = {
		success: 'var(--color-success)',
		error: 'var(--color-error)',
		warning: 'var(--color-warning)',
		info: 'var(--color-info)'
	};
</script>

{#if $toasts.length > 0}
	<div class="toast-container">
		{#each $toasts as toast (toast.id)}
			<div
				class="toast"
				style:--toast-color={colorMap[toast.type]}
				transition:fly={{ y: 16, duration: 200 }}
				role="alert"
			>
				<span class="toast-icon">
					<svelte:component this={iconMap[toast.type]} size={16} />
				</span>
				<span class="toast-message">{toast.message}</span>
				<button class="toast-close" onclick={() => removeToast(toast.id)}>
					<X size={14} />
				</button>
			</div>
		{/each}
	</div>
{/if}

<style>
	.toast-container {
		position: fixed;
		bottom: 24px;
		right: 24px;
		z-index: 20000;
		display: flex;
		flex-direction: column-reverse;
		gap: 8px;
		max-width: 400px;
	}

	.toast {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 12px 16px;
		background: var(--color-bg-secondary);
		border: 1px solid oklch(from var(--toast-color) l c h / 30%);
		border-left: 3px solid var(--toast-color);
		border-radius: 8px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
		animation: toast-in 0.2s ease-out;
	}

	@keyframes toast-in {
		from { opacity: 0; transform: translateY(8px) scale(0.96); }
		to { opacity: 1; transform: translateY(0) scale(1); }
	}

	.toast-icon {
		display: flex;
		align-items: center;
		color: var(--toast-color);
		flex-shrink: 0;
	}

	.toast-message {
		flex: 1;
		font-family: var(--font-sans);
		font-size: 13px;
		color: var(--color-text-primary);
		line-height: 1.4;
	}

	.toast-close {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		background: none;
		border: none;
		border-radius: 4px;
		color: var(--color-text-secondary);
		cursor: pointer;
		flex-shrink: 0;
		transition: background 0.15s, color 0.15s;
	}

	.toast-close:hover {
		background: var(--color-overlay-subtle);
		color: var(--color-text-primary);
	}
</style>
