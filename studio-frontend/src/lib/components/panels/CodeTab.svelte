<script lang="ts">
	import { smithCode, smithFiles, smithActiveFile, smithMessages, smithIsThinking, chatWithSmith, executeCode, generateCode, pendingCommand, approveCommand, connectSmith, disconnectSmith } from '$lib/stores/smith';
	import ThinkingIndicator from '$lib/components/shared/ThinkingIndicator.svelte';
	import ChatMessage from '$lib/components/shared/ChatMessage.svelte';
	import ToolCallDisplay from '$lib/components/shared/ToolCallDisplay.svelte';
	import CommandApprovalModal from '$lib/components/shared/CommandApprovalModal.svelte';
	import { Copy, Play, RefreshCw, Send, Loader, File, FileCode, FileText } from 'lucide-svelte';
	import { nodes, edges } from '$lib/stores/pipeline';
	import { get } from 'svelte/store';
	import { onMount, onDestroy } from 'svelte';

	type SmithTab = 'code' | 'chat';
	let activeTab: SmithTab = $state('code');
	let chatInput = $state('');
	let messagesContainer: HTMLDivElement;
	let copied = $state(false);

	onMount(() => {
		connectSmith();
		window.addEventListener('architect-canvas-complete', handleArchitectComplete);
	});

	onDestroy(() => {
		disconnectSmith();
		window.removeEventListener('architect-canvas-complete', handleArchitectComplete);
	});

	function handleArchitectComplete() {
		handleRefresh();
	}

	function handleCopy() {
		const file = $smithFiles.find(f => f.path === $smithActiveFile);
		if (file) {
			navigator.clipboard.writeText(file.content);
			copied = true;
			setTimeout(() => copied = false, 2000);
		}
	}

	function handleCopyAll() {
		const all = $smithFiles.map(f => `# --- ${f.path} ---\n${f.content}`).join('\n\n');
		if (all) {
			navigator.clipboard.writeText(all);
			copied = true;
			setTimeout(() => copied = false, 2000);
		}
	}

	function handleRefresh() {
		const graph = {
			nodes: get(nodes).map((n: any) => ({ id: n.id, type: n.type, data: n.data, position: n.position })),
			edges: get(edges).map((e: any) => ({ id: e.id, source: e.source, target: e.target }))
		};
		generateCode(graph);
	}

	function handleRun() {
		const code = get(smithCode);
		if (code) executeCode(code);
	}

	function handleSend() {
		const msg = chatInput.trim();
		if (!msg) return;
		chatInput = '';
		chatWithSmith(msg);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSend();
		}
	}

	function selectFile(path: string) {
		smithActiveFile.set(path);
	}

	function fileIcon(path: string) {
		if (path.endsWith('.py')) return FileCode;
		if (path.endsWith('.md')) return FileText;
		return File;
	}

	function fileExt(path: string): string {
		const parts = path.split('.');
		return parts.length > 1 ? parts[parts.length - 1] : '';
	}

	function extClass(path: string): string {
		const ext = fileExt(path);
		switch (ext) {
			case 'py': return 'ext-python';
			case 'js':
			case 'ts': return 'ext-js';
			case 'json': return 'ext-json';
			case 'yaml':
			case 'yml': return 'ext-yaml';
			case 'md': return 'ext-md';
			default: return '';
		}
	}

	const activeFileContent = $derived(
		$smithFiles.find(f => f.path === $smithActiveFile)?.content ?? ''
	);

	$effect(() => {
		$smithMessages;
		$smithIsThinking;
		if (messagesContainer) {
			requestAnimationFrame(() => {
				messagesContainer.scrollTop = messagesContainer.scrollHeight;
			});
		}
	});
</script>

