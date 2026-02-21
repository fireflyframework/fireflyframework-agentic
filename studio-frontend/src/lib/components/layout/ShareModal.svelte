<script lang="ts">
	import Link from 'lucide-svelte/icons/link';
	import Copy from 'lucide-svelte/icons/copy';
	import Check from 'lucide-svelte/icons/check';
	import Globe from 'lucide-svelte/icons/globe';
	import Loader from 'lucide-svelte/icons/loader';
	import ExternalLink from 'lucide-svelte/icons/external-link';
	import Terminal from 'lucide-svelte/icons/terminal';
	import AlertTriangle from 'lucide-svelte/icons/alert-triangle';
	import { api } from '$lib/api/client';
	import { tunnelUrl, tunnelActive } from '$lib/stores/runtime';
	import { currentProject } from '$lib/stores/project';
	import { addToast } from '$lib/stores/notifications';

	let { open = false, onclose }: { open: boolean; onclose: () => void } = $props();

	let loading = $state(false);
	let copiedField = $state<string | null>(null);
	let tUrl = $derived($tunnelUrl);
	let tActive = $derived($tunnelActive);
	let projectName = $derived($currentProject?.name ?? '');
	let notInstalled = $state(false);

	let apiEndpoint = $derived(tUrl ? `${tUrl}/api/projects/${projectName}/run` : null);
	let studioUrl = $derived(tUrl ? tUrl : null);

	let curlExample = $derived(apiEndpoint
		? `curl -X POST ${apiEndpoint} \\
  -H "Content-Type: application/json" \\
  -d '{"input": "Hello, world!"}'`
		: ''
	);

	$effect(() => {
		if (open) {
			refreshStatus();
		}
	});

	async function refreshStatus() {
		try {
			const status = await api.tunnel.status() as any;
			tunnelActive.set(status.active);
			tunnelUrl.set(status.url);
			notInstalled = status.cloudflared_installed === false;
		} catch {
			// Server might not support tunnel yet
		}
	}

	async function startTunnel() {
		loading = true;
		notInstalled = false;
		try {
			const result = await api.tunnel.start();
			if ((result as any).error) {
				// cloudflared not installed — backend returns error object instead of throwing
				notInstalled = true;
				addToast('cloudflared is not installed', 'error');
			} else {
				tunnelActive.set(true);
				tunnelUrl.set(result.url);
				addToast('Tunnel started — your studio is now publicly accessible', 'success');
			}
		} catch (err: any) {
			const msg = err?.message || err?.detail || '';
			if (msg.includes('not installed')) {
				notInstalled = true;
				addToast('cloudflared is not installed', 'error');
			} else {
				addToast(msg || 'Failed to start tunnel', 'error');
			}
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

	async function copyToClipboard(text: string, field: string) {
		try {
			await navigator.clipboard.writeText(text);
			copiedField = field;
			setTimeout(() => { copiedField = null; }, 2000);
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
		<div class="share-modal" role="dialog" aria-modal="true" aria-label="Share & Expose">
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
				<!-- Tunnel status card -->
				<div class="tunnel-card">
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
						Expose your local Firefly Studio via a Cloudflare Tunnel.
						Anyone with the URL can access your studio and run your pipelines remotely.
					</p>

					{#if tActive && tUrl}
						<div class="tunnel-active-badge">
							<Globe size={11} />
							<span>Publicly accessible</span>
						</div>
					{/if}
				</div>

				<!-- Not installed warning -->
				{#if notInstalled}
					<div class="install-card">
						<div class="install-header">
							<AlertTriangle size={14} />
							<span>cloudflared not installed</span>
						</div>
						<p class="install-desc">
							Cloudflare Tunnel requires the <code>cloudflared</code> CLI tool.
							Install it to enable public tunnel sharing.
						</p>
						<div class="install-commands">
							<div class="install-cmd">
								<span class="cmd-label">macOS (Homebrew)</span>
								<div class="cmd-row">
									<code>brew install cloudflared</code>
									<button class="copy-btn-sm" onclick={() => copyToClipboard('brew install cloudflared', 'brew')}>
										{#if copiedField === 'brew'}<Check size={11} />{:else}<Copy size={11} />{/if}
									</button>
								</div>
							</div>
							<div class="install-cmd">
								<span class="cmd-label">Linux</span>
								<div class="cmd-row">
									<code>curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared</code>
									<button class="copy-btn-sm" onclick={() => copyToClipboard('curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared', 'linux')}>
										{#if copiedField === 'linux'}<Check size={11} />{:else}<Copy size={11} />{/if}
									</button>
								</div>
							</div>
						</div>
						<a class="install-link" href="https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" target="_blank" rel="noopener">
							<ExternalLink size={12} />
							<span>View all download options</span>
						</a>
					</div>
				{/if}

				<!-- URLs section — only when tunnel is active -->
				{#if tActive && tUrl}
					<div class="urls-section">
						<!-- Studio URL -->
						<div class="url-card">
							<div class="url-header">
								<Globe size={13} />
								<label class="url-label">Public Studio URL</label>
							</div>
							<div class="url-row">
								<code class="url-value">{studioUrl}</code>
								<button class="copy-btn" onclick={() => copyToClipboard(studioUrl!, 'studio')}>
									{#if copiedField === 'studio'}<Check size={13} />{:else}<Copy size={13} />{/if}
								</button>
							</div>
							<p class="url-hint">Open this URL in any browser to access your studio remotely.</p>
						</div>

						<!-- API Endpoint -->
						{#if apiEndpoint}
							<div class="url-card">
								<div class="url-header">
									<Terminal size={13} />
									<label class="url-label">Pipeline API Endpoint</label>
								</div>
								<div class="url-row">
									<code class="url-value">{apiEndpoint}</code>
									<button class="copy-btn" onclick={() => copyToClipboard(apiEndpoint!, 'api')}>
										{#if copiedField === 'api'}<Check size={13} />{:else}<Copy size={13} />{/if}
									</button>
								</div>
								<p class="url-hint">Send a POST request with JSON to run your pipeline remotely.</p>
							</div>

							<!-- Usage example -->
							<div class="usage-card">
								<div class="usage-header">
									<Terminal size={12} />
									<span>Usage Example</span>
									<button class="copy-btn-sm" onclick={() => copyToClipboard(curlExample, 'curl')}>
										{#if copiedField === 'curl'}<Check size={11} />{:else}<Copy size={11} />{/if}
									</button>
								</div>
								<pre class="usage-code">{curlExample}</pre>
							</div>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Footer -->
			<div class="share-footer">
				{#if tActive}
					<span class="footer-warn">Anyone with this URL can access your studio</span>
				{/if}
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
		width: 560px;
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
		gap: 14px;
	}

	/* ===== Tunnel card ===== */
	.tunnel-card {
		border: 1px solid var(--color-border);
		border-radius: 10px;
		padding: 16px;
		background: var(--color-bg-primary);
	}

	.tunnel-status-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 10px;
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
		box-shadow: 0 0 8px oklch(from var(--color-success) l c h / 50%);
		animation: tunnel-glow 2s ease-in-out infinite;
	}

	@keyframes tunnel-glow {
		0%, 100% { box-shadow: 0 0 6px oklch(from var(--color-success) l c h / 30%); }
		50% { box-shadow: 0 0 12px oklch(from var(--color-success) l c h / 60%); }
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
		padding: 6px 14px;
		border: none;
		border-radius: 8px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		background: var(--color-accent);
		color: white;
		transition: opacity 0.15s, transform 0.1s;
	}

	.tunnel-toggle-btn:hover:not(:disabled) {
		opacity: 0.92;
		transform: translateY(-0.5px);
	}

	.tunnel-toggle-btn:active:not(:disabled) {
		transform: scale(0.97);
	}

	.tunnel-toggle-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.tunnel-toggle-btn.tunnel-stop {
		background: rgba(239, 68, 68, 0.12);
		color: var(--color-error);
		border: 1px solid rgba(239, 68, 68, 0.25);
	}

	.tunnel-toggle-btn.tunnel-stop:hover:not(:disabled) {
		background: rgba(239, 68, 68, 0.22);
		opacity: 1;
	}

	.tunnel-desc {
		font-family: var(--font-sans);
		font-size: 12px;
		color: var(--color-text-secondary);
		margin: 0;
		line-height: 1.55;
	}

	.tunnel-active-badge {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		margin-top: 10px;
		padding: 4px 10px;
		background: oklch(from var(--color-success) l c h / 10%);
		border: 1px solid oklch(from var(--color-success) l c h / 20%);
		border-radius: 6px;
		font-family: var(--font-sans);
		font-size: 11px;
		font-weight: 500;
		color: var(--color-success);
	}

	/* ===== Install card ===== */
	.install-card {
		border: 1px solid rgba(245, 158, 11, 0.25);
		border-radius: 10px;
		padding: 16px;
		background: rgba(245, 158, 11, 0.04);
	}

	.install-header {
		display: flex;
		align-items: center;
		gap: 8px;
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 600;
		color: #f59e0b;
		margin-bottom: 8px;
	}

	.install-desc {
		font-family: var(--font-sans);
		font-size: 12px;
		color: var(--color-text-secondary);
		margin: 0 0 12px;
		line-height: 1.55;
	}

	.install-desc code {
		font-family: var(--font-mono);
		font-size: 11px;
		background: rgba(255, 255, 255, 0.06);
		padding: 1px 5px;
		border-radius: 4px;
		color: var(--color-text-primary);
	}

	.install-commands {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-bottom: 10px;
	}

	.install-cmd {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.cmd-label {
		font-family: var(--font-sans);
		font-size: 10px;
		font-weight: 600;
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.cmd-row {
		display: flex;
		align-items: center;
		gap: 6px;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 6px 8px;
	}

	.cmd-row code {
		flex: 1;
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--color-text-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.copy-btn-sm {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		border: none;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary);
		cursor: pointer;
		flex-shrink: 0;
		transition: background 0.15s, color 0.15s;
	}

	.copy-btn-sm:hover {
		background: rgba(255, 255, 255, 0.08);
		color: var(--color-text-primary);
	}

	.install-link {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-family: var(--font-sans);
		font-size: 11px;
		color: var(--color-accent);
		text-decoration: none;
		transition: opacity 0.15s;
	}

	.install-link:hover {
		opacity: 0.8;
	}

	/* ===== URL sections ===== */
	.urls-section {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.url-card {
		border: 1px solid var(--color-border);
		border-radius: 10px;
		padding: 14px 16px;
		background: var(--color-bg-primary);
	}

	.url-header {
		display: flex;
		align-items: center;
		gap: 6px;
		color: var(--color-text-secondary);
		margin-bottom: 8px;
	}

	.url-label {
		font-family: var(--font-sans);
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-secondary);
	}

	.url-row {
		display: flex;
		align-items: center;
		gap: 8px;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 8px;
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
		border-radius: 6px;
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
		line-height: 1.5;
	}

	/* ===== Usage example ===== */
	.usage-card {
		border: 1px solid var(--color-border);
		border-radius: 10px;
		padding: 12px 14px;
		background: var(--color-bg-primary);
	}

	.usage-header {
		display: flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-sans);
		font-size: 11px;
		font-weight: 600;
		color: var(--color-text-secondary);
		margin-bottom: 8px;
	}

	.usage-header .copy-btn-sm {
		margin-left: auto;
	}

	.usage-code {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--color-text-primary);
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 10px 12px;
		margin: 0;
		overflow-x: auto;
		white-space: pre;
		line-height: 1.6;
	}

	/* ===== Footer ===== */
	.share-footer {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 12px;
		padding: 14px 20px;
		border-top: 1px solid var(--color-border);
	}

	.footer-warn {
		font-family: var(--font-sans);
		font-size: 11px;
		color: #f59e0b;
		opacity: 0.8;
		margin-right: auto;
	}

	.btn-close {
		background: transparent;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		padding: 7px 18px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.btn-close:hover {
		background: var(--color-bg-elevated);
		color: var(--color-text-primary);
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
