<script lang="ts">
	import { onMount } from 'svelte';
	import {
		FolderOpen,
		FileText,
		FileCode,
		ChevronRight,
		ChevronDown,
		File,
		Loader2,
		AlertCircle,
		RefreshCw
	} from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { currentProject } from '$lib/stores/project';
	import type { FileEntry, FileContent } from '$lib/types/graph';

	interface FileNode {
		name: string;
		path: string;
		type: 'folder' | 'file';
		size: number;
		children?: FileNode[];
		expanded?: boolean;
	}

	let fileTree: FileNode[] = $state([]);
	let selectedFile: string | null = $state(null);
	let fileContent: FileContent | null = $state(null);
	let treeLoading: boolean = $state(true);
	let treeError: string | null = $state(null);
	let contentLoading: boolean = $state(false);
	let contentError: string | null = $state(null);
	let projectName: string | null = $state(null);

	/**
	 * Build a nested tree structure from a flat list of file entries.
	 */
	function buildTree(entries: FileEntry[]): FileNode[] {
		const root: FileNode[] = [];
		const dirMap = new Map<string, FileNode>();

		// First pass: create all directory nodes
		for (const entry of entries) {
			if (entry.is_dir) {
				const node: FileNode = {
					name: entry.name,
					path: entry.path,
					type: 'folder',
					size: 0,
					children: [],
					expanded: false
				};
				dirMap.set(entry.path, node);
			}
		}

		// Second pass: place all entries into their parent directories
		for (const entry of entries) {
			const node: FileNode = entry.is_dir
				? dirMap.get(entry.path)!
				: {
						name: entry.name,
						path: entry.path,
						type: 'file',
						size: entry.size
					};

			const parts = entry.path.split('/');
			if (parts.length === 1) {
				// Top-level entry
				root.push(node);
			} else {
				// Find parent directory
				const parentPath = parts.slice(0, -1).join('/');
				const parent = dirMap.get(parentPath);
				if (parent && parent.children) {
					parent.children.push(node);
				} else {
					// Fallback: place at root if parent not found
					root.push(node);
				}
			}
		}

		return root;
	}

	async function fetchFiles() {
		if (!projectName) return;
		try {
			treeLoading = true;
			treeError = null;
			const entries = await api.files.list(projectName);
			fileTree = buildTree(entries);
		} catch (e) {
			treeError = e instanceof Error ? e.message : 'Failed to load files';
			fileTree = [];
		} finally {
			treeLoading = false;
		}
	}

	async function loadFileContent(path: string) {
		if (!projectName) return;
		try {
			contentLoading = true;
			contentError = null;
			selectedFile = path;
			fileContent = await api.files.read(projectName, path);
		} catch (e) {
			contentError = e instanceof Error ? e.message : 'Failed to read file';
			fileContent = null;
		} finally {
			contentLoading = false;
		}
	}

	function toggleFolder(node: FileNode) {
		if (node.type === 'folder') {
			node.expanded = !node.expanded;
		}
	}

	function selectFile(node: FileNode) {
		if (node.type === 'file') {
			loadFileContent(node.path);
		}
	}

	function getFileIcon(name: string): string {
		if (name.endsWith('.py')) return 'Python';
		if (name.endsWith('.yaml') || name.endsWith('.yml')) return 'YAML';
		if (name.endsWith('.json')) return 'JSON';
		if (name.endsWith('.toml')) return 'TOML';
		if (name.endsWith('.md')) return 'Markdown';
		if (name.endsWith('.ts') || name.endsWith('.js')) return 'JavaScript';
		if (name.endsWith('.svelte')) return 'Svelte';
		if (name.endsWith('.css')) return 'CSS';
		if (name.endsWith('.html')) return 'HTML';
		return 'Text';
	}

	function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	onMount(() => {
		const unsub = currentProject.subscribe((project) => {
			projectName = project?.name ?? null;
			selectedFile = null;
			fileContent = null;
			contentError = null;
			if (projectName) {
				fetchFiles();
			} else {
				fileTree = [];
				treeLoading = false;
			}
		});
		return unsub;
	});
</script>

