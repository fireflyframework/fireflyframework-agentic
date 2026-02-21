<script lang="ts">
	import { shortcutsModalOpen } from '$lib/stores/ui';
	import Keyboard from 'lucide-svelte/icons/keyboard';

	const isMac = typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform);
	const mod = isMac ? '\u2318' : 'Ctrl';

	interface ShortcutEntry {
		keys: string;
		description: string;
	}

	interface ShortcutGroup {
		category: string;
		shortcuts: ShortcutEntry[];
	}

	const groups: ShortcutGroup[] = [
		{
			category: 'General',
			shortcuts: [
				{ keys: `${mod} + K`, description: 'Open command palette' },
				{ keys: `${mod} + ,`, description: 'Open settings' },
				{ keys: `${mod} + /`, description: 'Toggle AI assistant' },
				{ keys: '?', description: 'Show keyboard shortcuts' },
				{ keys: 'Esc', description: 'Close modal / palette' }
			]
		},
		{
			category: 'Pipeline',
			shortcuts: [
				{ keys: `${mod} + Enter`, description: 'Run pipeline' },
				{ keys: `${mod} + Shift + D`, description: 'Toggle debug mode' }
			]
		},
		{
			category: 'Canvas',
			shortcuts: [
				{ keys: 'Delete / Backspace', description: 'Remove selected node' },
				{ keys: `${mod} + D`, description: 'Duplicate selected node' },
				{ keys: 'Space (hold)', description: 'Pan canvas' },
				{ keys: `${mod} + +`, description: 'Zoom in' },
			{ keys: `${mod} + -`, description: 'Zoom out' }
			]
		}
	];

	function close() {
		shortcutsModalOpen.set(false);
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) {
			close();
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	}
</script>

{#if $shortcutsModalOpen}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="shortcuts-backdrop" onclick={handleBackdropClick} onkeydown={handleKeydown}>
		<div class="shortcuts-modal" role="dialog" aria-modal="true" aria-label="Keyboard Shortcuts">
			<div class="shortcuts-header">
				<div class="shortcuts-title">
					<Keyboard size={18} />
					<span>Keyboard Shortcuts</span>
				</div>
				<kbd class="shortcuts-close-hint">ESC</kbd>
			</div>

			<div class="shortcuts-body">
				{#each groups as group}
					<div class="shortcuts-group">
						<div class="shortcuts-category">{group.category}</div>
						{#each group.shortcuts as shortcut}
							<div class="shortcuts-row">
								<span class="shortcuts-description">{shortcut.description}</span>
								<span class="shortcuts-keys">
									{#each shortcut.keys.split(' + ') as part, i}
										{#if i > 0}
											<span class="shortcuts-separator">+</span>
										{/if}
										<kbd class="shortcuts-kbd">{part.trim()}</kbd>
									{/each}
								</span>
							</div>
						{/each}
					</div>
				{/each}
			</div>
		</div>
	</div>
{/if}

<style>
	.shortcuts-backdrop {
		position: fixed;
		inset: 0;
		z-index: 9999;
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding-top: 12vh;
		animation: shortcuts-backdrop-in 0.12s ease-out;
	}

	@keyframes shortcuts-backdrop-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	.shortcuts-modal {
		width: 480px;
		max-width: 90vw;
		max-height: 70vh;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		box-shadow:
			0 0 0 1px oklch(from var(--color-text-primary) l c h / 4%),
			var(--shadow-lg),
			0 0 80px color-mix(in srgb, var(--color-accent) 4%, transparent);
		animation: shortcuts-slide-in 0.15s ease-out;
	}

	@keyframes shortcuts-slide-in {
		from {
			opacity: 0;
			transform: translateY(-8px) scale(0.98);
		}
		to {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}

	.shortcuts-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 20px;
		border-bottom: 1px solid var(--color-border);
	}

	.shortcuts-title {
		display: flex;
		align-items: center;
		gap: 10px;
		font-family: var(--font-sans);
		font-size: 15px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.shortcuts-close-hint {
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 500;
		color: var(--color-text-secondary);
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 4px;
		padding: 2px 6px;
		line-height: 1.4;
	}

	.shortcuts-body {
		flex: 1;
		overflow-y: auto;
		padding: 8px 20px 20px;
	}

	.shortcuts-group {
		margin-top: 12px;
	}

	.shortcuts-category {
		font-family: var(--font-sans);
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-text-secondary);
		padding: 4px 0 8px;
		user-select: none;
	}

	.shortcuts-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 7px 0;
		border-bottom: 1px solid oklch(from var(--color-text-primary) l c h / 4%);
	}

	.shortcuts-row:last-child {
		border-bottom: none;
	}

	.shortcuts-description {
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 400;
		color: var(--color-text-primary);
	}

	.shortcuts-keys {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}

	.shortcuts-kbd {
		font-family: var(--font-mono);
		font-size: 11px;
		font-weight: 500;
		color: var(--color-text-secondary);
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 4px;
		padding: 2px 7px;
		line-height: 1.4;
		white-space: nowrap;
	}

	.shortcuts-separator {
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--color-text-secondary);
		opacity: 0.5;
	}
</style>
