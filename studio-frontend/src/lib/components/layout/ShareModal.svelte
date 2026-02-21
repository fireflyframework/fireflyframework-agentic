<script lang="ts">
	import Link from 'lucide-svelte/icons/link';
	import Copy from 'lucide-svelte/icons/copy';
	import Check from 'lucide-svelte/icons/check';
	import Globe from 'lucide-svelte/icons/globe';
	import Loader from 'lucide-svelte/icons/loader';
	import { api } from '$lib/api/client';
	import { tunnelUrl, tunnelActive } from '$lib/stores/runtime';
	import { currentProject } from '$lib/stores/project';
	import { addToast } from '$lib/stores/notifications';

	let { open = false, onclose }: { open: boolean; onclose: () => void } = $props();

	let loading = $state(false);
	let copied = $state(false);
	let tUrl = $derived($tunnelUrl);
	let tActive = $derived($tunnelActive);
	let projectName = $derived($currentProject?.name ?? '');

	let apiEndpoint = $derived(tUrl ? `${tUrl}/api/projects/${projectName}/run` : null);

	$effect(() => {
		if (open) {
			refreshStatus();
		}
	});

	async function refreshStatus() {
		try {
			const status = await api.tunnel.status();
			tunnelActive.set(status.active);
			tunnelUrl.set(status.url);
		} catch {
			// Ignore – server might not support tunnel yet
		}
	}

	async function startTunnel() {
		loading = true;
		try {
			const result = await api.tunnel.start();
			tunnelActive.set(true);
			tunnelUrl.set(result.url);
			addToast('Tunnel started', 'success');
		} catch {
			addToast('Failed to start tunnel', 'error');
		} finally {
			loading = false;
		}
	}

	async function stopTunnel() {
		loading = true;
		try {
			await api.tunnel.stop();
			tunnelActive.set(false);
			tunnelUrl.set(null);
			addToast('Tunnel stopped', 'success');
		} catch {
			addToast('Failed to stop tunnel', 'error');
		} finally {
			loading = false;
		}
	}

	async function copyToClipboard(text: string) {
		try {
			await navigator.clipboard.writeText(text);
			copied = true;
			setTimeout(() => { copied = false; }, 2000);
		} catch {
			addToast('Failed to copy', 'error');
		}
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) onclose();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			onclose();
		}
	}
</script>

