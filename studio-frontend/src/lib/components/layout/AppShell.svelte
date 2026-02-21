<script lang="ts">
	import { get } from 'svelte/store';
	import { page } from '$app/stores';
	import TopBar from './TopBar.svelte';
	import CommandPalette from './CommandPalette.svelte';
	import ShortcutsModal from './ShortcutsModal.svelte';
	import SettingsModal from './SettingsModal.svelte';
	import FirstStartWizard from './FirstStartWizard.svelte';
	import ToastContainer from './ToastContainer.svelte';
	import ArchitectSidebar from '$lib/components/panels/ArchitectSidebar.svelte';
	import { commandPaletteOpen, architectSidebarOpen, shortcutsModalOpen, settingsModalOpen } from '$lib/stores/ui';
	import { nodes, edges, selectedNodeId, getGraphSnapshot, isDirty } from '$lib/stores/pipeline';
	import { debugPipeline } from '$lib/execution/bridge';
	import { startHealthPolling, stopHealthPolling } from '$lib/stores/connection';
	import { currentProject } from '$lib/stores/project';
	import { api } from '$lib/api/client';
	import { addToast } from '$lib/stores/notifications';
	import { onMount } from 'svelte';
	import { themeMode, cycleTheme } from '$lib/stores/theme';
	import { Sun, Moon, Monitor } from 'lucide-svelte';

	let { children } = $props();

	const isHomePage = $derived($page.url.pathname === '/' || $page.url.pathname === '/index.html');

	onMount(() => {
		startHealthPolling();

		// Global error handler: catch unhandled promise rejections to prevent UI freeze
		function handleUnhandledRejection(e: PromiseRejectionEvent) {
			e.preventDefault();
			const msg = e.reason instanceof Error ? e.reason.message : String(e.reason);
			addToast(`Unhandled error: ${msg}`, 'error');
			console.error('[AppShell] Unhandled rejection:', e.reason);
		}
		window.addEventListener('unhandledrejection', handleUnhandledRejection);

		return () => {
			stopHealthPolling();
			window.removeEventListener('unhandledrejection', handleUnhandledRejection);
		};
	});

	/**
	 * Returns true when the active element is a text-input field
	 * (input, textarea, or contenteditable) so that typing shortcuts
	 * should not fire.
	 */
	function isEditingText(): boolean {
		const el = document.activeElement;
		if (!el) return false;
		const tag = el.tagName.toLowerCase();
		if (tag === 'input' || tag === 'textarea') return true;
		if ((el as HTMLElement).isContentEditable) return true;
		return false;
	}

	function handleKeydown(e: KeyboardEvent) {
		// Only handle keyboard shortcuts in construct view
		if (isHomePage) return;

		const meta = e.metaKey || e.ctrlKey;

		// Cmd/Ctrl + S  —  save pipeline
		if (e.key === 's' && meta) {
			e.preventDefault();
			const proj = get(currentProject);
			if (proj) {
				api.projects.savePipeline(proj.name, 'main', getGraphSnapshot())
					.then(() => { isDirty.set(false); addToast('Pipeline saved', 'success'); })
					.catch(() => addToast('Failed to save pipeline', 'error'));
			}
			return;
		}

		// Cmd/Ctrl + ,  —  open settings
		if (e.key === ',' && meta) {
			e.preventDefault();
			settingsModalOpen.set(true);
			return;
		}

		// Cmd/Ctrl + K  —  toggle command palette
		if (e.key === 'k' && meta) {
			e.preventDefault();
			commandPaletteOpen.update((v) => !v);
			return;
		}

		// Cmd/Ctrl + Enter  —  run pipeline (delegates to TopBar's run dialog)
		if (e.key === 'Enter' && meta) {
			e.preventDefault();
			window.dispatchEvent(new CustomEvent('firefly:run-pipeline'));
			return;
		}

		// Cmd/Ctrl + Shift + D  —  toggle debug mode
		if (e.key === 'D' && meta && e.shiftKey) {
			e.preventDefault();
			debugPipeline(getGraphSnapshot());
			return;
		}

		// Cmd/Ctrl + /  —  toggle AI assistant sidebar
		if (e.key === '/' && meta) {
			e.preventDefault();
			architectSidebarOpen.update((v) => !v);
			return;
		}

		// Cmd/Ctrl + D  —  duplicate selected node (skip in text fields)
		if (e.key === 'd' && meta && !e.shiftKey) {
			if (isEditingText()) return;
			e.preventDefault();
			const selId = get(selectedNodeId);
			if (!selId) return;
			const currentNodes = get(nodes);
			const sourceNode = currentNodes.find((n) => n.id === selId);
			if (!sourceNode) return;
			const newId = `${sourceNode.type}-dup-${Date.now()}`;
			const offset = 40;
			nodes.update((ns) => [
				...ns,
				{
					...sourceNode,
					id: newId,
					position: {
						x: sourceNode.position.x + offset,
						y: sourceNode.position.y + offset
					},
					data: { ...sourceNode.data }
				}
			]);
			selectedNodeId.set(newId);
			return;
		}

		// Delete / Backspace  —  remove selected node (skip in text fields)
		if ((e.key === 'Delete' || e.key === 'Backspace') && !meta && !e.shiftKey && !e.altKey) {
			if (isEditingText()) return;
			const selId = get(selectedNodeId);
			if (!selId) return;
			e.preventDefault();
			nodes.update((ns) => ns.filter((n) => n.id !== selId));
			edges.update((es) => es.filter((edge) => edge.source !== selId && edge.target !== selId));
			selectedNodeId.set(null);
			return;
		}

		// ?  —  toggle shortcuts help modal (skip in text fields)
		if (e.key === '?' && !meta && !e.altKey) {
			if (isEditingText()) return;
			e.preventDefault();
			shortcutsModalOpen.update((v) => !v);
			return;
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="app-shell">
	<TopBar {isHomePage} />
	{#if isHomePage}
		<main class="app-content home-content">
			{@render children()}
		</main>
	{:else}
		<div class="app-body">
			<ArchitectSidebar />
			<main class="app-content">
				{@render children()}
			</main>
		</div>
	{/if}
	<footer class="app-footer">
		<span>Made with</span>
		<span class="heart">&#10084;</span>
		<span>by Firefly Software Solutions</span>
		<button class="theme-toggle" onclick={cycleTheme} title={`Theme: ${$themeMode}`}>
			{#if $themeMode === 'dark'}
				<Moon size={14} />
			{:else if $themeMode === 'light'}
				<Sun size={14} />
			{:else}
				<Monitor size={14} />
			{/if}
		</button>
	</footer>
</div>

<CommandPalette />
<ShortcutsModal />
<SettingsModal />
<FirstStartWizard />
<ToastContainer />

<style>
	.app-shell {
		display: flex;
		flex-direction: column;
		height: 100vh;
		width: 100vw;
		overflow: hidden;
		background: var(--color-bg-primary);
		color: var(--color-text-primary);
	}

	.home-content {
		flex: 1;
		min-height: 0;
		overflow: auto;
	}

	.app-body {
		display: flex;
		flex: 1;
		min-height: 0;
	}

	.app-content {
		flex: 1;
		min-width: 0;
		overflow: auto;
	}

	.app-footer {
		height: 34px;
		min-height: 34px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 4px;
		font-family: var(--font-sans);
		font-size: 11px;
		color: var(--color-text-secondary);
		background: var(--color-bg-secondary);
		border-top: 1px solid var(--color-border);
		opacity: 0.7;
		user-select: none;
	}

	.theme-toggle {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border-radius: 6px;
		border: 1px solid var(--color-border);
		background: var(--color-bg-elevated);
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: all 0.2s;
		margin-left: 8px;
	}

	.theme-toggle:hover {
		color: var(--color-text-primary);
		border-color: var(--color-accent);
	}

	.heart {
		color: #ef4444;
		display: inline-block;
		animation: heartbeat 1.2s ease-in-out infinite;
	}

	@keyframes heartbeat {
		0%, 100% { transform: scale(1); }
		15% { transform: scale(1.25); }
		30% { transform: scale(1); }
		45% { transform: scale(1.15); }
		60% { transform: scale(1); }
	}
</style>
