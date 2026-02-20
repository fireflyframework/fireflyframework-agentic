<script lang="ts">
	import Play from 'lucide-svelte/icons/play';
	import Bug from 'lucide-svelte/icons/bug';
	import Settings from 'lucide-svelte/icons/settings';
	import Bot from 'lucide-svelte/icons/bot';
	import Loader from 'lucide-svelte/icons/loader';
	import { isRunning, isDebugging } from '$lib/stores/execution';
	import { runPipeline, debugPipeline } from '$lib/execution/bridge';
	import { getGraphSnapshot } from '$lib/stores/pipeline';
	import { settingsModalOpen } from '$lib/stores/ui';
	import logo from '$lib/assets/favicon.svg';

	let running = $derived($isRunning);
	let debugging = $derived($isDebugging);
	let busy = $derived(running || debugging);

	function handleRun() {
		runPipeline(getGraphSnapshot());
	}

	function handleDebug() {
		debugPipeline(getGraphSnapshot());
	}
</script>

<header class="top-bar">
	<div class="top-bar-left">
		<img src={logo} alt="Firefly Studio" class="brand-logo" />
		<span class="brand">Firefly Studio</span>
		<span class="separator">/</span>
		<button class="project-selector">
			<span class="project-name">my-agent</span>
			<svg width="12" height="12" viewBox="0 0 12 12" fill="none">
				<path d="M3 5L6 8L9 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
			</svg>
		</button>
	</div>

	<div class="top-bar-right">
		<button class="btn-run" class:btn-run-active={running} disabled={busy} onclick={handleRun} title="Run">
			{#if running}
				<span class="spin-icon"><Loader size={14} /></span>
				<span>Running...</span>
				<span class="pulse-dot"></span>
			{:else}
				<Play size={14} />
				<span>Run</span>
			{/if}
		</button>
		<button class="btn-icon" class:btn-debug-active={debugging} disabled={busy} onclick={handleDebug} title="Debug">
			<Bug size={16} />
			{#if debugging}
				<span class="pulse-dot debug-dot"></span>
			{/if}
		</button>
		<div class="divider"></div>
		<button class="btn-icon" title="Settings" onclick={() => settingsModalOpen.set(true)}>
			<Settings size={16} />
		</button>
		<button class="btn-icon" title="AI Assistant">
			<Bot size={16} />
		</button>
	</div>
</header>

<style>
	.top-bar {
		height: 48px;
		min-height: 48px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 12px;
		background: var(--color-bg-secondary);
		border-bottom: 1px solid var(--color-border);
		user-select: none;
	}

	.top-bar-left {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.brand-logo {
		width: 24px;
		height: 24px;
		border-radius: 5px;
	}

	.brand {
		font-family: var(--font-sans);
		font-size: 14px;
		font-weight: 600;
		color: var(--color-accent);
		letter-spacing: -0.01em;
	}

	.separator {
		color: var(--color-text-secondary);
		font-size: 14px;
		opacity: 0.5;
	}

	.project-selector {
		display: flex;
		align-items: center;
		gap: 4px;
		background: transparent;
		border: none;
		color: var(--color-text-primary);
		font-family: var(--font-mono);
		font-size: 13px;
		padding: 4px 8px;
		border-radius: 4px;
		cursor: pointer;
		transition: background 0.15s;
	}

	.project-selector:hover {
		background: var(--color-bg-elevated);
	}

	.project-name {
		opacity: 0.9;
	}

	.top-bar-right {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.btn-run {
		display: flex;
		align-items: center;
		gap: 6px;
		background: var(--color-accent);
		color: white;
		border: none;
		padding: 5px 12px;
		border-radius: 6px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		transition: opacity 0.15s, background 0.3s ease;
	}

	.btn-run:hover:not(:disabled) {
		opacity: 0.9;
	}

	.btn-run:disabled {
		cursor: not-allowed;
		opacity: 0.7;
	}

	.btn-run-active {
		background: var(--color-success);
	}

	.btn-icon {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		background: transparent;
		border: none;
		color: var(--color-text-secondary);
		border-radius: 6px;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.btn-icon:hover:not(:disabled) {
		background: var(--color-bg-elevated);
		color: var(--color-text-primary);
	}

	.btn-icon:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}

	.btn-debug-active {
		color: var(--color-warning);
	}

	.divider {
		width: 1px;
		height: 20px;
		background: var(--color-border);
		margin: 0 4px;
	}

	.pulse-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: white;
		animation: pulse-indicator 1s ease-in-out infinite;
	}

	.debug-dot {
		position: absolute;
		top: 4px;
		right: 4px;
		width: 5px;
		height: 5px;
		background: var(--color-warning);
	}

	@keyframes pulse-indicator {
		0%, 100% {
			opacity: 0.4;
		}
		50% {
			opacity: 1;
		}
	}

	.spin-icon {
		display: flex;
		align-items: center;
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		from {
			transform: rotate(0deg);
		}
		to {
			transform: rotate(360deg);
		}
	}
</style>