{#if open}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="share-backdrop" onclick={handleBackdropClick} onkeydown={handleKeydown}>
		<div class="share-modal" role="dialog" aria-modal="true" aria-label="Share">
			<!-- Header -->
			<div class="share-header">
				<div class="share-title">
					<Link size={18} />
					<span>Share & Expose</span>
				</div>
				<kbd class="share-close-hint">ESC</kbd>
			</div>

			<!-- Body -->
			<div class="share-body">
				<!-- Tunnel status -->
				<div class="tunnel-section">
					<div class="tunnel-status-row">
						<div class="tunnel-status-info">
							<span class="tunnel-dot" class:tunnel-dot-active={tActive}></span>
							<span class="tunnel-label">{tActive ? 'Tunnel Active' : 'Tunnel Inactive'}</span>
						</div>
						<button
							class="tunnel-toggle-btn"
							class:tunnel-stop={tActive}
							disabled={loading}
							onclick={tActive ? stopTunnel : startTunnel}
						>
							{#if loading}
								<span class="spin-icon"><Loader size={13} /></span>
								<span>{tActive ? 'Stopping...' : 'Starting...'}</span>
							{:else}
								<Globe size={13} />
								<span>{tActive ? 'Stop Tunnel' : 'Start Tunnel'}</span>
							{/if}
						</button>
					</div>

					<p class="tunnel-desc">
						Expose your local Firefly Studio via a Cloudflare Tunnel. Anyone with the URL can interact with your pipeline.
					</p>
				</div>

				{#if tActive && tUrl}
					<!-- Tunnel URL -->
					<div class="url-section">
						<label class="url-label">Tunnel URL</label>
						<div class="url-row">
							<code class="url-value">{tUrl}</code>
							<button class="copy-btn" onclick={() => copyToClipboard(tUrl!)} title="Copy URL">
								{#if copied}
									<Check size={13} />
								{:else}
									<Copy size={13} />
								{/if}
							</button>
						</div>
					</div>

					<!-- API endpoint -->
					{#if apiEndpoint}
						<div class="url-section">
							<label class="url-label">Project API Endpoint</label>
							<div class="url-row">
								<code class="url-value">{apiEndpoint}</code>
								<button class="copy-btn" onclick={() => copyToClipboard(apiEndpoint!)} title="Copy endpoint">
									<Copy size={13} />
								</button>
							</div>
							<p class="url-hint">Send a POST request with a JSON body to run your pipeline remotely.</p>
						</div>
					{/if}
				{/if}
			</div>

			<!-- Footer -->
			<div class="share-footer">
				<button class="btn-close" onclick={onclose}>Close</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.share-backdrop {
		position: fixed;
		inset: 0;
		z-index: 9999;
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding-top: 8vh;
		animation: share-backdrop-in 0.12s ease-out;
	}

	@keyframes share-backdrop-in {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	.share-modal {
		width: 520px;
		max-width: 90vw;
		max-height: 82vh;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 14px;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		box-shadow:
			0 0 0 1px rgba(255, 255, 255, 0.04),
			0 20px 60px rgba(0, 0, 0, 0.5),
			0 0 100px oklch(from var(--color-accent) l c h / 4%);
		animation: share-slide-in 0.15s ease-out;
	}

	@keyframes share-slide-in {
		from { opacity: 0; transform: translateY(-8px) scale(0.98); }
		to { opacity: 1; transform: translateY(0) scale(1); }
	}

	.share-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 20px;
		border-bottom: 1px solid var(--color-border);
	}

	.share-title {
		display: flex;
		align-items: center;
		gap: 10px;
		font-family: var(--font-sans);
		font-size: 15px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.share-close-hint {
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

	.share-body {
		flex: 1;
		overflow-y: auto;
		padding: 16px 20px;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	/* Tunnel section */
	.tunnel-section {
		border: 1px solid var(--color-border);
		border-radius: 8px;
		padding: 14px 16px;
		background: var(--color-bg-primary);
	}

	.tunnel-status-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 8px;
	}

	.tunnel-status-info {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.tunnel-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--color-text-secondary);
		flex-shrink: 0;
		transition: background 0.3s;
	}

	.tunnel-dot.tunnel-dot-active {
		background: var(--color-success);
		box-shadow: 0 0 8px color-mix(in srgb, var(--color-success) 50%, transparent);
	}

	.tunnel-label {
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.tunnel-toggle-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 12px;
		border: none;
		border-radius: 6px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		background: var(--color-accent);
		color: white;
		transition: opacity 0.15s;
	}

	.tunnel-toggle-btn:hover:not(:disabled) {
		opacity: 0.9;
	}

	.tunnel-toggle-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.tunnel-toggle-btn.tunnel-stop {
		background: rgba(239, 68, 68, 0.15);
		color: var(--color-error);
		border: 1px solid rgba(239, 68, 68, 0.3);
	}

	.tunnel-toggle-btn.tunnel-stop:hover:not(:disabled) {
		background: rgba(239, 68, 68, 0.25);
		opacity: 1;
	}

	.tunnel-desc {
		font-family: var(--font-sans);
		font-size: 11px;
		color: var(--color-text-secondary);
		margin: 0;
		opacity: 0.7;
		line-height: 1.5;
	}

	/* URL sections */
	.url-section {
		border: 1px solid var(--color-border);
		border-radius: 8px;
		padding: 14px 16px;
		background: var(--color-bg-primary);
	}

	.url-label {
		display: block;
		font-family: var(--font-sans);
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-secondary);
		margin-bottom: 8px;
	}

	.url-row {
		display: flex;
		align-items: center;
		gap: 8px;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 8px 10px;
	}

	.url-value {
		flex: 1;
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--color-accent);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}

	.copy-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: none;
		background: var(--color-bg-elevated);
		border-radius: 4px;
		color: var(--color-text-secondary);
		cursor: pointer;
		flex-shrink: 0;
		transition: background 0.15s, color 0.15s;
	}

	.copy-btn:hover {
		background: var(--color-border);
		color: var(--color-text-primary);
	}

	.url-hint {
		font-family: var(--font-sans);
		font-size: 11px;
		color: var(--color-text-secondary);
		margin: 8px 0 0;
		opacity: 0.6;
	}

	/* Footer */
	.share-footer {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		padding: 14px 20px;
		border-top: 1px solid var(--color-border);
	}

	.btn-close {
		background: transparent;
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 7px 16px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s;
	}

	.btn-close:hover {
		background: var(--color-bg-elevated);
	}

	.spin-icon {
		display: flex;
		align-items: center;
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		from { transform: rotate(0deg); }
		to { transform: rotate(360deg); }
	}
</style>
