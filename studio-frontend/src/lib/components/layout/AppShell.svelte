<script lang="ts">
	import { get } from 'svelte/store';
	import TopBar from './TopBar.svelte';
	import Sidebar from './Sidebar.svelte';
	import CommandPalette from './CommandPalette.svelte';
	import ShortcutsModal from './ShortcutsModal.svelte';
	import SettingsModal from './SettingsModal.svelte';
	import FirstStartWizard from './FirstStartWizard.svelte';
	import { commandPaletteOpen, bottomPanelOpen, bottomPanelTab, shortcutsModalOpen, settingsModalOpen } from '$lib/stores/ui';
	import { nodes, edges, selectedNodeId, getGraphSnapshot } from '$lib/stores/pipeline';
	import { runPipeline, debugPipeline } from '$lib/execution/bridge';

	let { children } = $props();

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
		const meta = e.metaKey || e.ctrlKey;

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

		// Cmd/Ctrl + Enter  —  run pipeline
		if (e.key === 'Enter' && meta) {
			e.preventDefault();
			runPipeline(getGraphSnapshot());
			return;
		}

		// Cmd/Ctrl + Shift + D  —  toggle debug mode
		if (e.key === 'D' && meta && e.shiftKey) {
			e.preventDefault();
			debugPipeline(getGraphSnapshot());
			return;
		}

		// Cmd/Ctrl + /  —  toggle AI assistant (bottom panel chat tab)
		if (e.key === '/' && meta) {
			e.preventDefault();
			const isOpen = get(bottomPanelOpen);
			const currentTab = get(bottomPanelTab);
			if (isOpen && currentTab === 'chat') {
				// If already showing chat, close the panel
				bottomPanelOpen.set(false);
			} else {
				// Open panel and switch to chat
				bottomPanelOpen.set(true);
				bottomPanelTab.set('chat');
			}
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
	<TopBar />
	<div class="app-body">
		<Sidebar />
		<main class="app-content">
			{@render children()}
		</main>
	</div>
</div>

<CommandPalette />
<ShortcutsModal />
<SettingsModal />
<FirstStartWizard />

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
</style>
