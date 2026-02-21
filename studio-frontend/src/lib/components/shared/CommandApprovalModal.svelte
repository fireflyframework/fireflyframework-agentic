<script lang="ts">
	import ShieldAlert from 'lucide-svelte/icons/shield-alert';
	import Check from 'lucide-svelte/icons/check';
	import X from 'lucide-svelte/icons/x';

	let { command, level, onApprove, onDeny }: {
		command: string;
		level: string;
		onApprove: () => void;
		onDeny: () => void;
	} = $props();
</script>

<div class="modal-overlay" onclick={onDeny} role="dialog" aria-modal="true">
	<div class="modal" onclick={(e) => e.stopPropagation()}>
		<div class="modal-header">
			<ShieldAlert size={20} color="#f59e0b" />
			<h3>Command Approval Required</h3>
		</div>
		<p class="modal-desc">Smith wants to execute a <strong>{level}</strong> command:</p>
		<pre class="command-preview">{command}</pre>
		<div class="modal-actions">
			<button class="btn-deny" onclick={onDeny}>
				<X size={16} /> Deny
			</button>
			<button class="btn-approve" onclick={onApprove}>
				<Check size={16} /> Approve
			</button>
		</div>
	</div>
</div>

<style>
	.modal-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 10000;
		backdrop-filter: blur(4px);
	}
	.modal {
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 16px;
		padding: 24px;
		max-width: 480px;
		width: 90%;
		box-shadow:
			0 0 0 1px oklch(from var(--color-text-primary) l c h / 4%),
			var(--shadow-lg);
	}
	.modal-header {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 12px;
	}
	.modal-header h3 {
		margin: 0;
		font-size: 1rem;
		color: var(--color-text-primary);
	}
	.modal-desc {
		font-size: 0.875rem;
		color: var(--color-text-secondary);
		margin: 0 0 12px;
	}
	.command-preview {
		background: var(--color-code-bg);
		border: 1px solid var(--color-code-border);
		border-radius: 8px;
		padding: 12px;
		font-size: 0.85rem;
		color: #22c55e;
		margin: 0 0 16px;
		overflow-x: auto;
	}
	.modal-actions {
		display: flex;
		gap: 12px;
		justify-content: flex-end;
	}
	.btn-deny, .btn-approve {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 20px;
		border-radius: 8px;
		border: none;
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 500;
	}
	.btn-deny {
		background: var(--color-bg-hover);
		color: var(--color-text-secondary);
	}
	.btn-deny:hover { background: var(--color-error); color: #fff; }
	.btn-approve {
		background: #22c55e;
		color: #fff;
	}
	.btn-approve:hover { background: #16a34a; }
</style>
