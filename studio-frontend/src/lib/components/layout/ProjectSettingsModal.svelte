<script lang="ts">
	import { X } from 'lucide-svelte';
	import { projectSettingsModalOpen } from '$lib/stores/ui';
	import { currentProject, renameProject, updateProjectDescription } from '$lib/stores/project';
	import { addToast } from '$lib/stores/notifications';

	let dialogEl: HTMLDialogElement | undefined = $state(undefined);
	let name = $state('');
	let description = $state('');
	let saving = $state(false);

	// Sync dialog open/close with store
	$effect(() => {
		if ($projectSettingsModalOpen && dialogEl && !dialogEl.open) {
			name = $currentProject?.name ?? '';
			description = $currentProject?.description ?? '';
			dialogEl.showModal();
		} else if (!$projectSettingsModalOpen && dialogEl?.open) {
			dialogEl.close();
		}
	});

	function handleClose() {
		projectSettingsModalOpen.set(false);
	}

	async function handleSave() {
		const proj = $currentProject;
		if (!proj || saving) return;
		saving = true;
		try {
			const trimmedName = name.trim();
			const trimmedDesc = description.trim();
			if (trimmedName && trimmedName !== proj.name) {
				await renameProject(proj.name, trimmedName);
			}
			if (trimmedDesc !== (proj.description ?? '')) {
				await updateProjectDescription(trimmedName || proj.name, trimmedDesc);
			}
			addToast('Project settings saved', 'success');
			handleClose();
		} catch (err: any) {
			addToast(err?.message || 'Failed to save project settings', 'error');
		} finally {
			saving = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			handleClose();
		}
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<dialog
	bind:this={dialogEl}
	class="project-settings-dialog"
	onclose={handleClose}
	onkeydown={handleKeydown}
	onclick={(e) => { if (e.target === dialogEl) handleClose(); }}
>
	<div class="dialog-content">
		<div class="dialog-header">
			<h3 class="dialog-title">Project Settings</h3>
			<button class="dialog-close" onclick={handleClose}>
				<X size={16} />
			</button>
		</div>
		<div class="dialog-body">
			<label class="field-label" for="proj-name">Name</label>
			<input
				id="proj-name"
				class="field-input"
				type="text"
				bind:value={name}
				placeholder="Project name"
				onkeydown={(e) => { if (e.key === 'Enter') handleSave(); }}
			/>
			<label class="field-label" for="proj-desc">Description</label>
			<textarea
				id="proj-desc"
				class="field-textarea"
				bind:value={description}
				placeholder="Optional description..."
				rows={3}
			></textarea>
		</div>
		<div class="dialog-actions">
			<button class="btn-cancel" onclick={handleClose}>Cancel</button>
			<button class="btn-save" onclick={handleSave} disabled={saving || !name.trim()}>
				{saving ? 'Saving...' : 'Save'}
			</button>
		</div>
	</div>
</dialog>

<style>
	.project-settings-dialog {
		border: none;
		border-radius: 14px;
		background: var(--color-bg-secondary);
		color: var(--color-text-primary);
		padding: 0;
		width: 420px;
		max-width: 90vw;
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
	}

	.project-settings-dialog::backdrop {
		background: rgba(0, 0, 0, 0.5);
	}

	.dialog-content {
		display: flex;
		flex-direction: column;
	}

	.dialog-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 20px 12px;
		border-bottom: 1px solid var(--color-border);
	}

	.dialog-title {
		font-size: 15px;
		font-weight: 600;
		margin: 0;
		color: var(--color-text-primary);
	}

	.dialog-close {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: none;
		background: transparent;
		border-radius: 6px;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.dialog-close:hover {
		background: var(--color-overlay-subtle);
		color: var(--color-text-primary);
	}

	.dialog-body {
		padding: 16px 20px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.field-label {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-secondary);
		margin-top: 4px;
	}

	.field-input,
	.field-textarea {
		width: 100%;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		padding: 8px 12px;
		font-family: var(--font-sans);
		font-size: 13px;
		color: var(--color-text-primary);
		outline: none;
		box-sizing: border-box;
		transition: border-color 0.15s;
	}

	.field-input:focus,
	.field-textarea:focus {
		border-color: var(--color-accent);
	}

	.field-input::placeholder,
	.field-textarea::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.5;
	}

	.field-textarea {
		resize: vertical;
		min-height: 60px;
	}

	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 12px 20px 16px;
		border-top: 1px solid var(--color-border);
	}

	.btn-cancel {
		background: transparent;
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 7px 14px;
		font-size: 12px;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s;
	}

	.btn-cancel:hover {
		background: var(--color-bg-elevated);
		color: var(--color-text-primary);
	}

	.btn-save {
		background: var(--color-accent);
		border: none;
		border-radius: 6px;
		padding: 7px 16px;
		font-size: 12px;
		font-weight: 600;
		color: white;
		cursor: pointer;
		transition: opacity 0.15s;
	}

	.btn-save:hover:not(:disabled) {
		opacity: 0.9;
	}

	.btn-save:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
</style>
