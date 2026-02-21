<script lang="ts">
	import { onMount } from 'svelte';
	import { Star, RotateCcw, RefreshCw, GitCommit } from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { currentProject, selectProject } from '$lib/stores/project';
	import { addToast } from '$lib/stores/notifications';

	interface VersionEntry {
		sha: string;
		message: string;
		timestamp: string;
		bookmarked: boolean;
	}

	let versions: VersionEntry[] = $state([]);
	let loading = $state(false);
	let confirmRestore: string | null = $state(null);

	async function loadHistory() {
		const proj = $currentProject;
		if (!proj) return;
		loading = true;
		try {
			versions = await api.projects.getHistory(proj.name);
		} catch {
			versions = [];
		} finally {
			loading = false;
		}
	}

	async function bookmark(sha: string) {
		const proj = $currentProject;
		if (!proj) return;
		try {
			await api.projects.bookmarkVersion(proj.name, sha, `bookmark-${sha.slice(0, 7)}`);
			await loadHistory();
			addToast('Version bookmarked', 'success');
		} catch {
			addToast('Failed to bookmark', 'error');
		}
	}

	async function restore(sha: string) {
		const proj = $currentProject;
		if (!proj) return;
		try {
			await api.projects.restoreVersion(proj.name, sha);
			confirmRestore = null;
			// Reload the pipeline onto the canvas from the restored files
			await selectProject(proj);
			await loadHistory();
			addToast('Restored to version ' + sha.slice(0, 7), 'success');
		} catch {
			addToast('Failed to restore', 'error');
		}
	}

	function timeAgo(timestamp: string): string {
		const now = Date.now();
		const then = new Date(timestamp).getTime();
		const diff = now - then;
		const minutes = Math.floor(diff / 60000);
		if (minutes < 1) return 'just now';
		if (minutes < 60) return `${minutes}m ago`;
		const hours = Math.floor(minutes / 60);
		if (hours < 24) return `${hours}h ago`;
		const days = Math.floor(hours / 24);
		return `${days}d ago`;
	}

	$effect(() => {
		if ($currentProject) loadHistory();
	});
</script>

<div class="history-panel">
	<div class="header">
		<span class="title">Version History</span>
		<button class="refresh-btn" onclick={loadHistory} title="Refresh history" disabled={loading}>
			<RefreshCw size={13} />
		</button>
	</div>

	<div class="versions-list">
		{#if loading}
			<div class="empty-state">
				<RefreshCw size={16} class="spin" />
				<span>Loading history...</span>
			</div>
		{:else if versions.length === 0}
			<div class="empty-state">
				<GitCommit size={16} />
				<span>No version history yet</span>
			</div>
		{:else}
			{#each versions as version (version.sha)}
				<div class="version-item" class:confirming={confirmRestore === version.sha}>
					<div class="version-icon">
						<GitCommit size={14} />
					</div>
					<div class="version-info">
						<span class="version-sha">{version.sha.slice(0, 7)}</span>
						<span class="version-message">{version.message}</span>
						<span class="version-time">{timeAgo(version.timestamp)}</span>
					</div>
					<div class="version-actions">
						<button
							class="action-btn bookmark-btn"
							class:bookmarked={version.bookmarked}
							onclick={() => bookmark(version.sha)}
							title={version.bookmarked ? 'Bookmarked' : 'Bookmark this version'}
						>
							<Star size={13} fill={version.bookmarked ? 'currentColor' : 'none'} />
						</button>
						<button
							class="action-btn restore-btn"
							class:visible={confirmRestore === version.sha}
							onclick={() => (confirmRestore = version.sha)}
							title="Restore to this version"
						>
							<RotateCcw size={13} />
						</button>
					</div>
					{#if confirmRestore === version.sha}
						<div class="confirm-bar">
							<span class="confirm-text">Restore to {version.sha.slice(0, 7)}?</span>
							<button class="confirm-btn confirm-yes" onclick={() => restore(version.sha)}>
								Restore
							</button>
							<button class="confirm-btn confirm-no" onclick={() => (confirmRestore = null)}>
								Cancel
							</button>
						</div>
					{/if}
				</div>
			{/each}
		{/if}
	</div>
</div>

<style>
	.history-panel {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--color-bg-primary);
		font-family: var(--font-sans, system-ui, -apple-system, sans-serif);
	}

	.header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 12px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
	}

	.title {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.refresh-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		border: none;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
	}

	.refresh-btn:hover {
		background: oklch(from var(--color-text-primary) l c h / 5%);
		color: var(--color-text-primary, #e8e8ed);
	}

	.refresh-btn:disabled {
		opacity: 0.4;
		cursor: default;
	}

	.versions-list {
		flex: 1;
		overflow-y: auto;
		padding: 4px 0;
	}

	.versions-list::-webkit-scrollbar {
		width: 6px;
	}

	.versions-list::-webkit-scrollbar-track {
		background: transparent;
	}

	.versions-list::-webkit-scrollbar-thumb {
		background: var(--color-border, #2a2a3a);
		border-radius: 3px;
	}

	.empty-state {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		height: 100%;
		color: var(--color-text-secondary, #8888a0);
		font-size: 12px;
		opacity: 0.6;
	}

	.version-item {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 12px;
		margin: 0 4px;
		border-radius: 6px;
		position: relative;
		flex-wrap: wrap;
		transition: background 0.12s ease;
	}

	.version-item:hover {
		background: var(--color-bg-secondary, #12121a);
	}

	.version-item.confirming {
		background: var(--color-bg-elevated, #1a1a2a);
	}

	.version-icon {
		display: flex;
		align-items: center;
		color: var(--color-text-secondary, #8888a0);
		flex-shrink: 0;
	}

	.version-info {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: baseline;
		gap: 8px;
	}

	.version-sha {
		font-family: var(--font-mono, 'SF Mono', 'Fira Code', monospace);
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
		flex-shrink: 0;
	}

	.version-message {
		font-size: 12px;
		color: var(--color-text-primary, #e8e8ed);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}

	.version-time {
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.7;
		flex-shrink: 0;
		margin-left: auto;
	}

	.version-actions {
		display: flex;
		align-items: center;
		gap: 2px;
		flex-shrink: 0;
	}

	.action-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		border: none;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
	}

	.action-btn:hover {
		background: var(--color-overlay-light);
		color: var(--color-text-primary, #e8e8ed);
	}

	.bookmark-btn.bookmarked {
		color: var(--color-accent, #ff6b35);
	}

	.restore-btn {
		opacity: 0;
		transition: opacity 0.15s ease, background 0.15s ease, color 0.15s ease;
	}

	.version-item:hover .restore-btn,
	.restore-btn.visible {
		opacity: 1;
	}

	.confirm-bar {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 6px 0 2px 22px;
	}

	.confirm-text {
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
	}

	.confirm-btn {
		padding: 3px 10px;
		border: none;
		border-radius: 4px;
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s ease;
	}

	.confirm-yes {
		background: var(--color-accent, #ff6b35);
		color: #fff;
	}

	.confirm-yes:hover {
		filter: brightness(1.1);
	}

	.confirm-no {
		background: var(--color-overlay-subtle);
		color: var(--color-text-secondary, #8888a0);
	}

	.confirm-no:hover {
		background: var(--color-overlay-medium);
		color: var(--color-text-primary, #e8e8ed);
	}
</style>
