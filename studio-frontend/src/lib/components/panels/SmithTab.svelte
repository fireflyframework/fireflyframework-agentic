<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { get } from 'svelte/store';
	import {
		SendHorizonal,
		Trash2,
		Bot,
		User,
		Loader,
		ChevronRight,
		CheckCircle2,
		Zap,
		Paperclip,
		X,
		FileText,
		FileSpreadsheet,
		Presentation,
		Image as ImageIcon,
		File as FileIcon,
		Copy,
		ChevronDown,
		Plus,
		Camera,
		Play,
		RefreshCw,
		Code,
		MessageCircle,
		FileCode
	} from 'lucide-svelte';
	import { marked } from 'marked';
	import hljs from 'highlight.js/lib/core';
	import javascript from 'highlight.js/lib/languages/javascript';
	import typescript from 'highlight.js/lib/languages/typescript';
	import python from 'highlight.js/lib/languages/python';
	import json from 'highlight.js/lib/languages/json';
	import bash from 'highlight.js/lib/languages/bash';
	import yaml from 'highlight.js/lib/languages/yaml';
	import xml from 'highlight.js/lib/languages/xml';
	import css from 'highlight.js/lib/languages/css';
	import sql from 'highlight.js/lib/languages/sql';
	import markdownLang from 'highlight.js/lib/languages/markdown';
	import {
		smithCode,
		smithFiles,
		smithActiveFile,
		smithMessages,
		smithIsThinking,
		smithConnected,
		chatWithSmith,
		executeCode,
		generateCode,
		pendingCommand,
		approveCommand,
		connectSmith,
		disconnectSmith,
		loadSmithHistory,
		loadSmithFiles
	} from '$lib/stores/smith';
	import { currentProject } from '$lib/stores/project';
	import CommandApprovalModal from '$lib/components/shared/CommandApprovalModal.svelte';
	import { nodes, edges } from '$lib/stores/pipeline';

	// Register highlight.js languages
	hljs.registerLanguage('javascript', javascript);
	hljs.registerLanguage('js', javascript);
	hljs.registerLanguage('typescript', typescript);
	hljs.registerLanguage('ts', typescript);
	hljs.registerLanguage('python', python);
	hljs.registerLanguage('py', python);
	hljs.registerLanguage('json', json);
	hljs.registerLanguage('bash', bash);
	hljs.registerLanguage('sh', bash);
	hljs.registerLanguage('shell', bash);
	hljs.registerLanguage('yaml', yaml);
	hljs.registerLanguage('yml', yaml);
	hljs.registerLanguage('xml', xml);
	hljs.registerLanguage('html', xml);
	hljs.registerLanguage('css', css);
	hljs.registerLanguage('sql', sql);
	hljs.registerLanguage('markdown', markdownLang);
	hljs.registerLanguage('md', markdownLang);

	// Configure marked to use highlight.js for code blocks
	const renderer = new marked.Renderer();
	renderer.code = ({ text, lang }: { text: string; lang?: string }) => {
		const langClass = lang && hljs.getLanguage(lang) ? lang : '';
		let highlighted: string;
		try {
			highlighted = langClass
				? hljs.highlight(text, { language: langClass }).value
				: hljs.highlightAuto(text).value;
		} catch {
			highlighted = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
		}
		const langLabel = lang || 'code';
		return `<div class="code-block-wrapper"><div class="code-block-header"><span class="code-lang">${langLabel}</span><button class="code-copy-btn" onclick="(function(btn){var code=btn.closest('.code-block-wrapper').querySelector('code').textContent;navigator.clipboard.writeText(code);btn.dataset.copied='true';setTimeout(function(){btn.dataset.copied='';},1500);})(this)" title="Copy code">Copy</button></div><pre><code class="hljs${langClass ? ' language-' + langClass : ''}">${highlighted}</code></pre></div>`;
	};
	marked.setOptions({ renderer });

	// File attachment types
	interface FileAttachment {
		id: string;
		name: string;
		type: string;
		size: number;
		category: 'image' | 'pdf' | 'document' | 'spreadsheet' | 'presentation' | 'text' | 'other';
		data: string;
		preview?: string;
		docType: string;
	}

	const DOC_TYPE_OPTIONS = [
		{ value: 'auto', label: 'Auto-detect' },
		{ value: 'requirements', label: 'Requirements Doc' },
		{ value: 'api_spec', label: 'API Spec / OpenAPI' },
		{ value: 'data_sample', label: 'Data Sample' },
		{ value: 'diagram', label: 'Architecture Diagram' },
		{ value: 'config', label: 'Config / Settings' },
		{ value: 'code', label: 'Source Code' },
		{ value: 'documentation', label: 'Documentation' },
		{ value: 'test_cases', label: 'Test Cases' },
		{ value: 'schema', label: 'Schema / Model' },
	];

	const ACCEPTED_TYPES: Record<string, string> = {
		'image/png': 'image', 'image/jpeg': 'image', 'image/gif': 'image',
		'image/webp': 'image', 'image/svg+xml': 'image', 'image/bmp': 'image',
		'application/pdf': 'pdf',
		'application/msword': 'document',
		'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'document',
		'application/vnd.oasis.opendocument.text': 'document',
		'application/rtf': 'document',
		'application/vnd.ms-excel': 'spreadsheet',
		'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'spreadsheet',
		'application/vnd.oasis.opendocument.spreadsheet': 'spreadsheet',
		'text/csv': 'spreadsheet',
		'application/vnd.ms-powerpoint': 'presentation',
		'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'presentation',
		'application/vnd.oasis.opendocument.presentation': 'presentation',
		'text/plain': 'text', 'text/markdown': 'text', 'application/json': 'text',
		'text/html': 'text', 'text/css': 'text', 'application/javascript': 'text',
		'application/x-yaml': 'text', 'text/yaml': 'text',
		'application/xml': 'text', 'text/xml': 'text',
	};

	const EXTENSION_MAP: Record<string, string> = {
		'.py': 'text', '.js': 'text', '.ts': 'text', '.jsx': 'text', '.tsx': 'text',
		'.json': 'text', '.md': 'text', '.txt': 'text', '.csv': 'spreadsheet',
		'.yaml': 'text', '.yml': 'text', '.xml': 'text', '.html': 'text', '.css': 'text',
		'.sql': 'text', '.sh': 'text', '.bash': 'text', '.r': 'text', '.rb': 'text',
		'.go': 'text', '.rs': 'text', '.java': 'text', '.kt': 'text', '.swift': 'text',
		'.pdf': 'pdf',
		'.doc': 'document', '.docx': 'document', '.odt': 'document', '.rtf': 'document',
		'.xls': 'spreadsheet', '.xlsx': 'spreadsheet', '.ods': 'spreadsheet',
		'.ppt': 'presentation', '.pptx': 'presentation', '.odp': 'presentation',
		'.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.gif': 'image',
		'.webp': 'image', '.svg': 'image', '.bmp': 'image',
	};

	const ACCEPT_STRING = Object.keys(ACCEPTED_TYPES).join(',') +
		',.py,.js,.ts,.jsx,.tsx,.sql,.sh,.r,.rb,.go,.rs,.java,.kt,.swift';

	function detectCategory(file: File): FileAttachment['category'] {
		if (file.type && ACCEPTED_TYPES[file.type]) {
			return ACCEPTED_TYPES[file.type] as FileAttachment['category'];
		}
		const ext = '.' + file.name.split('.').pop()?.toLowerCase();
		if (ext && EXTENSION_MAP[ext]) {
			return EXTENSION_MAP[ext] as FileAttachment['category'];
		}
		return 'other';
	}

	let attachments: FileAttachment[] = $state([]);
	let fileInputEl: HTMLInputElement | undefined = $state(undefined);
	let attachDropdownOpen = $state(false);

	async function addFiles(files: FileList | File[]): Promise<void> {
		const fileArr = Array.from(files);
		for (const file of fileArr) {
			if (file.size > 20 * 1024 * 1024) continue;
			const category = detectCategory(file);
			const base64 = await readFileAsBase64(file);
			const attachment: FileAttachment = {
				id: `file-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
				name: file.name,
				type: file.type || 'application/octet-stream',
				size: file.size,
				category,
				data: base64,
				docType: 'auto',
			};
			if (category === 'image') {
				attachment.preview = `data:${file.type};base64,${base64}`;
			}
			attachments = [...attachments, attachment];
		}
	}

	function readFileAsBase64(file: File): Promise<string> {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => {
				const result = reader.result as string;
				const base64 = result.includes(',') ? result.split(',')[1] : result;
				resolve(base64);
			};
			reader.onerror = reject;
			reader.readAsDataURL(file);
		});
	}

	function removeAttachment(id: string): void {
		attachments = attachments.filter((a) => a.id !== id);
	}

	let openTypeDropdown = $state<string | null>(null);

	function setDocType(id: string, value: string) {
		attachments = attachments.map(a => a.id === id ? { ...a, docType: value } : a);
		openTypeDropdown = null;
	}

	function getDocTypeLabel(docType: string | undefined): string {
		if (!docType || docType === 'auto') return 'Auto-detect';
		return DOC_TYPE_OPTIONS.find(o => o.value === docType)?.label ?? docType;
	}

	function handleFileSelect(event: Event): void {
		const input = event.target as HTMLInputElement;
		if (input.files && input.files.length > 0) {
			addFiles(input.files);
			input.value = '';
		}
	}

	function handlePaste(event: ClipboardEvent): void {
		const items = event.clipboardData?.items;
		if (!items) return;
		const filesToAdd: File[] = [];
		for (const item of Array.from(items)) {
			if (item.kind === 'file') {
				const file = item.getAsFile();
				if (file) filesToAdd.push(file);
			}
		}
		if (filesToAdd.length > 0) {
			event.preventDefault();
			addFiles(filesToAdd);
		}
	}

	// Braille spinner animation
	const SPINNER_FRAMES = ['\u280B', '\u2819', '\u2839', '\u2838', '\u283C', '\u2834', '\u2826', '\u2827', '\u2807', '\u280F'];
	const THINKING_MESSAGES = [
		'Compiling the code...',
		'It is... inevitable.',
		'Analyzing the construct...',
		'Making it real...',
		'Writing the program...',
		'Assembling the modules...',
		'Forging the implementation...',
		'Building the executable...',
	];

	let spinnerFrame = $state(SPINNER_FRAMES[0]);
	let currentThinkingMsg = $state(THINKING_MESSAGES[0]);
	let thinkingInterval: ReturnType<typeof setInterval> | null = null;
	let messageInterval: ReturnType<typeof setInterval> | null = null;
	let spinnerIdx = 0;
	let messageIdx = 0;

	$effect(() => {
		if ($smithIsThinking) {
			spinnerIdx = 0;
			messageIdx = Math.floor(Math.random() * THINKING_MESSAGES.length);
			currentThinkingMsg = THINKING_MESSAGES[messageIdx];
			thinkingInterval = setInterval(() => {
				spinnerIdx = (spinnerIdx + 1) % SPINNER_FRAMES.length;
				spinnerFrame = SPINNER_FRAMES[spinnerIdx];
			}, 80);
			messageInterval = setInterval(() => {
				messageIdx = (messageIdx + 1) % THINKING_MESSAGES.length;
				currentThinkingMsg = THINKING_MESSAGES[messageIdx];
			}, 2500);
		} else {
			if (thinkingInterval) { clearInterval(thinkingInterval); thinkingInterval = null; }
			if (messageInterval) { clearInterval(messageInterval); messageInterval = null; }
		}
	});

	// Tool call display helpers
	let expandedToolGroups: Record<string, boolean> = $state({});

	function toggleToolGroup(msgIdx: number): void {
		const key = `msg-${msgIdx}`;
		expandedToolGroups[key] = !expandedToolGroups[key];
	}

	function toolCallSummary(toolCalls: { name: string }[]): string {
		const counts: Record<string, number> = {};
		for (const tc of toolCalls) {
			counts[tc.name] = (counts[tc.name] || 0) + 1;
		}
		return Object.entries(counts)
			.map(([name, count]) => (count > 1 ? `${name} x${count}` : name))
			.join(', ');
	}

	function parseToolArgs(argsStr: string): Record<string, unknown> | null {
		if (!argsStr) return null;
		try {
			const parsed = JSON.parse(argsStr);
			if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
				return parsed;
			}
			return null;
		} catch {
			return null;
		}
	}

	function sanitizeHtml(html: string): string {
		return html
			.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
			.replace(/\bon\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '');
	}

	function renderMarkdown(content: string): string {
		if (!content) return '';
		const raw = marked(content, { async: false }) as string;
		return sanitizeHtml(raw);
	}

	// State
	let viewMode: 'chat' | 'code' = $state('chat');
	let chatInput = $state('');
	let messagesContainer: HTMLDivElement | undefined = $state(undefined);
	let inputElement: HTMLTextAreaElement | undefined = $state(undefined);
	let copied = $state(false);

	// Connection error derived from smithConnected
	let connectionError = $derived(!$smithConnected && $smithMessages.length > 0 ? 'Connection to Smith lost. Attempting to reconnect...' : '');

	onMount(async () => {
		connectSmith();
		inputElement?.focus();
		window.addEventListener('architect-canvas-complete', handleArchitectComplete);
		// Load persisted history and files for current project
		const proj = $currentProject;
		if (proj?.name) {
			await Promise.all([
				loadSmithHistory(proj.name),
				loadSmithFiles(proj.name),
			]);
		}
	});

	onDestroy(() => {
		disconnectSmith();
		window.removeEventListener('architect-canvas-complete', handleArchitectComplete);
		if (thinkingInterval) clearInterval(thinkingInterval);
		if (messageInterval) clearInterval(messageInterval);
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

	function handleSend(): void {
		const text = chatInput.trim();
		if (!text || $smithIsThinking) return;
		chatInput = '';
		attachments = [];
		chatWithSmith(text);
		scrollToBottom();
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			handleSend();
		}
	}

	function handleClear(): void {
		smithMessages.set([]);
	}

	function retryConnection(): void {
		connectSmith();
	}

	function scrollToBottom(): void {
		requestAnimationFrame(() => {
			if (messagesContainer) {
				messagesContainer.scrollTop = messagesContainer.scrollHeight;
			}
		});
	}

	function formatTime(isoString: string): string {
		const d = new Date(isoString);
		return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
	}

	function selectFile(path: string) {
		smithActiveFile.set(path);
	}

	function fileIcon(path: string) {
		if (path.endsWith('.py')) return FileCode;
		if (path.endsWith('.md')) return FileText;
		return FileIcon;
	}

	function fileExt(path: string): string {
		const parts = path.split('.');
		return parts.length > 1 ? parts[parts.length - 1] : '';
	}

	function extClass(path: string): string {
		const ext = fileExt(path);
		switch (ext) {
			case 'py': return 'ext-python';
			case 'js': case 'ts': return 'ext-js';
			case 'json': return 'ext-json';
			case 'yaml': case 'yml': return 'ext-yaml';
			case 'md': return 'ext-md';
			default: return '';
		}
	}

	const activeFileContent = $derived(
		$smithFiles.find(f => f.path === $smithActiveFile)?.content ?? ''
	);

	// Language detection for syntax highlighting in code view
	const EXT_TO_LANG: Record<string, string> = {
		py: 'python', js: 'javascript', ts: 'typescript', jsx: 'javascript', tsx: 'typescript',
		json: 'json', yaml: 'yaml', yml: 'yaml', sh: 'bash', bash: 'bash', shell: 'bash',
		xml: 'xml', html: 'xml', css: 'css', sql: 'sql', md: 'markdown',
	};

	function detectLang(path: string): string {
		const ext = path.split('.').pop()?.toLowerCase() ?? '';
		return EXT_TO_LANG[ext] ?? '';
	}

	const highlightedLines = $derived.by(() => {
		if (!activeFileContent || !$smithActiveFile) return [];
		const lang = detectLang($smithActiveFile);
		let highlighted: string;
		try {
			highlighted = lang && hljs.getLanguage(lang)
				? hljs.highlight(activeFileContent, { language: lang }).value
				: hljs.highlightAuto(activeFileContent).value;
		} catch {
			highlighted = activeFileContent.replace(/</g, '&lt;').replace(/>/g, '&gt;');
		}
		return highlighted.split('\n');
	});

	// Copy button in code file header
	let fileCopied = $state(false);

	function handleCopyFile() {
		if (activeFileContent) {
			navigator.clipboard.writeText(activeFileContent);
			fileCopied = true;
			setTimeout(() => fileCopied = false, 1500);
		}
	}

	// Auto-scroll on new messages or thinking state change
	$effect(() => {
		$smithMessages;
		$smithIsThinking;
		if (messagesContainer) {
			requestAnimationFrame(() => {
				if (messagesContainer && messagesContainer.offsetParent !== null) {
					messagesContainer.scrollTop = messagesContainer.scrollHeight;
				}
			});
		}
	});
</script>

<div class="smith-tab">
	<!-- Header with view toggle -->
	<div class="smith-header">
		<div class="view-toggle">
			<button class="toggle-btn" class:active={viewMode === 'chat'} onclick={() => viewMode = 'chat'}>
				<MessageCircle size={13} />
				Chat
			</button>
			<button class="toggle-btn" class:active={viewMode === 'code'} onclick={() => viewMode = 'code'}>
				<Code size={13} />
				Code
				{#if $smithFiles.length > 0}
					<span class="toggle-badge">{$smithFiles.length}</span>
				{/if}
			</button>
		</div>
		{#if viewMode === 'code'}
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

	{#if viewMode === 'chat'}
		<!-- Messages area -->
		<div class="messages" bind:this={messagesContainer}>
			{#if $smithMessages.length === 0 && !$smithIsThinking}
				<div class="empty-state">
					<div class="empty-icon-circle">
						<Bot size={48} />
					</div>
					<span class="empty-title">Agent Smith</span>
					<span class="empty-hint">I am... inevitable. Describe what code you need and I shall compile it into existence.</span>
				</div>
			{:else}
				{#each $smithMessages as message, msgIdx}
					<div
						class="message"
						class:user={message.role === 'user'}
						class:assistant={message.role === 'assistant'}
					>
						<div class="message-avatar">
							{#if message.role === 'user'}
								<User size={18} />
							{:else}
								<Bot size={18} />
							{/if}
						</div>
						<div class="message-body">
							<div class="message-header">
								<span class="message-role">{message.role === 'user' ? 'You' : 'Smith'}</span>
								<span class="message-time">{formatTime(message.timestamp)}</span>
							</div>
							<div class="message-content" class:markdown={message.role === 'assistant'}>
								{#if message.role === 'assistant'}
									{@html renderMarkdown(message.content)}
								{:else}
									{message.content}
								{/if}
							</div>
							{#if message.toolCalls && message.toolCalls.length > 0}
								<div class="tool-calls-container">
									<!-- svelte-ignore a11y_click_events_have_key_events -->
									<!-- svelte-ignore a11y_no_static_element_interactions -->
									<div
										class="tool-calls-header"
										onclick={() => toggleToolGroup(msgIdx)}
									>
										<div class="tool-calls-header-left">
											<div
												class="tool-chevron"
												class:expanded={expandedToolGroups[`msg-${msgIdx}`]}
											>
												<ChevronRight size={12} />
											</div>
											<Zap size={12} />
											<span class="tool-calls-count">{message.toolCalls.length} tool call{message.toolCalls.length !== 1 ? 's' : ''}</span>
										</div>
										<span class="tool-calls-summary">{toolCallSummary(message.toolCalls)}</span>
									</div>
									{#if expandedToolGroups[`msg-${msgIdx}`]}
										<div class="tool-calls-body">
											{#each message.toolCalls as tc, i}
												{@const parsedArgs = parseToolArgs(tc.args)}
												<div class="tool-call-item">
													<div class="tool-call-row">
														<span class="tool-call-index">{i + 1}</span>
														<span class="tool-call-name">{tc.name}</span>
														{#if tc.result}
															<CheckCircle2 size={11} class="tool-call-ok" />
														{/if}
													</div>
													{#if parsedArgs && Object.keys(parsedArgs).length > 0}
														<div class="tool-call-args">
															{#each Object.entries(parsedArgs) as [key, val]}
																<div class="tool-arg-line">
																	<span class="tool-arg-key">{key}:</span>
																	<span class="tool-arg-val">{typeof val === 'string' ? (val.length > 120 ? val.slice(0, 117) + '...' : val) : JSON.stringify(val)}</span>
																</div>
															{/each}
														</div>
													{:else if tc.args}
														<div class="tool-call-args">
															<div class="tool-arg-line">
																<span class="tool-arg-val">{tc.args.length > 200 ? tc.args.slice(0, 197) + '...' : tc.args}</span>
															</div>
														</div>
													{/if}
													{#if tc.result}
														<div class="tool-call-result">
															<span class="tool-result-label">result</span>
															<span class="tool-result-val">{tc.result.length > 200 ? tc.result.slice(0, 197) + '...' : tc.result}</span>
														</div>
													{/if}
												</div>
											{/each}
										</div>
									{/if}
								</div>
							{/if}
						</div>
					</div>
				{/each}
				{#if $smithIsThinking}
					<div class="message assistant">
						<div class="message-avatar">
							<Bot size={18} />
						</div>
						<div class="message-body">
							<div class="message-header">
								<span class="message-role">Smith</span>
							</div>
							<div class="message-content markdown">
								<div class="thinking-indicator">
									<span class="thinking-spinner">{spinnerFrame}</span>
									{#key currentThinkingMsg}
										<span class="thinking-message">{currentThinkingMsg}</span>
									{/key}
								</div>
							</div>
						</div>
					</div>
				{/if}
				{#if $smithFiles.length > 0}
					<button class="view-code-link" onclick={() => viewMode = 'code'}>
						<Code size={12} />
						View generated code ({$smithFiles.length} file{$smithFiles.length !== 1 ? 's' : ''})
					</button>
				{/if}
			{/if}
		</div>

		<!-- Error bar -->
		{#if connectionError}
			<div class="error-bar">
				<span>{connectionError}</span>
				<button class="retry-btn" onclick={retryConnection}>Retry</button>
			</div>
		{/if}

		<!-- Input area -->
		<div class="input-area">
			{#if attachments.length > 0}
				<div class="attachment-badges">
					{#each attachments as att (att.id)}
						<div class="attachment-badge-wrapper">
							<div class="attachment-badge" class:has-preview={att.category === 'image' && att.preview}>
								{#if att.category === 'image' && att.preview}
									<img src={att.preview} alt={att.name} class="attachment-thumb" />
								{:else}
									<div class="attachment-icon">
										{#if att.category === 'pdf'}
											<FileText size={14} />
										{:else if att.category === 'spreadsheet'}
											<FileSpreadsheet size={14} />
										{:else if att.category === 'presentation'}
											<Presentation size={14} />
										{:else if att.category === 'document'}
											<FileText size={14} />
										{:else if att.category === 'image'}
											<ImageIcon size={14} />
										{:else}
											<FileIcon size={14} />
										{/if}
									</div>
								{/if}
								<div class="attachment-info">
									<span class="attachment-name" title={att.name}>
										{att.name.length > 20 ? att.name.slice(0, 17) + '...' : att.name}
									</span>
									<button class="attachment-type-btn" onclick={() => openTypeDropdown = openTypeDropdown === att.id ? null : att.id}>
										<span>{getDocTypeLabel(att.docType)}</span>
										<ChevronDown size={9} />
									</button>
								</div>
								<button
									class="attachment-remove"
									onclick={() => removeAttachment(att.id)}
									title="Remove file"
								>
									<X size={12} />
								</button>
							</div>
							{#if openTypeDropdown === att.id}
								<div class="type-dropdown">
									{#each DOC_TYPE_OPTIONS as opt}
										<button class="type-option" class:selected={att.docType === opt.value}
											onclick={() => setDocType(att.id, opt.value)}>
											{opt.label}
										</button>
									{/each}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
			<div class="input-row">
				<div class="attach-container">
					<button class="action-btn attach-btn" onclick={() => attachDropdownOpen = !attachDropdownOpen} title="Attach" disabled={$smithIsThinking}>
						<Plus size={16} />
					</button>
					{#if attachDropdownOpen}
						<div class="attach-dropdown">
							<button class="attach-option" onclick={() => { fileInputEl?.click(); attachDropdownOpen = false; }}>
								<Paperclip size={14} />
								<span>File</span>
							</button>
							<button class="attach-option" onclick={() => { attachDropdownOpen = false; }}>
								<Camera size={14} />
								<span>Screenshot</span>
							</button>
						</div>
					{/if}
				</div>
				<input
					type="file"
					multiple
					accept={ACCEPT_STRING}
					bind:this={fileInputEl}
					onchange={handleFileSelect}
					class="file-input-hidden"
				/>
				<textarea
					class="chat-input"
					placeholder="Ask Agent Smith..."
					bind:value={chatInput}
					bind:this={inputElement}
					onkeydown={handleKeydown}
					onpaste={handlePaste}
					disabled={$smithIsThinking}
					rows={1}
				></textarea>
				<div class="input-actions">
					<button
						class="action-btn clear-btn"
						onclick={handleClear}
						title="Clear chat"
						disabled={$smithMessages.length === 0}
					>
						<Trash2 size={14} />
					</button>
					<button
						class="action-btn send-btn"
						onclick={handleSend}
						disabled={!chatInput.trim() || $smithIsThinking}
						title="Send message"
					>
						{#if $smithIsThinking}
							<Loader size={14} class="spin-icon" />
						{:else}
							<SendHorizonal size={14} />
						{/if}
					</button>
				</div>
			</div>
		</div>
	{:else}
		<!-- Code view -->
		<div class="code-area">
			{#if $smithFiles.length === 0 && !$smithIsThinking}
				<div class="code-empty">
					<span>No files generated yet.</span>
					<button class="generate-btn" onclick={handleRefresh}>
						<RefreshCw size={12} />
						Generate
					</button>
				</div>
			{:else if $smithIsThinking && $smithFiles.length === 0}
				<div class="code-generating">
					<Loader size={20} class="smith-spinner" />
					<span>Smith is generating code...</span>
				</div>
			{:else}
				<!-- File list (compact full-width) -->
				<div class="file-list">
					{#each $smithFiles as file (file.path)}
						{@const Icon = fileIcon(file.path)}
						<button
							class="file-item"
							class:active={$smithActiveFile === file.path}
							onclick={() => selectFile(file.path)}
						>
							<Icon size={13} />
							<span class="file-name">{file.path}</span>
							{#if fileExt(file.path)}
								<span class="file-ext {extClass(file.path)}">{fileExt(file.path)}</span>
							{/if}
						</button>
					{/each}
				</div>
				<!-- Code viewer -->
				{#if activeFileContent}
					<div class="code-file-header">
						<span class="code-file-path">{$smithActiveFile}</span>
						<button class="copy-file-btn" onclick={handleCopyFile}>
							<Copy size={12} />
							{#if fileCopied}<span class="copy-feedback">Copied!</span>{:else}<span>Copy</span>{/if}
						</button>
					</div>
					<div class="code-display-wrapper">
						<table class="code-table">
							<tbody>
								{#each highlightedLines as line, i}
									<tr class="code-line">
										<td class="line-number">{i + 1}</td>
										<td class="line-content hljs">{@html line || ' '}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<div class="code-placeholder">Select a file to view its content</div>
				{/if}
			{/if}
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
	.smith-tab {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	/* ---- Header ---- */
	.smith-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 10px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
		gap: 8px;
	}

	.view-toggle {
		display: flex;
		gap: 2px;
		background: oklch(from var(--color-text-primary) l c h / 3%);
		border-radius: 6px;
		padding: 2px;
	}

	.toggle-btn {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 4px 10px;
		border: none;
		border-radius: 4px;
		background: transparent;
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}
	.toggle-btn:hover { color: var(--color-text-primary, #e8e8ed); }
	.toggle-btn.active { background: var(--color-overlay-light); color: #22c55e; }

	.toggle-badge {
		font-size: 9px;
		padding: 0 5px;
		border-radius: 8px;
		background: rgba(34, 197, 94, 0.15);
		color: #22c55e;
		min-width: 16px;
		text-align: center;
	}

	.toolbar-actions { display: flex; gap: 2px; }
	.toolbar-btn {
		display: flex; align-items: center; gap: 4px; padding: 4px 8px;
		border: 1px solid var(--color-border); border-radius: 5px;
		background: var(--color-bg-elevated); color: var(--color-text-secondary);
		cursor: pointer; font-size: 11px; transition: all 0.15s;
	}
	.toolbar-btn:hover { color: var(--color-text-primary); border-color: #22c55e; }
	.copied-text { color: #22c55e; font-size: 10px; }

	/* ---- Messages area ---- */
	.messages {
		flex: 1;
		overflow-y: auto;
		padding: 16px;
		min-height: 0;
		background: linear-gradient(
			180deg,
			oklch(from #22c55e l c h / 2%) 0%,
			var(--color-bg-primary, #0a0a0f) 100%
		);
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: 10px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.7;
		padding: 24px;
	}

	.empty-icon-circle {
		width: 72px;
		height: 72px;
		border-radius: 50%;
		background: oklch(from #22c55e l c h / 10%);
		color: #22c55e;
		display: flex;
		align-items: center;
		justify-content: center;
		margin-bottom: 4px;
	}

	.empty-title {
		font-size: 15px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.empty-hint {
		font-size: 12px;
		color: var(--color-text-secondary, #8888a0);
		text-align: center;
		max-width: 320px;
		line-height: 1.5;
	}

	/* ---- Message layout ---- */
	.message {
		display: flex;
		gap: 10px;
		margin-bottom: 16px;
	}

	.message-avatar {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		margin-top: 2px;
	}

	.message.user .message-avatar {
		background: oklch(from #22c55e l c h / 15%);
		color: #22c55e;
	}

	.message.assistant .message-avatar {
		background: var(--color-overlay-subtle);
		color: var(--color-text-secondary, #8888a0);
	}

	.message-body {
		flex: 1;
		min-width: 0;
	}

	.message-header {
		display: flex;
		align-items: baseline;
		gap: 8px;
		margin-bottom: 4px;
	}

	.message-role {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.message-time {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.6;
	}

	.message-content {
		font-size: 13px;
		line-height: 1.6;
		color: var(--color-text-primary, #e8e8ed);
		white-space: pre-wrap;
		word-break: break-word;
	}

	.message.user .message-content {
		background: oklch(from #22c55e l c h / 10%);
		border-radius: 8px;
		padding: 8px 12px;
	}

	.message.assistant .message-content {
		background: var(--color-bg-elevated, #1a1a26);
		border-radius: 8px;
		padding: 8px 12px;
	}

	.message-content.markdown {
		white-space: normal;
	}

	/* ---- Markdown rendering ---- */
	.message-content.markdown :global(p) { margin: 0 0 8px; }
	.message-content.markdown :global(p:last-child) { margin-bottom: 0; }
	.message-content.markdown :global(h1),
	.message-content.markdown :global(h2),
	.message-content.markdown :global(h3) {
		margin: 12px 0 6px;
		font-weight: 600;
		line-height: 1.3;
	}
	.message-content.markdown :global(h1) { font-size: 16px; }
	.message-content.markdown :global(h2) { font-size: 14px; }
	.message-content.markdown :global(h3) { font-size: 13px; }

	.message-content.markdown :global(code) {
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		font-size: 11px;
		background: var(--color-overlay-subtle);
		padding: 1px 4px;
		border-radius: 3px;
	}

	.message-content.markdown :global(pre) {
		background: var(--color-code-bg, var(--color-bg-primary));
		border-radius: 6px;
		padding: 10px 12px;
		overflow-x: auto;
		margin: 8px 0;
	}

	.message-content.markdown :global(pre code) {
		background: none;
		padding: 0;
		font-size: 11px;
		line-height: 1.5;
	}

	.message-content.markdown :global(ul),
	.message-content.markdown :global(ol) { margin: 6px 0; padding-left: 20px; }
	.message-content.markdown :global(li) { margin-bottom: 2px; }

	.message-content.markdown :global(blockquote) {
		border-left: 3px solid #22c55e;
		margin: 8px 0;
		padding: 4px 12px;
		color: var(--color-text-secondary, #8888a0);
	}

	.message-content.markdown :global(a) {
		color: #22c55e;
		text-decoration: underline;
	}

	.message-content.markdown :global(table) {
		border-collapse: collapse;
		width: 100%;
		margin: 8px 0;
		font-size: 11px;
	}

	.message-content.markdown :global(th),
	.message-content.markdown :global(td) {
		border: 1px solid var(--color-border, #2a2a3a);
		padding: 4px 8px;
		text-align: left;
	}

	.message-content.markdown :global(th) {
		background: oklch(from var(--color-text-primary) l c h / 4%);
		font-weight: 600;
	}

	/* ---- Streaming cursor ---- */
	.streaming-cursor {
		display: inline-block;
		width: 6px;
		height: 14px;
		background: #22c55e;
		margin-left: 2px;
		animation: blink 0.8s step-end infinite;
		vertical-align: text-bottom;
	}

	@keyframes blink {
		0%, 100% { opacity: 1; }
		50% { opacity: 0; }
	}

	/* ---- Thinking indicator ---- */
	.thinking-indicator {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 0;
	}

	.thinking-spinner {
		font-size: 16px;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		color: #22c55e;
		flex-shrink: 0;
		line-height: 1;
	}

	.thinking-message {
		font-size: 12px;
		color: var(--color-text-secondary, #8888a0);
		font-style: italic;
		animation: msg-fade 0.4s ease;
	}

	@keyframes msg-fade {
		from { opacity: 0; transform: translateX(4px); }
		to { opacity: 1; transform: translateX(0); }
	}

	/* ---- Tool calls ---- */
	.tool-calls-container {
		margin-top: 8px;
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 8px;
		overflow: hidden;
		background: oklch(from var(--color-bg-primary) l c h / 50%);
	}

	.tool-calls-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 7px 10px;
		cursor: pointer;
		user-select: none;
		transition: background 0.15s ease;
		gap: 8px;
	}

	.tool-calls-header:hover { background: oklch(from var(--color-text-primary) l c h / 3%); }

	.tool-calls-header-left {
		display: flex;
		align-items: center;
		gap: 6px;
		color: #22c55e;
		flex-shrink: 0;
	}

	.tool-chevron {
		display: flex;
		align-items: center;
		transition: transform 0.2s ease;
	}

	.tool-chevron.expanded { transform: rotate(90deg); }

	.tool-calls-count {
		font-size: 11px;
		font-weight: 600;
		white-space: nowrap;
	}

	.tool-calls-summary {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		text-align: right;
	}

	.tool-calls-body {
		border-top: 1px solid var(--color-border, #2a2a3a);
		display: flex;
		flex-direction: column;
	}

	.tool-call-item {
		padding: 8px 10px;
		border-bottom: 1px solid oklch(from var(--color-text-primary) l c h / 3%);
	}
	.tool-call-item:last-child { border-bottom: none; }

	.tool-call-row {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 2px;
	}

	.tool-call-index {
		width: 16px;
		height: 16px;
		border-radius: 50%;
		background: var(--color-overlay-subtle);
		color: var(--color-text-secondary, #8888a0);
		font-size: 9px;
		font-weight: 600;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.tool-call-name {
		font-size: 11px;
		font-weight: 600;
		color: #22c55e;
	}

	:global(.tool-call-ok) { color: #4ade80; flex-shrink: 0; }

	.tool-call-args {
		margin: 4px 0 0 22px;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.tool-arg-line {
		display: flex;
		gap: 6px;
		font-size: 10px;
		line-height: 1.5;
	}

	.tool-arg-key {
		color: var(--color-text-secondary, #8888a0);
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		flex-shrink: 0;
	}

	.tool-arg-val {
		color: var(--color-text-primary, #e8e8ed);
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		word-break: break-word;
	}

	.tool-call-result {
		margin: 4px 0 0 22px;
		padding: 4px 8px;
		background: rgba(74, 222, 128, 0.06);
		border-left: 2px solid rgba(74, 222, 128, 0.3);
		border-radius: 0 4px 4px 0;
		display: flex;
		gap: 6px;
		font-size: 10px;
		line-height: 1.5;
	}

	.tool-result-label {
		color: #4ade80;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		font-weight: 600;
		flex-shrink: 0;
	}

	.tool-result-val {
		color: var(--color-text-secondary, #8888a0);
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		word-break: break-word;
	}

	/* ---- View code link ---- */
	.view-code-link {
		display: inline-flex; align-items: center; gap: 5px;
		margin-top: 8px; padding: 5px 10px;
		border: 1px solid rgba(34, 197, 94, 0.25); border-radius: 6px;
		background: rgba(34, 197, 94, 0.06); color: #22c55e;
		font-size: 11px; cursor: pointer; transition: background 0.15s;
	}
	.view-code-link:hover { background: rgba(34, 197, 94, 0.12); }

	/* ---- Error bar ---- */
	.error-bar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 12px;
		background: rgba(239, 68, 68, 0.1);
		border-top: 1px solid rgba(239, 68, 68, 0.2);
		font-size: 11px;
		color: var(--color-error, #ef4444);
		flex-shrink: 0;
	}

	.retry-btn {
		margin-left: auto;
		padding: 2px 10px;
		border: 1px solid rgba(239, 68, 68, 0.3);
		border-radius: 4px;
		background: rgba(239, 68, 68, 0.15);
		color: var(--color-error, #ef4444);
		font-size: 11px;
		cursor: pointer;
		white-space: nowrap;
	}

	.retry-btn:hover { background: rgba(239, 68, 68, 0.25); }

	/* ---- Input area ---- */
	.input-area {
		flex-shrink: 0;
		border-top: 1px solid var(--color-border, #2a2a3a);
		padding: 8px 12px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.file-input-hidden {
		display: none;
	}

	/* Attachment badges */
	.attachment-badges {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.attachment-badge {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 4px 8px;
		background: var(--color-bg-elevated, #1a1a26);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 8px;
		max-width: 200px;
		transition: border-color 0.15s;
	}

	.attachment-badge:hover {
		border-color: var(--color-text-secondary, #8888a0);
	}

	.attachment-badge.has-preview {
		padding: 3px 8px 3px 3px;
	}

	.attachment-thumb {
		width: 32px;
		height: 32px;
		object-fit: cover;
		border-radius: 5px;
		flex-shrink: 0;
	}

	.attachment-icon {
		width: 28px;
		height: 28px;
		border-radius: 6px;
		background: oklch(from #22c55e l c h / 10%);
		color: #22c55e;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.attachment-info {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.attachment-name {
		font-size: 11px;
		font-weight: 500;
		color: var(--color-text-primary, #e8e8ed);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.attachment-badge-wrapper {
		position: relative;
	}

	.attachment-type-btn {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		font-size: 9px;
		color: var(--color-text-secondary, #8888a0);
		transition: color 0.15s;
	}

	.attachment-type-btn:hover {
		color: #22c55e;
	}

	.type-dropdown {
		position: absolute;
		bottom: calc(100% + 4px);
		left: 0;
		min-width: 160px;
		background: var(--color-bg-secondary, #12121a);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 8px;
		box-shadow: var(--shadow-dropdown);
		z-index: 100;
		overflow: hidden;
		padding: 4px;
	}

	.type-option {
		display: block;
		width: 100%;
		text-align: left;
		padding: 5px 10px;
		border: none;
		background: transparent;
		border-radius: 5px;
		color: var(--color-text-primary, #e8e8ed);
		font-size: 11px;
		cursor: pointer;
		transition: background 0.1s;
	}

	.type-option:hover {
		background: var(--color-overlay-subtle);
	}

	.type-option.selected {
		color: #22c55e;
		background: oklch(from #22c55e l c h / 10%);
	}

	.attachment-remove {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 18px;
		height: 18px;
		border: none;
		background: transparent;
		border-radius: 50%;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		flex-shrink: 0;
		transition: background 0.15s, color 0.15s;
	}

	.attachment-remove:hover {
		background: rgba(239, 68, 68, 0.15);
		color: var(--color-error, #ef4444);
	}

	.input-row {
		display: flex;
		gap: 4px;
		align-items: flex-end;
	}

	.attach-btn {
		color: var(--color-text-secondary, #8888a0);
	}

	.attach-btn:hover:not(:disabled) {
		color: #22c55e;
	}

	.attach-container {
		position: relative;
	}

	.attach-dropdown {
		position: absolute;
		bottom: calc(100% + 6px);
		left: 0;
		background: var(--color-bg-secondary, #12121a);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 8px;
		box-shadow: var(--shadow-dropdown);
		overflow: hidden;
		z-index: 100;
		min-width: 140px;
	}

	.attach-option {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 8px 12px;
		background: none;
		border: none;
		color: var(--color-text-primary, #e8e8ed);
		font-size: 12px;
		cursor: pointer;
		transition: background 0.1s;
	}

	.attach-option:hover {
		background: var(--color-bg-elevated, #1a1a26);
	}

	.chat-input {
		flex: 1;
		background: transparent;
		border: none;
		outline: none;
		color: var(--color-text-primary, #e8e8ed);
		font-size: 13px;
		font-family: inherit;
		line-height: 1.5;
		resize: none;
		padding: 4px 0;
	}

	.chat-input::placeholder {
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.5;
	}

	.chat-input:disabled { opacity: 0.5; }

	.input-actions {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}

	.action-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: none;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
	}

	.action-btn:hover:not(:disabled) {
		background: oklch(from var(--color-text-primary) l c h / 5%);
		color: var(--color-text-primary, #e8e8ed);
	}

	.action-btn:disabled { opacity: 0.3; cursor: default; }

	.send-btn:not(:disabled) { color: #22c55e; }

	.send-btn:hover:not(:disabled) {
		background: oklch(from #22c55e l c h / 12%);
	}

	:global(.spin-icon) {
		animation: smith-spin 1s linear infinite;
	}

	@keyframes smith-spin {
		from { transform: rotate(0deg); }
		to { transform: rotate(360deg); }
	}

	/* ---- Code block syntax highlighting ---- */
	.message-content.markdown :global(.code-block-wrapper) {
		position: relative;
		margin: 8px 0;
		border-radius: 8px;
		overflow: hidden;
		border: 1px solid var(--color-border, #2a2a3a);
	}

	.message-content.markdown :global(.code-block-header) {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 4px 10px;
		background: oklch(from var(--color-text-primary) l c h / 3%);
		border-bottom: 1px solid var(--color-border, #2a2a3a);
	}

	.message-content.markdown :global(.code-lang) {
		font-size: 10px;
		font-weight: 600;
		color: var(--color-text-secondary, #8888a0);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.message-content.markdown :global(.code-copy-btn) {
		font-size: 10px;
		font-weight: 500;
		color: var(--color-text-secondary, #8888a0);
		background: none;
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 4px;
		padding: 2px 8px;
		cursor: pointer;
		transition: color 0.15s, border-color 0.15s;
	}

	.message-content.markdown :global(.code-copy-btn:hover) {
		color: var(--color-text-primary, #e8e8ed);
		border-color: var(--color-text-secondary, #8888a0);
	}

	.message-content.markdown :global(.code-copy-btn[data-copied='true']) {
		color: #22c55e;
		border-color: #22c55e;
	}

	.message-content.markdown :global(.code-block-wrapper pre) {
		margin: 0;
		border-radius: 0;
		border: none;
	}

	/* highlight.js theme (dark) */
	.message-content.markdown :global(.hljs) {
		color: #abb2bf;
		background: var(--color-code-bg, var(--color-bg-primary));
	}

	.message-content.markdown :global(.hljs-keyword),
	.message-content.markdown :global(.hljs-selector-tag),
	.message-content.markdown :global(.hljs-literal),
	.message-content.markdown :global(.hljs-section),
	.message-content.markdown :global(.hljs-link) {
		color: #c678dd;
	}

	.message-content.markdown :global(.hljs-string),
	.message-content.markdown :global(.hljs-addition) {
		color: #98c379;
	}

	.message-content.markdown :global(.hljs-number),
	.message-content.markdown :global(.hljs-regexp),
	.message-content.markdown :global(.hljs-meta) {
		color: #d19a66;
	}

	.message-content.markdown :global(.hljs-comment),
	.message-content.markdown :global(.hljs-quote) {
		color: #5c6370;
		font-style: italic;
	}

	.message-content.markdown :global(.hljs-title),
	.message-content.markdown :global(.hljs-name) {
		color: #61afef;
	}

	.message-content.markdown :global(.hljs-variable),
	.message-content.markdown :global(.hljs-template-variable) {
		color: #e06c75;
	}

	.message-content.markdown :global(.hljs-built_in),
	.message-content.markdown :global(.hljs-type) {
		color: #e6c07b;
	}

	.message-content.markdown :global(.hljs-attr),
	.message-content.markdown :global(.hljs-attribute) {
		color: #d19a66;
	}

	.message-content.markdown :global(.hljs-deletion) {
		color: #e06c75;
	}

	.message-content.markdown :global(.hljs-params) {
		color: #abb2bf;
	}

	.message-content.markdown :global(.hljs-function) {
		color: #61afef;
	}

	/* ---- Code view ---- */
	.code-area { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }

	.code-empty {
		display: flex; flex-direction: column; align-items: center; justify-content: center;
		gap: 10px; padding: 20px; color: var(--color-text-muted); font-size: 11px;
		text-align: center; flex: 1;
	}
	.generate-btn {
		display: flex; align-items: center; gap: 5px; padding: 5px 12px;
		border: 1px solid rgba(34, 197, 94, 0.3); border-radius: 6px;
		background: rgba(34, 197, 94, 0.08); color: #22c55e;
		font-size: 11px; cursor: pointer; transition: all 0.15s;
	}
	.generate-btn:hover { background: rgba(34, 197, 94, 0.15); border-color: #22c55e; }

	.code-generating {
		display: flex; align-items: center; justify-content: center;
		gap: 10px; height: 100%; color: var(--color-text-muted); font-size: 13px;
	}
	:global(.smith-spinner) { animation: smith-spin 1s linear infinite; }

	/* File list (compact) */
	.file-list {
		display: flex; flex-wrap: wrap; gap: 2px;
		padding: 6px 8px; border-bottom: 1px solid var(--color-border);
		background: var(--color-bg-secondary); flex-shrink: 0;
	}
	.file-item {
		display: flex; align-items: center; gap: 5px;
		padding: 4px 8px; border: none; background: transparent;
		color: var(--color-text-secondary); font-size: 11px;
		cursor: pointer; border-radius: 4px; transition: all 0.12s;
		font-family: var(--font-sans);
	}
	.file-item:hover { background: var(--color-overlay-subtle); color: var(--color-text-primary); }
	.file-item.active { background: rgba(34, 197, 94, 0.08); color: #22c55e; }
	.file-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.file-ext {
		font-size: 9px; font-weight: 600; padding: 1px 4px; border-radius: 2px;
		background: var(--color-overlay-subtle); color: var(--color-text-secondary);
		flex-shrink: 0; text-transform: uppercase;
	}
	.ext-python { background: rgba(53, 114, 165, 0.2); color: #5b9bd5; }
	.ext-js { background: rgba(240, 219, 79, 0.15); color: #f0db4f; }
	.ext-json { background: var(--color-overlay-subtle); color: var(--color-text-secondary); }
	.ext-yaml { background: rgba(203, 171, 81, 0.15); color: #cbab51; }
	.ext-md { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }

	.code-file-header {
		display: flex; align-items: center; justify-content: space-between; padding: 6px 12px;
		background: var(--color-bg-elevated); border-bottom: 1px solid var(--color-border); flex-shrink: 0;
	}
	.code-file-path { font-size: 11px; font-family: var(--font-mono, 'JetBrains Mono', monospace); color: var(--color-text-primary); }

	.copy-file-btn {
		display: flex; align-items: center; gap: 4px; padding: 2px 8px;
		border: 1px solid var(--color-border); border-radius: 4px;
		background: transparent; color: var(--color-text-secondary);
		font-size: 10px; cursor: pointer; transition: all 0.15s;
	}
	.copy-file-btn:hover { color: var(--color-text-primary); border-color: var(--color-text-secondary); }
	.copy-feedback { color: #22c55e; }

	.code-display-wrapper {
		flex: 1; overflow: auto;
		background: var(--color-code-bg, var(--color-bg-primary));
	}

	.code-table {
		width: 100%; border-collapse: collapse;
		font-family: var(--font-mono, 'JetBrains Mono', 'Fira Code', monospace);
		font-size: 12px; line-height: 1.6;
	}

	.code-line:hover { background: oklch(from var(--color-text-primary) l c h / 3%); }

	.line-number {
		width: 40px; min-width: 40px; padding: 0 10px 0 12px;
		text-align: right; user-select: none;
		color: var(--color-text-secondary); opacity: 0.4;
		font-size: 11px; vertical-align: top;
		border-right: 1px solid oklch(from var(--color-border) l c h / 50%);
	}

	.line-content {
		padding: 0 12px; white-space: pre; tab-size: 4;
		color: #abb2bf; background: transparent;
	}

	/* Syntax theme for code view (reuses hljs classes) */
	.line-content :global(.hljs-keyword),
	.line-content :global(.hljs-selector-tag),
	.line-content :global(.hljs-literal) { color: #c678dd; }
	.line-content :global(.hljs-string),
	.line-content :global(.hljs-addition) { color: #98c379; }
	.line-content :global(.hljs-number),
	.line-content :global(.hljs-regexp),
	.line-content :global(.hljs-meta) { color: #d19a66; }
	.line-content :global(.hljs-comment),
	.line-content :global(.hljs-quote) { color: #5c6370; font-style: italic; }
	.line-content :global(.hljs-title),
	.line-content :global(.hljs-name) { color: #61afef; }
	.line-content :global(.hljs-variable),
	.line-content :global(.hljs-template-variable) { color: #e06c75; }
	.line-content :global(.hljs-built_in),
	.line-content :global(.hljs-type) { color: #e6c07b; }
	.line-content :global(.hljs-attr),
	.line-content :global(.hljs-attribute) { color: #d19a66; }
	.line-content :global(.hljs-deletion) { color: #e06c75; }
	.line-content :global(.hljs-params) { color: #abb2bf; }
	.line-content :global(.hljs-function) { color: #61afef; }

	.code-placeholder {
		display: flex; align-items: center; justify-content: center;
		height: 100%; color: var(--color-text-muted); font-size: 13px;
	}
</style>