<div class="smith-container">
	<!-- Tab bar -->
	<div class="tab-bar">
		<div class="tabs">
			<button class="tab" class:active={activeTab === 'code'} onclick={() => activeTab = 'code'}>
				<FileCode size={13} />
				Code
				{#if $smithFiles.length > 0}
					<span class="tab-badge">{$smithFiles.length}</span>
				{/if}
			</button>
			<button class="tab" class:active={activeTab === 'chat'} onclick={() => activeTab = 'chat'}>
				<Send size={13} />
				Chat
				{#if $smithMessages.length > 0}
					<span class="tab-badge">{$smithMessages.length}</span>
				{/if}
			</button>
		</div>
		{#if activeTab === 'code'}
			<div class="toolbar-actions">
				<button class="toolbar-btn" onclick={handleCopy} title="Copy current file">
					<Copy size={13} />
					{#if copied}<span class="copied-text">Copied!</span>{/if}
				</button>
				<button class="toolbar-btn" onclick={handleRun} title="Run all files">
					<Play size={13} />
				</button>
				<button class="toolbar-btn" onclick={handleRefresh} title="Regenerate from pipeline">
					<RefreshCw size={13} />
				</button>
			</div>
		{/if}
	</div>

	<!-- Code Tab -->
	{#if activeTab === 'code'}
		<div class="code-layout">
			<!-- File tree sidebar -->
			<div class="file-sidebar">
				<div class="file-sidebar-header">
					<span>PROJECT FILES</span>
					<span class="file-count">{$smithFiles.length}</span>
				</div>
				{#if $smithFiles.length === 0 && !$smithIsThinking}
					<div class="file-empty">
						<span>No files generated yet.</span>
						<button class="generate-btn" onclick={handleRefresh}>
							<RefreshCw size={12} />
							Generate
						</button>
					</div>
				{:else}
					<div class="file-tree">
						{#each $smithFiles as file (file.path)}
							{@const Icon = fileIcon(file.path)}
							<button
								class="file-tree-item"
								class:active={$smithActiveFile === file.path}
								onclick={() => selectFile(file.path)}
							>
								<Icon size={13} />
								<span class="file-tree-name">{file.path}</span>
								{#if fileExt(file.path)}
									<span class="file-tree-ext {extClass(file.path)}">{fileExt(file.path)}</span>
								{/if}
							</button>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Code viewer -->
			<div class="code-viewer">
				{#if $smithIsThinking && $smithFiles.length === 0}
					<div class="code-generating">
						<Loader size={20} class="smith-spinner" />
						<span>Smith is generating code...</span>
					</div>
				{:else if activeFileContent}
					<div class="code-file-header">
						<span class="code-file-path">{$smithActiveFile}</span>
					</div>
					<pre class="code-display"><code>{activeFileContent}</code></pre>
				{:else if $smithFiles.length > 0}
					<div class="code-placeholder">Select a file to view its content</div>
				{:else}
					<div class="code-placeholder">
						<p>Generate code from your pipeline</p>
						<p class="code-placeholder-sub">Click the refresh button or ask Smith in the Chat tab</p>
					</div>
				{/if}
			</div>
		</div>

	<!-- Chat Tab -->
	{:else}
		<div class="chat-area">
			<div class="messages" bind:this={messagesContainer}>
				{#if $smithMessages.length === 0 && !$smithIsThinking}
					<div class="chat-welcome">
						<div class="chat-welcome-icon">S</div>
						<p class="chat-welcome-title">Agent Smith</p>
						<p class="chat-welcome-sub">Ask Smith to generate, modify, or explain your pipeline code.</p>
					</div>
				{/if}
				{#each $smithMessages as msg}
					<ChatMessage
						role={msg.role}
						content={msg.content}
						agentName="Smith"
						accentColor="#22c55e"
					/>
					{#if msg.toolCalls}
						{#each msg.toolCalls as tc}
							<ToolCallDisplay
								toolName={tc.name}
								args={tc.args}
								result={tc.result}
								accentColor="#22c55e"
							/>
						{/each}
					{/if}
				{/each}
				{#if $smithIsThinking}
					<ThinkingIndicator
						accentColor="#22c55e"
						messages={['Compiling...', 'It is... inevitable.', 'Analyzing the construct...', 'Making it real...']}
					/>
				{/if}
			</div>
			<div class="input-bar">
				<input
					type="text"
					placeholder="Ask Smith..."
					bind:value={chatInput}
					onkeydown={handleKeydown}
				/>
				<button class="send-btn" onclick={handleSend} disabled={!chatInput.trim()}>
					<Send size={14} />
				</button>
			</div>
		</div>
	{/if}
</div>

{#if $pendingCommand}
	{@const cmdId = $pendingCommand.commandId}
	<CommandApprovalModal
		command={$pendingCommand.command}
		level={$pendingCommand.level}
		onApprove={() => approveCommand(cmdId, true)}
		onDeny={() => approveCommand(cmdId, false)}
	/>
{/if}

<style>
	.smith-container {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--color-bg-primary);
	}

	/* Tab bar */
	.tab-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 8px;
		height: 36px;
		min-height: 36px;
		border-bottom: 1px solid var(--color-border);
		background: var(--color-bg-secondary);
		flex-shrink: 0;
	}

	.tabs {
		display: flex;
		gap: 2px;
	}

	.tab {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 4px 12px;
		border: none;
		background: transparent;
		color: var(--color-text-muted);
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
		border-radius: 4px;
		transition: all 0.15s;
	}
	.tab:hover { color: var(--color-text-secondary); background: var(--color-overlay-subtle); }
	.tab.active { color: #22c55e; background: rgba(34, 197, 94, 0.08); }

	.tab-badge {
		font-size: 10px;
		padding: 0 5px;
		border-radius: 8px;
		background: var(--color-overlay-subtle);
		color: var(--color-text-muted);
		min-width: 16px;
		text-align: center;
	}
	.tab.active .tab-badge {
		background: rgba(34, 197, 94, 0.15);
		color: #22c55e;
	}

	.toolbar-actions {
		display: flex;
		gap: 2px;
	}

	.toolbar-btn {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px 8px;
		border: 1px solid var(--color-border);
		border-radius: 5px;
		background: var(--color-bg-elevated);
		color: var(--color-text-secondary);
		cursor: pointer;
		font-size: 11px;
		transition: all 0.15s;
	}
	.toolbar-btn:hover { color: var(--color-text-primary); border-color: var(--color-accent); }

	.copied-text { color: #22c55e; font-size: 10px; }

	/* Code layout */
	.code-layout {
		flex: 1;
		display: flex;
		min-height: 0;
	}

	/* File sidebar */
	.file-sidebar {
		width: 180px;
		min-width: 140px;
		border-right: 1px solid var(--color-border);
		display: flex;
		flex-direction: column;
		background: var(--color-bg-secondary);
		flex-shrink: 0;
	}

	.file-sidebar-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 10px;
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.5px;
		color: var(--color-text-muted);
		border-bottom: 1px solid var(--color-border);
	}

	.file-count {
		font-size: 10px;
		padding: 0 5px;
		border-radius: 8px;
		background: rgba(34, 197, 94, 0.12);
		color: #22c55e;
	}

	.file-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 10px;
		padding: 20px 10px;
		color: var(--color-text-muted);
		font-size: 11px;
		text-align: center;
		flex: 1;
	}

	.generate-btn {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 5px 12px;
		border: 1px solid rgba(34, 197, 94, 0.3);
		border-radius: 6px;
		background: rgba(34, 197, 94, 0.08);
		color: #22c55e;
		font-size: 11px;
		cursor: pointer;
		transition: all 0.15s;
	}
	.generate-btn:hover { background: rgba(34, 197, 94, 0.15); border-color: #22c55e; }

	.file-tree {
		flex: 1;
		overflow-y: auto;
		padding: 4px 0;
	}

	.file-tree::-webkit-scrollbar { width: 4px; }
	.file-tree::-webkit-scrollbar-track { background: transparent; }
	.file-tree::-webkit-scrollbar-thumb { background: var(--color-border); border-radius: 2px; }

	.file-tree-item {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 5px 10px;
		border: none;
		background: transparent;
		color: var(--color-text-secondary);
		font-size: 12px;
		cursor: pointer;
		width: 100%;
		text-align: left;
		transition: all 0.12s;
		font-family: var(--font-sans);
	}
	.file-tree-item:hover { background: var(--color-overlay-subtle); color: var(--color-text-primary); }
	.file-tree-item.active {
		background: rgba(34, 197, 94, 0.08);
		color: #22c55e;
		border-left: 2px solid #22c55e;
	}

	.file-tree-name {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.file-tree-ext {
		font-size: 9px;
		font-weight: 600;
		padding: 1px 4px;
		border-radius: 2px;
		background: var(--color-overlay-subtle);
		color: var(--color-text-secondary);
		flex-shrink: 0;
		text-transform: uppercase;
	}
	.ext-python { background: rgba(53, 114, 165, 0.2); color: #5b9bd5; }
	.ext-js { background: rgba(240, 219, 79, 0.15); color: #f0db4f; }
	.ext-json { background: var(--color-overlay-subtle); color: var(--color-text-secondary); }
	.ext-yaml { background: rgba(203, 171, 81, 0.15); color: #cbab51; }
	.ext-md { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }

	/* Code viewer */
	.code-viewer {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
		overflow: hidden;
	}

	.code-file-header {
		display: flex;
		align-items: center;
		padding: 6px 12px;
		background: var(--color-bg-elevated);
		border-bottom: 1px solid var(--color-border);
		flex-shrink: 0;
	}

	.code-file-path {
		font-size: 11px;
		font-family: var(--font-mono, 'JetBrains Mono', monospace);
		color: var(--color-text-primary);
	}

	.code-display {
		margin: 0;
		padding: 12px 16px;
		font-size: 12px;
		line-height: 1.6;
		color: var(--color-text-primary);
		background: var(--color-code-bg, var(--color-bg-primary));
		white-space: pre;
		tab-size: 4;
		flex: 1;
		overflow: auto;
		font-family: var(--font-mono, 'JetBrains Mono', 'Fira Code', monospace);
	}

	.code-display code { font-family: inherit; }

	.code-generating {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		height: 100%;
		color: var(--color-text-muted);
		font-size: 13px;
	}

	:global(.smith-spinner) {
		animation: smith-spin 1s linear infinite;
	}
	@keyframes smith-spin { to { transform: rotate(360deg); } }

	.code-placeholder {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--color-text-muted);
		font-size: 13px;
		gap: 4px;
	}
	.code-placeholder-sub { font-size: 11px; opacity: 0.6; }

	/* Chat area */
	.chat-area {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-height: 0;
	}

	.chat-welcome {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: 8px;
		padding: 20px;
	}

	.chat-welcome-icon {
		width: 40px;
		height: 40px;
		border-radius: 10px;
		background: rgba(34, 197, 94, 0.12);
		color: #22c55e;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 18px;
		font-weight: 700;
		font-family: var(--font-mono, monospace);
	}

	.chat-welcome-title {
		color: var(--color-text-primary);
		font-size: 14px;
		font-weight: 600;
		margin: 0;
	}

	.chat-welcome-sub {
		color: var(--color-text-muted);
		font-size: 12px;
		text-align: center;
		margin: 0;
	}

	.messages {
		flex: 1;
		overflow-y: auto;
		padding: 12px;
		min-height: 0;
	}

	.input-bar {
		display: flex;
		gap: 8px;
		padding: 8px 12px;
		border-top: 1px solid var(--color-border);
		background: var(--color-bg-secondary);
		flex-shrink: 0;
	}

	.input-bar input {
		flex: 1;
		padding: 8px 12px;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-bg-elevated);
		color: var(--color-text-primary);
		font-size: 13px;
		outline: none;
	}
	.input-bar input:focus { border-color: #22c55e; }
	.input-bar input::placeholder { color: var(--color-text-muted); }

	.send-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		border: none;
		border-radius: 8px;
		background: #22c55e;
		color: #fff;
		cursor: pointer;
		transition: background 0.15s;
	}
	.send-btn:hover { background: #16a34a; }
	.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
