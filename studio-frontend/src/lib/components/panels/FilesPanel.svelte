<script lang="ts">
	import { RefreshCw, File, Folder, FolderOpen, ChevronRight, ArrowLeft } from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { currentProject } from '$lib/stores/project';
	import type { FileEntry, FileContent } from '$lib/types/graph';

	let loading = $state(false);
	let files: FileEntry[] = $state([]);
	let selectedFile: string | null = $state(null);
	let fileContent: string = $state('');
	let loadingContent = $state(false);

	async function loadFiles() {
		const proj = $currentProject;
		if (!proj) return;
		loading = true;
		try {
			files = await api.files.list(proj.name);
		} catch {
			files = [];
		} finally {
			loading = false;
		}
	}

	async function openFile(path: string) {
		const proj = $currentProject;
		if (!proj) return;
		loadingContent = true;
		selectedFile = path;
		try {
			const result: FileContent = await api.files.read(proj.name, path);
			fileContent = result.content;
		} catch {
			fileContent = '// Failed to load file content';
		} finally {
			loadingContent = false;
		}
	}

	function closeFile() {
		selectedFile = null;
		fileContent = '';
	}

	function fileIcon(entry: FileEntry): typeof File {
		return entry.is_dir ? Folder : File;
	}

	function fileExtension(name: string): string {
		const parts = name.split('.');
		return parts.length > 1 ? parts[parts.length - 1] : '';
	}

	function extClass(name: string): string {
		const ext = fileExtension(name);
		switch (ext) {
			case 'py': return 'ext-python';
			case 'ts':
			case 'js': return 'ext-js';
			case 'json': return 'ext-json';
			case 'yaml':
			case 'yml': return 'ext-yaml';
			case 'md': return 'ext-md';
			default: return '';
		}
	}

	function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	$effect(() => {
		if ($currentProject) {
			selectedFile = null;
			fileContent = '';
			loadFiles();
		}
	});
</script>

<div class="panel">
	<div class="header">
		{#if selectedFile}
			<button class="back-btn" onclick={closeFile} title="Back to file list">
				<ArrowLeft size={13} />
			</button>
			<span class="file-path">{selectedFile}</span>
		{:else}
			<span class="title">Files</span>
		{/if}
		<button class="action-btn" onclick={loadFiles} title="Refresh">
			<RefreshCw size={13} />
		</button>
	</div>

	<div class="content">
		{#if selectedFile}
			{#if loadingContent}
				<div class="empty-state">
					<RefreshCw size={16} />
					<span>Loading file...</span>
				</div>
			{:else}
				<div class="code-viewer">
					<pre class="code-block"><code>{fileContent}</code></pre>
				</div>
			{/if}
		{:else if loading}
			<div class="empty-state">
				<RefreshCw size={16} />
				<span>Loading files...</span>
			</div>
		{:else if files.length === 0}
			<div class="empty-state">
				<FolderOpen size={16} />
				<span>No files in this project.</span>
			</div>
		{:else}
			<div class="file-list">
				{#each files as entry (entry.path)}
					{@const Icon = fileIcon(entry)}
					{#if entry.is_dir}
						<div class="file-item dir">
							<Folder size={13} />
							<span class="file-name">{entry.name}</span>
						</div>
					{:else}
						<button class="file-item" onclick={() => openFile(entry.path)}>
							<File size={13} />
							<span class="file-name">{entry.name}</span>
							{#if fileExtension(entry.name)}
								<span class="file-ext {extClass(entry.name)}">{fileExtension(entry.name)}</span>
							{/if}
							<span class="file-size">{formatSize(entry.size)}</span>
							<ChevronRight size={11} />
						</button>
					{/if}
				{/each}
			</div>
		{/if}
	</div>
</div>

<style>
	.panel {
		height: 100%;
		display: flex;
		flex-direction: column;
		background: var(--color-bg-primary, #0a0a12);
		font-family: var(--font-sans, system-ui, -apple-system, sans-serif);
	}

	.header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 12px;
		height: 40px;
		min-height: 40px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
		gap: 8px;
	}

	.title {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.file-path {
		font-size: 11px;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		color: var(--color-text-primary, #e8e8ed);
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.back-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 26px;
		height: 26px;
		border: none;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
		flex-shrink: 0;
	}

	.back-btn:hover {
		background: oklch(from var(--color-text-primary) l c h / 5%);
		color: var(--color-text-primary, #e8e8ed);
	}

	.action-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 26px;
		height: 26px;
		border: none;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
		flex-shrink: 0;
	}

	.action-btn:hover {
		background: oklch(from var(--color-text-primary) l c h / 5%);
		color: var(--color-text-primary, #e8e8ed);
	}

	.content {
		flex: 1;
		overflow: hidden;
		display: flex;
		flex-direction: column;
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

	/* File list */
	.file-list {
		flex: 1;
		overflow-y: auto;
		padding: 4px 0;
	}

	.file-list::-webkit-scrollbar {
		width: 6px;
	}

	.file-list::-webkit-scrollbar-track {
		background: transparent;
	}

	.file-list::-webkit-scrollbar-thumb {
		background: var(--color-border, #2a2a3a);
		border-radius: 3px;
	}

	.file-item {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 5px 12px;
		border: none;
		background: transparent;
		color: var(--color-text-secondary, #8888a0);
		font-size: 12px;
		cursor: pointer;
		width: 100%;
		text-align: left;
		transition: background 0.12s ease, color 0.12s ease;
		font-family: var(--font-sans, system-ui, -apple-system, sans-serif);
	}

	.file-item:hover {
		background: var(--color-bg-secondary, #12121a);
		color: var(--color-text-primary, #e8e8ed);
	}

	.file-item.dir {
		color: var(--color-accent, #ff6b35);
		cursor: default;
	}

	.file-name {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.file-ext {
		font-size: 9px;
		font-weight: 600;
		padding: 1px 4px;
		border-radius: 2px;
		background: var(--color-overlay-subtle);
		color: var(--color-text-secondary, #8888a0);
		flex-shrink: 0;
		text-transform: uppercase;
	}

	.ext-python {
		background: rgba(53, 114, 165, 0.2);
		color: #5b9bd5;
	}

	.ext-js {
		background: rgba(240, 219, 79, 0.15);
		color: #f0db4f;
	}

	.ext-json {
		background: var(--color-overlay-subtle);
		color: var(--color-text-secondary, #8888a0);
	}

	.ext-yaml {
		background: rgba(203, 171, 81, 0.15);
		color: #cbab51;
	}

	.ext-md {
		background: rgba(59, 130, 246, 0.15);
		color: #3b82f6;
	}

	.file-size {
		font-size: 10px;
		opacity: 0.5;
		flex-shrink: 0;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
	}

	/* Code viewer */
	.code-viewer {
		flex: 1;
		overflow: auto;
	}

	.code-viewer::-webkit-scrollbar {
		width: 6px;
		height: 6px;
	}

	.code-viewer::-webkit-scrollbar-track {
		background: transparent;
	}

	.code-viewer::-webkit-scrollbar-thumb {
		background: var(--color-border, #2a2a3a);
		border-radius: 3px;
	}

	.code-block {
		margin: 0;
		padding: 12px;
		background: var(--color-bg-secondary, #12121a);
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		font-size: 12px;
		line-height: 1.6;
		color: var(--color-text-primary, #e8e8ed);
		white-space: pre;
		tab-size: 4;
		min-height: 100%;
		box-sizing: border-box;
	}

	.code-block code {
		font-family: inherit;
	}
</style>