<div class="page">
	<div class="page-header">
		<div class="page-title">
			<FolderOpen size={20} class="text-accent" />
			<h1>Project Files</h1>
			{#if projectName}
				<span class="project-badge">{projectName}</span>
			{/if}
		</div>
		{#if !treeLoading && projectName}
			<button class="refresh-btn" onclick={fetchFiles} title="Refresh file list">
				<RefreshCw size={14} />
			</button>
		{/if}
	</div>

	<div class="page-content">
		{#if !projectName && !treeLoading}
			<div class="no-project">
				<div class="no-selection-icon">
					<FolderOpen size={40} />
				</div>
				<span class="no-selection-text">No project selected</span>
				<span class="no-selection-hint">Create or select a project to browse its files</span>
			</div>
		{:else}
			<div class="split-layout">
				<!-- File Tree -->
				<div class="file-tree-panel">
					<div class="panel-header">
						<span class="panel-title">Explorer</span>
					</div>
					<div class="tree-content">
						{#if treeLoading}
							<div class="tree-loading">
								<Loader2 size={16} class="spin" />
								<span>Loading files...</span>
							</div>
						{:else if treeError}
							<div class="tree-error">
								<AlertCircle size={14} />
								<span>{treeError}</span>
								<button class="retry-link" onclick={fetchFiles}>Retry</button>
							</div>
						{:else if fileTree.length === 0}
							<div class="tree-empty">
								<span>No files found</span>
							</div>
						{:else}
							{#each fileTree as node}
								{@render treeNode(node, 0)}
							{/each}
						{/if}
					</div>
				</div>

				<!-- Content Area -->
				<div class="content-panel">
					{#if contentLoading}
						<div class="no-selection">
							<Loader2 size={32} class="spin" />
							<span class="no-selection-text">Loading file...</span>
						</div>
					{:else if selectedFile && contentError}
						<div class="content-header">
							<File size={14} />
							<span class="content-filename">{selectedFile}</span>
						</div>
						<div class="no-selection">
							<div class="no-selection-icon error-icon">
								<AlertCircle size={32} />
							</div>
							<span class="no-selection-text">{contentError}</span>
							<button class="retry-link" onclick={() => loadFileContent(selectedFile!)}>Retry</button>
						</div>
					{:else if selectedFile && fileContent}
						<div class="content-header">
							<File size={14} />
							<span class="content-filename">{selectedFile}</span>
							<span class="content-size">{formatSize(fileContent.size)}</span>
							<span class="content-type">{getFileIcon(selectedFile)}</span>
						</div>
						<div class="content-body">
							<pre class="file-content">{fileContent.content}</pre>
						</div>
					{:else}
						<div class="no-selection">
							<div class="no-selection-icon">
								<FileText size={40} />
							</div>
							<span class="no-selection-text">Select a file to view its contents</span>
							<span class="no-selection-hint">Browse the project tree on the left</span>
						</div>
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>

{#snippet treeNode(node: FileNode, depth: number)}
	<button
		class="tree-item"
		class:selected={node.type === 'file' && selectedFile === node.path}
		style="padding-left: {12 + depth * 16}px"
		onclick={() => {
			if (node.type === 'folder') {
				toggleFolder(node);
			} else {
				selectFile(node);
			}
		}}
	>
		{#if node.type === 'folder'}
			<span class="tree-chevron">
				{#if node.expanded}
					<ChevronDown size={14} />
				{:else}
					<ChevronRight size={14} />
				{/if}
			</span>
			<FolderOpen size={14} class="tree-icon-folder" />
		{:else}
			<span class="tree-chevron-spacer"></span>
			{#if node.name.endsWith('.py') || node.name.endsWith('.ts') || node.name.endsWith('.js') || node.name.endsWith('.svelte')}
				<FileCode size={14} class="tree-icon-file" />
			{:else}
				<FileText size={14} class="tree-icon-file" />
			{/if}
		{/if}
		<span class="tree-name">{node.name}</span>
	</button>
	{#if node.type === 'folder' && node.expanded && node.children}
		{#each node.children as child}
			{@render treeNode(child, depth + 1)}
		{/each}
	{/if}
{/snippet}

<style>
	.page {
		display: flex;
		flex-direction: column;
		height: 100%;
		padding: 24px;
		gap: 24px;
		overflow: hidden;
		background: var(--color-bg-primary);
	}

	.page-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-shrink: 0;
	}

	.page-title {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.page-title h1 {
		font-size: 20px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0;
	}

	.project-badge {
		font-size: 11px;
		font-weight: 500;
		padding: 3px 10px;
		border-radius: 6px;
		background: oklch(from var(--color-accent) l c h / 12%);
		color: var(--color-accent);
		font-family: var(--font-mono);
	}

	.refresh-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-bg-elevated);
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: all 0.15s;
	}

	.refresh-btn:hover {
		color: var(--color-text-primary);
		border-color: var(--color-text-secondary);
	}

	.page-content {
		flex: 1;
		min-height: 0;
	}

	/* No project state */
	.no-project {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: 12px;
	}

	/* Split Layout */
	.split-layout {
		display: flex;
		height: 100%;
		gap: 1px;
		background: var(--color-border);
		border-radius: 12px;
		overflow: hidden;
	}

	/* File Tree Panel */
	.file-tree-panel {
		width: 240px;
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		background: var(--color-bg-elevated);
		overflow: hidden;
	}

	.panel-header {
		display: flex;
		align-items: center;
		padding: 12px 14px;
		border-bottom: 1px solid var(--color-border);
	}

	.panel-title {
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary);
	}

	.tree-content {
		flex: 1;
		overflow-y: auto;
		padding: 4px 0;
	}

	/* Tree loading / error / empty states */
	.tree-loading,
	.tree-error,
	.tree-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		padding: 24px 16px;
		font-size: 12px;
		color: var(--color-text-secondary);
		text-align: center;
	}

	.tree-error {
		color: var(--color-error, #ef4444);
	}

	.retry-link {
		background: none;
		border: none;
		color: var(--color-accent);
		cursor: pointer;
		font-size: 12px;
		text-decoration: underline;
		padding: 0;
	}

	.retry-link:hover {
		opacity: 0.8;
	}

	/* Tree Items */
	.tree-item {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		padding: 5px 12px;
		border: none;
		background: transparent;
		color: var(--color-text-primary);
		font-size: 12px;
		cursor: pointer;
		transition: background 0.1s;
		text-align: left;
	}

	.tree-item:hover {
		background: oklch(from var(--color-border) l c h / 30%);
	}

	.tree-item.selected {
		background: oklch(from var(--color-accent) l c h / 12%);
		color: var(--color-accent);
	}

	.tree-chevron {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 14px;
		flex-shrink: 0;
		color: var(--color-text-secondary);
	}

	.tree-chevron-spacer {
		width: 14px;
		flex-shrink: 0;
	}

	.tree-name {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	:global(.tree-icon-folder) {
		color: var(--color-accent);
		flex-shrink: 0;
	}

	:global(.tree-icon-file) {
		color: var(--color-text-secondary);
		flex-shrink: 0;
	}

	/* Content Panel */
	.content-panel {
		flex: 1;
		display: flex;
		flex-direction: column;
		background: var(--color-bg-elevated);
		overflow: hidden;
	}

	.content-header {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 16px;
		border-bottom: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		font-size: 12px;
	}

	.content-filename {
		color: var(--color-text-primary);
		font-weight: 500;
		font-family: var(--font-mono);
	}

	.content-size {
		font-size: 10px;
		color: var(--color-text-secondary);
	}

	.content-type {
		margin-left: auto;
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 2px 6px;
		border-radius: 3px;
		background: oklch(from var(--color-text-secondary) l c h / 10%);
		color: var(--color-text-secondary);
	}

	/* Content Body */
	.content-body {
		flex: 1;
		overflow: auto;
		padding: 0;
	}

	.file-content {
		margin: 0;
		padding: 16px;
		font-family: var(--font-mono);
		font-size: 12px;
		line-height: 1.6;
		color: var(--color-text-primary);
		white-space: pre;
		tab-size: 4;
	}

	/* No Selection */
	.no-selection {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
	}

	.no-selection-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 72px;
		height: 72px;
		border-radius: 16px;
		background: oklch(from var(--color-text-secondary) l c h / 8%);
		color: var(--color-text-secondary);
	}

	.error-icon {
		background: oklch(from var(--color-error, #ef4444) l c h / 10%);
		color: var(--color-error, #ef4444);
	}

	.no-selection-text {
		font-size: 14px;
		font-weight: 500;
		color: var(--color-text-secondary);
	}

	.no-selection-hint {
		font-size: 12px;
		color: oklch(from var(--color-text-secondary) l c h / 60%);
	}

	/* Spinner animation */
	:global(.spin) {
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
