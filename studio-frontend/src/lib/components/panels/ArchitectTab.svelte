<script lang="ts">
	import { onMount, onDestroy, untrack } from 'svelte';
	import { get } from 'svelte/store';
	import {
		SendHorizonal,
		Trash2,
		Bot,
		User,
		Wrench,
		Loader,
		ChevronRight,
		CheckCircle2,
		Zap,
		Paperclip,
		X,
		FileText,
		FileSpreadsheet,
		Presentation,
		Image,
		File,
		Copy,
		Check,
		ChevronDown,
		Plus,
		Camera
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
	import markdown from 'highlight.js/lib/languages/markdown';
	import {
		chatMessages,
		chatStreaming,
		addUserMessage,
		addAssistantMessage,
		appendToken,
		completeMessage,
		addToolCall,
		clearChat
	} from '$lib/stores/chat';

	// Plan card state
	interface PlanData {
		summary: string;
		steps: string[];
		options: string[];
		question: string;
		msgId: string;
	}
	let activePlan: PlanData | null = $state(null);
	import { settingsData } from '$lib/stores/settings';
	import { nodes, edges, resetNodeCounter } from '$lib/stores/pipeline';
	import { architectSidebarOpen, activeAgentTab, pendingArchitectMessage } from '$lib/stores/ui';
	import { currentProject as currentProjectStore } from '$lib/stores/project';
	import { api } from '$lib/api/client';
	import { syncCanvasToOracle } from '$lib/stores/oracle';
	import type { Node, Edge } from '@xyflow/svelte';

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
	hljs.registerLanguage('markdown', markdown);
	hljs.registerLanguage('md', markdown);

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
		data: string; // base64
		preview?: string; // data URL for image preview
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

	// Claude Code-style braille spinner animation
	const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
	const THINKING_MESSAGES = [
		'Drafting the blueprint...', 'Consulting the Oracle...', 'Aligning the nodes...',
		'Designing the inevitable...', 'Architecting a masterpiece...', 'Tracing the path of causality...',
		'Reshaping the construct...', 'Balancing the equation...', 'Loading the next iteration...',
		'Surveying the pipeline...', 'Engineering the solution...', 'Selecting the right components...',
		'Orchestrating the agents...', 'Running the simulation...', 'Weaving the connections...',
		'Compiling the grand design...', 'Evaluating all possible paths...', 'Constructing the framework...',
		'Visualizing the architecture...', 'Reticulating splines...',
	];

	let spinnerFrame = $state(SPINNER_FRAMES[0]);
	let currentThinkingMsg = $state(THINKING_MESSAGES[0]);
	let thinkingInterval: ReturnType<typeof setInterval> | null = null;
	let messageInterval: ReturnType<typeof setInterval> | null = null;
	let spinnerIdx = 0;
	let messageIdx = 0;

	const isThinking = $derived($chatMessages.some(m => m.streaming && !m.content));

	$effect(() => {
		if (isThinking) {
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

	const assistantName = $derived($settingsData?.user_profile?.assistant_name || 'The Architect');

	// Tool call display helpers
	let expandedToolGroups: Record<string, boolean> = $state({});

	function toggleToolGroup(msgId: string): void {
		expandedToolGroups[msgId] = !expandedToolGroups[msgId];
	}

	function toolCallSummary(toolCalls: { tool: string }[]): string {
		const counts: Record<string, number> = {};
		for (const tc of toolCalls) { counts[tc.tool] = (counts[tc.tool] || 0) + 1; }
		return Object.entries(counts).map(([name, count]) => (count > 1 ? `${name} x${count}` : name)).join(', ');
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

	let inputText = $state('');
	let messagesContainer: HTMLDivElement | undefined = $state(undefined);
	let inputElement: HTMLTextAreaElement | undefined = $state(undefined);
	let ws: WebSocket | null = $state(null);
	let currentAssistantMsgId = $state('');
	let connectionError = $state('');
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let reconnectAttempts = $state(0);
	let gotServerError = false;
	const MAX_RECONNECT_ATTEMPTS = 5;

	function applyCanvasSync(canvas: { nodes: any[]; edges: any[] }): void {
		nodes.update((current) => {
			const existingMap = new Map<string, Node>();
			for (const n of current) existingMap.set(n.id, n);
			for (const n of canvas.nodes) {
				const existing = existingMap.get(n.id);
				if (existing) {
					existing.data = { ...existing.data, label: n.label || existing.data.label, ...n.config };
					if (n.position) existing.position = n.position;
				}
			}
			const newNodes: Node[] = canvas.nodes
				.filter((n: any) => !existingMap.has(n.id))
				.map((n: any) => ({
					id: n.id, type: n.type,
					position: n.position ?? { x: 250, y: 200 },
					data: { label: n.label || n.id, origin: 'architect', ...n.config }
				}));

			// Auto-distribute new nodes at default position to avoid stacking
			const defaultPos = newNodes.filter(
				n => n.position.x === 250 && n.position.y === 200
			);
			if (defaultPos.length > 1) {
				defaultPos.forEach((n, i) => {
					n.position = { x: 250 + i * 300, y: 250 };
				});
			}

			return [...current, ...newNodes];
		});

		edges.update((current) => {
			const existingEdgeIds = new Set<string>();
			for (const e of current) existingEdgeIds.add(e.id);
			const newEdges: Edge[] = canvas.edges
				.filter((e: any) => !existingEdgeIds.has(e.id))
				.map((e: any) => ({
					id: e.id, source: e.source, target: e.target,
					sourceHandle: e.source_handle ?? undefined,
					targetHandle: e.target_handle ?? undefined
				}));
			return [...current, ...newEdges];
		});

		if (canvas.nodes.length === 0) {
			nodes.set([]);
			edges.set([]);
		}
		resetNodeCounter();
	}

	function getWsUrl(): string {
		const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
		const proj = get(currentProjectStore);
		const projectParam = proj ? `?project=${encodeURIComponent(proj.name)}` : '';
		return `${protocol}//${window.location.host}/ws/assistant${projectParam}`;
	}

	function connectWs(): void {
		if (ws && ws.readyState === WebSocket.OPEN) return;
		connectionError = '';
		gotServerError = false;
		let socket: WebSocket;
		try {
			socket = new WebSocket(getWsUrl());
		} catch {
			connectionError = 'AI Assistant requires a configured LLM provider. Check Settings.';
			return;
		}

		socket.onopen = () => {
			connectionError = '';
			reconnectAttempts = 0;
			const currentNodes = get(nodes);
			const currentEdges = get(edges);
			if (currentNodes.length > 0) {
				try {
					socket.send(JSON.stringify({
						action: 'sync_canvas',
						nodes: currentNodes.map(n => ({ id: n.id, type: n.type, position: n.position, data: n.data ?? {} })),
						edges: currentEdges.map(e => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle ?? undefined, targetHandle: e.targetHandle ?? undefined })),
					}));
				} catch {}
			}
			const pending = get(pendingArchitectMessage);
			if (pending) {
				pendingArchitectMessage.set(null);
				addUserMessage(pending.text);
				currentAssistantMsgId = addAssistantMessage();
				const payload: Record<string, unknown> = { action: 'chat', message: pending.text };
				if (pending.attachments && pending.attachments.length > 0) payload.attachments = pending.attachments;
				try { socket.send(JSON.stringify(payload)); } catch {
					connectionError = 'Failed to send initial message.';
					chatStreaming.set(false);
					currentAssistantMsgId = '';
				}
				scrollToBottom();
			}
		};

		socket.onmessage = (event) => {
			let data: Record<string, unknown>;
			try { data = JSON.parse(event.data); } catch { return; }

			if (data.type === 'token') {
				if (!currentAssistantMsgId) currentAssistantMsgId = addAssistantMessage();
				appendToken(currentAssistantMsgId, data.content as string);
				scrollToBottom();
			} else if (data.type === 'response_complete') {
				if (currentAssistantMsgId) completeMessage(currentAssistantMsgId, data.full_text as string);
				currentAssistantMsgId = '';
				scrollToBottom();
				const proj = get(currentProjectStore);
				if (proj) {
					const msgs = get(chatMessages);
					api.assistant.saveHistory(proj.name, msgs.map(m => ({
						role: m.role, content: m.content,
						timestamp: m.timestamp ?? new Date().toISOString(),
						toolCalls: m.toolCalls ?? [],
					}))).catch(() => {});
				}
			} else if (data.type === 'plan') {
				if (!currentAssistantMsgId) currentAssistantMsgId = addAssistantMessage();
				let steps: string[] = [];
				let options: string[] = [];
				try { steps = JSON.parse(data.steps as string); } catch { steps = []; }
				try { options = JSON.parse(data.options as string); } catch { options = []; }
				activePlan = {
					summary: (data.summary as string) || '', steps, options,
					question: (data.question as string) || '', msgId: currentAssistantMsgId,
				};
				scrollToBottom();
			} else if (data.type === 'tool_call') {
				if (!currentAssistantMsgId) currentAssistantMsgId = addAssistantMessage();
				if (data.tool === 'present_plan') { scrollToBottom(); return; }
				let args = data.args as Record<string, unknown>;
				if (typeof args === 'string') { try { args = JSON.parse(args); } catch { args = { raw: args }; } }
				if (!args || typeof args !== 'object' || Array.isArray(args)) args = {};
				addToolCall(currentAssistantMsgId, { tool: data.tool, args, result: data.result });
				scrollToBottom();
			} else if (data.type === 'canvas_sync') {
				const canvas = data.canvas as { nodes: any[]; edges: any[] };
				if (canvas) {
					applyCanvasSync(canvas);
					syncCanvasToOracle(canvas.nodes, canvas.edges);
					window.dispatchEvent(new CustomEvent('architect-canvas-complete'));
				}
			} else if (data.type === 'error') {
				connectionError = data.message as string;
				gotServerError = true;
				if (currentAssistantMsgId) completeMessage(currentAssistantMsgId, '');
				else chatStreaming.set(false);
				currentAssistantMsgId = '';
			}
		};

		socket.onclose = () => {
			if (currentAssistantMsgId) { completeMessage(currentAssistantMsgId, '[Connection lost]'); currentAssistantMsgId = ''; }
			else chatStreaming.set(false);
			ws = null;
			if (gotServerError) { gotServerError = false; reconnectAttempts = MAX_RECONNECT_ATTEMPTS; return; }
			reconnectAttempts++;
			if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
				connectionError = `Connecting to assistant... (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`;
				reconnectTimer = setTimeout(connectWs, 3000);
			} else {
				connectionError = 'Could not connect to AI Assistant. Ensure an LLM API key is configured in Settings.';
			}
		};
		socket.onerror = () => {};
		ws = socket;
	}

	function retryConnection(): void { reconnectAttempts = 0; connectWs(); }

	function disconnectWs(): void {
		if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
		ws?.close();
		ws = null;
	}

	function sendMessage(): void {
		const text = inputText.trim();
		if ((!text && attachments.length === 0) || $chatStreaming || !ws) return;
		const displayText = text || `[${attachments.length} file${attachments.length > 1 ? 's' : ''} attached]`;
		addUserMessage(displayText);
		currentAssistantMsgId = addAssistantMessage();
		const payload: Record<string, unknown> = { action: 'chat', message: text || 'Please analyze the attached files.' };
		if (attachments.length > 0) {
			payload.attachments = attachments.map((a) => ({
				name: a.name, type: a.type, category: a.category, size: a.size, data: a.data, docType: a.docType,
			}));
		}
		inputText = '';
		attachments = [];
		try { ws.send(JSON.stringify(payload)); } catch {
			connectionError = 'Failed to send message. Connection may be lost.';
			chatStreaming.set(false);
			currentAssistantMsgId = '';
			return;
		}
		scrollToBottom();
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); }
	}

	function handleClear(): void {
		clearChat();
		if (ws && ws.readyState === WebSocket.OPEN) {
			try { ws.send(JSON.stringify({ action: 'clear_history' })); } catch {}
		}
		connectionError = '';
	}

	function scrollToBottom(): void {
		requestAnimationFrame(() => {
			if (messagesContainer && messagesContainer.offsetParent !== null) {
				messagesContainer.scrollTop = messagesContainer.scrollHeight;
			}
		});
	}

	function formatTime(isoString: string): string {
		const d = new Date(isoString);
		return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
	}

	function selectPlanOption(option: string): void {
		if (!activePlan || !ws) return;
		addUserMessage(option);
		currentAssistantMsgId = addAssistantMessage();
		try { ws.send(JSON.stringify({ action: 'chat', message: option })); } catch {
			connectionError = 'Failed to send plan selection.';
			chatStreaming.set(false);
			currentAssistantMsgId = '';
		}
		activePlan = null;
		scrollToBottom();
	}

	// Reconnect WebSocket when project changes
	$effect(() => {
		const proj = $currentProjectStore;
		untrack(() => {
			if (proj && ws) { ws.close(); ws = null; connectWs(); }
		});
	});

	// Load chat history when project changes
	$effect(() => {
		const proj = $currentProjectStore;
		if (proj) {
			untrack(() => {
				clearChat();
				connectionError = '';
				api.assistant.getHistory(proj.name).then(history => {
					if (history && history.length > 0) {
						for (const msg of history) {
							if (msg.role === 'user') { addUserMessage(msg.content); }
							else if (msg.role === 'assistant') {
								chatMessages.update(msgs => [...msgs, {
									id: `msg_hist_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
									role: 'assistant' as const, content: msg.content,
									timestamp: msg.timestamp || new Date().toISOString(),
									streaming: false, toolCalls: (msg.toolCalls as any[]) ?? [],
								}]);
							}
						}
					}
				}).catch(() => {});
			});
		}
	});

	// Oracle-to-Architect bridge: listen for approved insights
	function handleOracleApproved(event: Event) {
		const detail = (event as CustomEvent).detail;
		const instruction = detail?.instruction;
		if (!instruction || !ws || ws.readyState !== WebSocket.OPEN) return;
		const prefix = '[Oracle Approved Insight]\n';
		const fullMsg = prefix + instruction;
		addUserMessage(fullMsg);
		currentAssistantMsgId = addAssistantMessage();
		try { ws.send(JSON.stringify({ action: 'chat', message: fullMsg })); } catch {
			connectionError = 'Failed to forward Oracle instruction.';
			chatStreaming.set(false);
			currentAssistantMsgId = '';
		}
		scrollToBottom();
		// Switch sidebar to Architect tab
		architectSidebarOpen.set(true);
		activeAgentTab.set('architect');
	}

	onMount(() => {
		connectWs();
		inputElement?.focus();
		window.addEventListener('oracle-approved', handleOracleApproved);
	});

	onDestroy(() => {
		disconnectWs();
		window.removeEventListener('oracle-approved', handleOracleApproved);
		if (thinkingInterval) clearInterval(thinkingInterval);
		if (messageInterval) clearInterval(messageInterval);
	});
</script>

<div class="architect-tab">
	<!-- Messages area -->
	<div class="messages" bind:this={messagesContainer}>
		{#if $chatMessages.length === 0}
			<div class="empty-state">
				<div class="empty-icon-circle">
					<Bot size={48} />
				</div>
				<span class="empty-title">{assistantName}</span>
				<span class="empty-hint"
					>{assistantName === 'The Architect'
						? 'I am The Architect. I designed the canvas upon which your agent pipelines take form. Describe what you wish to construct, and I shall design it.'
						: `Ask ${assistantName} to help build your agent pipeline.`}</span
				>
			</div>
		{:else}
			{#each $chatMessages as message (message.id)}
				<div class="message" class:user={message.role === 'user'} class:assistant={message.role === 'assistant'}>
					<div class="message-avatar">
						{#if message.role === 'user'}
							<User size={18} />
						{:else}
							<Bot size={18} />
						{/if}
					</div>
					<div class="message-body">
						<div class="message-header">
							<span class="message-role">{message.role === 'user' ? 'You' : assistantName}</span>
							<span class="message-time">{formatTime(message.timestamp)}</span>
						</div>
						<div class="message-content" class:markdown={message.role === 'assistant'}>
							{#if message.role === 'assistant'}
								{#if message.streaming && !message.content}
									<div class="thinking-indicator">
										<span class="thinking-spinner">{spinnerFrame}</span>
										{#key currentThinkingMsg}
											<span class="thinking-message">{currentThinkingMsg}</span>
										{/key}
									</div>
								{:else}
									{@html renderMarkdown(message.content)}
									{#if message.streaming}
										<span class="streaming-cursor"></span>
									{/if}
								{/if}
							{:else}
								{message.content}
							{/if}
						</div>
						{#if message.toolCalls && message.toolCalls.length > 0}
							<div class="tool-calls-container">
								<!-- svelte-ignore a11y_click_events_have_key_events -->
								<!-- svelte-ignore a11y_no_static_element_interactions -->
								<div class="tool-calls-header" onclick={() => toggleToolGroup(message.id)}>
									<div class="tool-calls-header-left">
										<div class="tool-chevron" class:expanded={expandedToolGroups[message.id]}>
											<ChevronRight size={12} />
										</div>
										<Zap size={12} />
										<span class="tool-calls-count">{message.toolCalls.length} tool call{message.toolCalls.length !== 1 ? 's' : ''}</span>
									</div>
									<span class="tool-calls-summary">{toolCallSummary(message.toolCalls)}</span>
								</div>
								{#if expandedToolGroups[message.id]}
									<div class="tool-calls-body">
										{#each message.toolCalls as tc, i}
											<div class="tool-call-item">
												<div class="tool-call-row">
													<span class="tool-call-index">{i + 1}</span>
													<span class="tool-call-name">{tc.tool}</span>
													{#if tc.result}
														<CheckCircle2 size={11} class="tool-call-ok" />
													{/if}
												</div>
												{#if tc.args && Object.keys(tc.args).length > 0}
													<div class="tool-call-args">
														{#each Object.entries(tc.args) as [key, val]}
															<div class="tool-arg-line">
																<span class="tool-arg-key">{key}:</span>
																<span class="tool-arg-val">{typeof val === 'string' ? val.length > 120 ? val.slice(0, 117) + '...' : val : JSON.stringify(val)}</span>
															</div>
														{/each}
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
		{/if}
	</div>

	<!-- Plan card -->
	{#if activePlan}
		<div class="plan-card">
			<div class="plan-header">
				<div class="plan-header-left">
					<div class="plan-icon"><Zap size={11} /></div>
					<span class="plan-title">Plan</span>
				</div>
				<button class="plan-dismiss" onclick={() => activePlan = null} title="Dismiss">
					<X size={12} />
				</button>
			</div>
			<div class="plan-body">
				{#if activePlan.summary}
					<p class="plan-summary">{activePlan.summary}</p>
				{/if}
				{#if activePlan.steps.length > 0}
					<div class="plan-steps">
						{#each activePlan.steps as step, i}
							<div class="plan-step">
								<span class="step-number">{i + 1}</span>
								<span class="step-text">{step}</span>
							</div>
						{/each}
					</div>
				{/if}
				{#if activePlan.question}
					<p class="plan-question">{activePlan.question}</p>
				{/if}
			</div>
			<div class="plan-footer">
				{#if activePlan.options.length > 0}
					<div class="plan-options">
						{#each activePlan.options as option, i}
							<button class="plan-option-btn" onclick={() => selectPlanOption(option)}>
								<span class="plan-option-key">{String.fromCharCode(65 + i)}</span>
								<span class="plan-option-text">{option}</span>
							</button>
						{/each}
					</div>
				{/if}
				<div class="plan-custom-input">
					<textarea
						class="plan-answer-input"
						placeholder={activePlan.options.length > 0 ? 'Or type your own response...' : 'Type your response...'}
						onkeydown={(e) => {
							if (e.key === 'Enter' && !e.shiftKey) {
								e.preventDefault();
								const target = e.currentTarget as HTMLTextAreaElement;
								if (target.value.trim()) selectPlanOption(target.value.trim());
							}
						}}
						rows={2}
					></textarea>
					<button class="plan-send-btn" title="Send" onclick={(e) => {
						const textarea = (e.currentTarget as HTMLElement).previousElementSibling as HTMLTextAreaElement;
						if (textarea?.value.trim()) selectPlanOption(textarea.value.trim());
					}}>
						<SendHorizonal size={12} />
					</button>
				</div>
			</div>
		</div>
	{/if}

	<!-- Error banner -->
	{#if connectionError}
		<div class="error-bar">
			<span>{connectionError}</span>
			{#if reconnectAttempts >= MAX_RECONNECT_ATTEMPTS}
				<button class="retry-btn" onclick={retryConnection}>Retry</button>
			{/if}
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
									{#if att.category === 'pdf'}<FileText size={14} />
									{:else if att.category === 'spreadsheet'}<FileSpreadsheet size={14} />
									{:else if att.category === 'presentation'}<Presentation size={14} />
									{:else if att.category === 'document'}<FileText size={14} />
									{:else if att.category === 'image'}<Image size={14} />
									{:else}<File size={14} />
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
							<button class="attachment-remove" onclick={() => removeAttachment(att.id)} title="Remove file">
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
				<button class="action-btn attach-btn" onclick={() => attachDropdownOpen = !attachDropdownOpen} title="Attach" disabled={$chatStreaming}>
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
			<input type="file" multiple accept={ACCEPT_STRING} bind:this={fileInputEl} onchange={handleFileSelect} class="file-input-hidden" />
			<textarea
				class="chat-input"
				placeholder="Ask {assistantName}..."
				bind:value={inputText}
				bind:this={inputElement}
				onkeydown={handleKeydown}
				onpaste={handlePaste}
				disabled={$chatStreaming}
				rows={1}
			></textarea>
			<div class="input-actions">
				<button class="action-btn clear-btn" onclick={handleClear} title="Clear chat" disabled={$chatMessages.length === 0}>
					<Trash2 size={14} />
				</button>
				<button class="action-btn send-btn" onclick={sendMessage} disabled={(!inputText.trim() && attachments.length === 0) || $chatStreaming || !ws} title="Send message">
					{#if $chatStreaming}
						<Loader size={14} class="spin-icon" />
					{:else}
						<SendHorizonal size={14} />
					{/if}
				</button>
			</div>
		</div>
	</div>
</div>

<style>
	.architect-tab {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	/* Messages */
	.messages {
		flex: 1;
		overflow-y: auto;
		padding: 16px;
		background: linear-gradient(180deg, oklch(from var(--color-accent) l c h / 2%) 0%, var(--color-bg-primary, #0a0a0f) 100%);
	}

	.empty-state {
		display: flex; flex-direction: column; align-items: center; justify-content: center;
		height: 100%; gap: 10px; color: var(--color-text-secondary, #8888a0); opacity: 0.7; padding: 24px;
	}
	.empty-icon-circle {
		width: 72px; height: 72px; border-radius: 50%;
		background: oklch(from var(--color-accent, #ff6b35) l c h / 10%);
		color: var(--color-accent, #ff6b35);
		display: flex; align-items: center; justify-content: center; margin-bottom: 4px;
	}
	.empty-title { font-size: 15px; font-weight: 600; color: var(--color-text-primary, #e8e8ed); }
	.empty-hint { font-size: 12px; color: var(--color-text-secondary, #8888a0); text-align: center; max-width: 320px; line-height: 1.5; }

	.message { display: flex; gap: 10px; margin-bottom: 16px; }
	.message-avatar {
		width: 32px; height: 32px; border-radius: 50%;
		display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px;
	}
	.message.user .message-avatar { background: oklch(from var(--color-accent, #ff6b35) l c h / 15%); color: var(--color-accent, #ff6b35); }
	.message.assistant .message-avatar { background: var(--color-overlay-subtle); color: var(--color-text-secondary, #8888a0); }
	.message-body { flex: 1; min-width: 0; }
	.message-header { display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; }
	.message-role { font-size: 12px; font-weight: 600; color: var(--color-text-primary, #e8e8ed); }
	.message-time { font-size: 10px; color: var(--color-text-secondary, #8888a0); opacity: 0.6; }
	.message-content { font-size: 13px; line-height: 1.6; color: var(--color-text-primary, #e8e8ed); white-space: pre-wrap; word-break: break-word; }
	.message.user .message-content { background: oklch(from var(--color-accent, #ff6b35) l c h / 10%); border-radius: 8px; padding: 8px 12px; }
	.message.assistant .message-content { background: var(--color-bg-elevated, #1a1a26); border-radius: 8px; padding: 8px 12px; }
	.message-content.markdown { white-space: normal; }
	.message-content.markdown :global(p) { margin: 0 0 8px; }
	.message-content.markdown :global(p:last-child) { margin-bottom: 0; }
	.message-content.markdown :global(h1), .message-content.markdown :global(h2), .message-content.markdown :global(h3) { margin: 12px 0 6px; font-weight: 600; line-height: 1.3; }
	.message-content.markdown :global(h1) { font-size: 16px; }
	.message-content.markdown :global(h2) { font-size: 14px; }
	.message-content.markdown :global(h3) { font-size: 13px; }
	.message-content.markdown :global(code) { font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace); font-size: 11px; background: var(--color-overlay-subtle); padding: 1px 4px; border-radius: 3px; }
	.message-content.markdown :global(pre) { background: var(--color-code-bg, var(--color-bg-primary)); border-radius: 6px; padding: 10px 12px; overflow-x: auto; margin: 8px 0; }
	.message-content.markdown :global(pre code) { background: none; padding: 0; font-size: 11px; line-height: 1.5; }
	.message-content.markdown :global(ul), .message-content.markdown :global(ol) { margin: 6px 0; padding-left: 20px; }
	.message-content.markdown :global(li) { margin-bottom: 2px; }
	.message-content.markdown :global(blockquote) { border-left: 3px solid var(--color-accent, #ff6b35); margin: 8px 0; padding: 4px 12px; color: var(--color-text-secondary, #8888a0); }
	.message-content.markdown :global(a) { color: var(--color-accent, #ff6b35); text-decoration: underline; }
	.message-content.markdown :global(table) { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 11px; }
	.message-content.markdown :global(th), .message-content.markdown :global(td) { border: 1px solid var(--color-border, #2a2a3a); padding: 4px 8px; text-align: left; }
	.message-content.markdown :global(th) { background: oklch(from var(--color-text-primary) l c h / 4%); font-weight: 600; }

	.streaming-cursor { display: inline-block; width: 6px; height: 14px; background: var(--color-accent, #ff6b35); margin-left: 2px; animation: blink 0.8s step-end infinite; vertical-align: text-bottom; }
	@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

	.thinking-indicator { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
	.thinking-spinner { font-size: 16px; font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace); color: var(--color-accent, #ff6b35); flex-shrink: 0; line-height: 1; }
	.thinking-message { font-size: 12px; color: var(--color-text-secondary, #8888a0); font-style: italic; animation: msg-fade 0.4s ease; }
	@keyframes msg-fade { from { opacity: 0; transform: translateX(4px); } to { opacity: 1; transform: translateX(0); } }

	/* Tool calls */
	.tool-calls-container { margin-top: 8px; border: 1px solid var(--color-border, #2a2a3a); border-radius: 8px; overflow: hidden; background: oklch(from var(--color-bg-primary) l c h / 50%); }
	.tool-calls-header { display: flex; align-items: center; justify-content: space-between; padding: 7px 10px; cursor: pointer; user-select: none; transition: background 0.15s ease; gap: 8px; }
	.tool-calls-header:hover { background: oklch(from var(--color-text-primary) l c h / 3%); }
	.tool-calls-header-left { display: flex; align-items: center; gap: 6px; color: var(--color-accent, #ff6b35); flex-shrink: 0; }
	.tool-chevron { display: flex; align-items: center; transition: transform 0.2s ease; }
	.tool-chevron.expanded { transform: rotate(90deg); }
	.tool-calls-count { font-size: 11px; font-weight: 600; white-space: nowrap; }
	.tool-calls-summary { font-size: 10px; color: var(--color-text-secondary, #8888a0); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: right; }
	.tool-calls-body { border-top: 1px solid var(--color-border, #2a2a3a); display: flex; flex-direction: column; }
	.tool-call-item { padding: 8px 10px; border-bottom: 1px solid oklch(from var(--color-text-primary) l c h / 3%); }
	.tool-call-item:last-child { border-bottom: none; }
	.tool-call-row { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }
	.tool-call-index { width: 16px; height: 16px; border-radius: 50%; background: var(--color-overlay-subtle); color: var(--color-text-secondary, #8888a0); font-size: 9px; font-weight: 600; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
	.tool-call-name { font-size: 11px; font-weight: 600; color: var(--color-accent, #ff6b35); }
	:global(.tool-call-ok) { color: #4ade80; flex-shrink: 0; }
	.tool-call-args { margin: 4px 0 0 22px; display: flex; flex-direction: column; gap: 1px; }
	.tool-arg-line { display: flex; gap: 6px; font-size: 10px; line-height: 1.5; }
	.tool-arg-key { color: var(--color-text-secondary, #8888a0); font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace); flex-shrink: 0; }
	.tool-arg-val { color: var(--color-text-primary, #e8e8ed); font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace); word-break: break-word; }
	.tool-call-result { margin: 4px 0 0 22px; padding: 4px 8px; background: rgba(74, 222, 128, 0.06); border-left: 2px solid rgba(74, 222, 128, 0.3); border-radius: 0 4px 4px 0; display: flex; gap: 6px; font-size: 10px; line-height: 1.5; }
	.tool-result-label { color: #4ade80; font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace); font-weight: 600; flex-shrink: 0; }
	.tool-result-val { color: var(--color-text-secondary, #8888a0); font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace); word-break: break-word; }

	/* Error bar */
	.error-bar { display: flex; align-items: center; gap: 8px; padding: 6px 12px; background: rgba(239, 68, 68, 0.1); border-top: 1px solid rgba(239, 68, 68, 0.2); font-size: 11px; color: var(--color-error, #ef4444); flex-shrink: 0; }
	.retry-btn { margin-left: auto; padding: 2px 10px; border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 4px; background: rgba(239, 68, 68, 0.15); color: var(--color-error, #ef4444); font-size: 11px; cursor: pointer; white-space: nowrap; }
	.retry-btn:hover { background: rgba(239, 68, 68, 0.25); }

	/* Input area */
	.input-area { flex-shrink: 0; border-top: 1px solid var(--color-border, #2a2a3a); padding: 8px 12px; display: flex; flex-direction: column; gap: 6px; }
	.file-input-hidden { display: none; }
	.attachment-badges { display: flex; flex-wrap: wrap; gap: 6px; }
	.attachment-badge { display: flex; align-items: center; gap: 6px; padding: 4px 8px; background: var(--color-bg-elevated, #1a1a26); border: 1px solid var(--color-border, #2a2a3a); border-radius: 8px; max-width: 200px; transition: border-color 0.15s; }
	.attachment-badge:hover { border-color: var(--color-text-secondary, #8888a0); }
	.attachment-badge.has-preview { padding: 3px 8px 3px 3px; }
	.attachment-thumb { width: 32px; height: 32px; object-fit: cover; border-radius: 5px; flex-shrink: 0; }
	.attachment-icon { width: 28px; height: 28px; border-radius: 6px; background: oklch(from var(--color-accent, #ff6b35) l c h / 10%); color: var(--color-accent, #ff6b35); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
	.attachment-info { display: flex; flex-direction: column; min-width: 0; }
	.attachment-name { font-size: 11px; font-weight: 500; color: var(--color-text-primary, #e8e8ed); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.attachment-badge-wrapper { position: relative; }
	.attachment-type-btn { display: inline-flex; align-items: center; gap: 3px; background: none; border: none; padding: 0; cursor: pointer; font-size: 9px; color: var(--color-text-secondary, #8888a0); transition: color 0.15s; }
	.attachment-type-btn:hover { color: var(--color-accent, #ff6b35); }
	.type-dropdown { position: absolute; bottom: calc(100% + 4px); left: 0; min-width: 160px; background: var(--color-bg-secondary, #12121a); border: 1px solid var(--color-border, #2a2a3a); border-radius: 8px; box-shadow: var(--shadow-dropdown); z-index: 100; overflow: hidden; padding: 4px; }
	.type-option { display: block; width: 100%; text-align: left; padding: 5px 10px; border: none; background: transparent; border-radius: 5px; color: var(--color-text-primary, #e8e8ed); font-size: 11px; cursor: pointer; transition: background 0.1s; }
	.type-option:hover { background: var(--color-overlay-subtle); }
	.type-option.selected { color: var(--color-accent, #ff6b35); background: oklch(from var(--color-accent, #ff6b35) l c h / 10%); }
	.attachment-remove { display: flex; align-items: center; justify-content: center; width: 18px; height: 18px; border: none; background: transparent; border-radius: 50%; color: var(--color-text-secondary, #8888a0); cursor: pointer; flex-shrink: 0; transition: background 0.15s, color 0.15s; }
	.attachment-remove:hover { background: rgba(239, 68, 68, 0.15); color: var(--color-error, #ef4444); }

	.input-row { display: flex; gap: 4px; align-items: flex-end; }
	.attach-btn { color: var(--color-text-secondary, #8888a0); }
	.attach-btn:hover:not(:disabled) { color: var(--color-accent, #ff6b35); }
	.attach-container { position: relative; }
	.attach-dropdown { position: absolute; bottom: calc(100% + 6px); left: 0; background: var(--color-bg-secondary, #12121a); border: 1px solid var(--color-border, #2a2a3a); border-radius: 8px; box-shadow: var(--shadow-dropdown); overflow: hidden; z-index: 100; min-width: 140px; }
	.attach-option { display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 12px; background: none; border: none; color: var(--color-text-primary, #e8e8ed); font-size: 12px; cursor: pointer; transition: background 0.1s; }
	.attach-option:hover { background: var(--color-bg-elevated, #1a1a26); }

	.chat-input { flex: 1; background: transparent; border: none; outline: none; color: var(--color-text-primary, #e8e8ed); font-size: 13px; font-family: inherit; line-height: 1.5; resize: none; padding: 4px 0; }
	.chat-input::placeholder { color: var(--color-text-secondary, #8888a0); opacity: 0.5; }
	.chat-input:disabled { opacity: 0.5; }
	.input-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
	.action-btn { display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; border: none; background: transparent; border-radius: 4px; color: var(--color-text-secondary, #8888a0); cursor: pointer; transition: background 0.15s ease, color 0.15s ease; }
	.action-btn:hover:not(:disabled) { background: oklch(from var(--color-text-primary) l c h / 5%); color: var(--color-text-primary, #e8e8ed); }
	.action-btn:disabled { opacity: 0.3; cursor: default; }
	.send-btn:not(:disabled) { color: var(--color-accent, #ff6b35); }
	.send-btn:hover:not(:disabled) { background: oklch(from var(--color-accent, #ff6b35) l c h / 12%); }
	:global(.spin-icon) { animation: chat-spin 1s linear infinite; }
	@keyframes chat-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

	/* Code block syntax highlighting */
	.message-content.markdown :global(.code-block-wrapper) { position: relative; margin: 8px 0; border-radius: 8px; overflow: hidden; border: 1px solid var(--color-border, #2a2a3a); }
	.message-content.markdown :global(.code-block-header) { display: flex; align-items: center; justify-content: space-between; padding: 4px 10px; background: oklch(from var(--color-text-primary) l c h / 3%); border-bottom: 1px solid var(--color-border, #2a2a3a); }
	.message-content.markdown :global(.code-lang) { font-size: 10px; font-weight: 600; color: var(--color-text-secondary, #8888a0); text-transform: uppercase; letter-spacing: 0.04em; }
	.message-content.markdown :global(.code-copy-btn) { font-size: 10px; font-weight: 500; color: var(--color-text-secondary, #8888a0); background: none; border: 1px solid var(--color-border, #2a2a3a); border-radius: 4px; padding: 2px 8px; cursor: pointer; transition: color 0.15s, border-color 0.15s; }
	.message-content.markdown :global(.code-copy-btn:hover) { color: var(--color-text-primary, #e8e8ed); border-color: var(--color-text-secondary, #8888a0); }
	.message-content.markdown :global(.code-copy-btn[data-copied='true']) { color: var(--color-success, #22c55e); border-color: var(--color-success, #22c55e); }
	.message-content.markdown :global(.code-block-wrapper pre) { margin: 0; border-radius: 0; border: none; }

	/* highlight.js theme */
	.message-content.markdown :global(.hljs) { color: #abb2bf; background: var(--color-code-bg, var(--color-bg-primary)); }
	.message-content.markdown :global(.hljs-keyword), .message-content.markdown :global(.hljs-selector-tag), .message-content.markdown :global(.hljs-literal), .message-content.markdown :global(.hljs-section), .message-content.markdown :global(.hljs-link) { color: #c678dd; }
	.message-content.markdown :global(.hljs-string), .message-content.markdown :global(.hljs-addition) { color: #98c379; }
	.message-content.markdown :global(.hljs-number), .message-content.markdown :global(.hljs-regexp), .message-content.markdown :global(.hljs-meta) { color: #d19a66; }
	.message-content.markdown :global(.hljs-comment), .message-content.markdown :global(.hljs-quote) { color: #5c6370; font-style: italic; }
	.message-content.markdown :global(.hljs-title), .message-content.markdown :global(.hljs-name) { color: #61afef; }
	.message-content.markdown :global(.hljs-variable), .message-content.markdown :global(.hljs-template-variable) { color: #e06c75; }
	.message-content.markdown :global(.hljs-built_in), .message-content.markdown :global(.hljs-type) { color: #e6c07b; }
	.message-content.markdown :global(.hljs-attr), .message-content.markdown :global(.hljs-attribute) { color: #d19a66; }
	.message-content.markdown :global(.hljs-deletion) { color: #e06c75; }
	.message-content.markdown :global(.hljs-params) { color: #abb2bf; }
	.message-content.markdown :global(.hljs-function) { color: #61afef; }

	/* Plan card */
	.plan-card { flex-shrink: 0; margin: 0 10px 8px; border: 1px solid var(--color-border, #2a2a3a); border-radius: 12px; background: var(--color-bg-elevated, #1a1a26); overflow: hidden; animation: planSlideUp 0.25s ease-out; max-height: min(55vh, 440px); display: flex; flex-direction: column; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25); }
	@keyframes planSlideUp { from { transform: translateY(12px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
	.plan-header { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border-bottom: 1px solid var(--color-border, #2a2a3a); flex-shrink: 0; }
	.plan-header-left { display: flex; align-items: center; gap: 7px; }
	.plan-icon { width: 22px; height: 22px; border-radius: 6px; background: oklch(from var(--color-accent, #ff6b35) l c h / 12%); color: var(--color-accent, #ff6b35); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
	.plan-title { font-size: 12px; font-weight: 600; color: var(--color-text-primary, #e8e8ed); letter-spacing: 0.02em; }
	.plan-dismiss { display: flex; align-items: center; justify-content: center; width: 22px; height: 22px; border: none; background: transparent; border-radius: 5px; color: var(--color-text-secondary, #8888a0); cursor: pointer; flex-shrink: 0; transition: background 0.15s, color 0.15s; }
	.plan-dismiss:hover { background: var(--color-overlay-light); color: var(--color-text-primary, #e8e8ed); }
	.plan-body { flex: 1; overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--color-border, #2a2a3a) transparent; padding: 10px 12px 6px; }
	.plan-summary { font-size: 12px; line-height: 1.55; color: var(--color-text-primary, #e8e8ed); margin: 0 0 8px; }
	.plan-steps { display: flex; flex-direction: column; gap: 2px; margin: 0 0 6px; }
	.plan-step { display: flex; align-items: flex-start; gap: 8px; padding: 5px 8px; font-size: 12px; line-height: 1.5; color: var(--color-text-primary, #e8e8ed); border-radius: 6px; transition: background 0.1s; }
	.plan-step:hover { background: oklch(from var(--color-text-primary) l c h / 3%); }
	.step-number { width: 18px; height: 18px; border-radius: 5px; background: var(--color-overlay-subtle); color: var(--color-text-secondary, #8888a0); font-size: 10px; font-weight: 600; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }
	.step-text { flex: 1; }
	.plan-question { font-size: 12px; font-weight: 500; color: var(--color-text-primary, #e8e8ed); margin: 4px 0 2px; line-height: 1.5; }
	.plan-footer { flex-shrink: 0; border-top: 1px solid var(--color-border, #2a2a3a); padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; }
	.plan-options { display: flex; flex-direction: column; gap: 4px; }
	.plan-option-btn { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border: 1px solid var(--color-border, #2a2a3a); border-radius: 8px; background: var(--color-bg-secondary, #12121a); color: var(--color-text-primary, #e8e8ed); cursor: pointer; font-size: 12px; line-height: 1.4; text-align: left; transition: border-color 0.15s, background 0.15s; }
	.plan-option-btn:hover { border-color: var(--color-accent, #ff6b35); background: oklch(from var(--color-accent, #ff6b35) l c h / 6%); }
	.plan-option-key { width: 20px; height: 20px; border-radius: 5px; background: var(--color-overlay-subtle); color: var(--color-text-secondary, #8888a0); font-size: 10px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace); transition: background 0.15s, color 0.15s; }
	.plan-option-btn:hover .plan-option-key { background: oklch(from var(--color-accent, #ff6b35) l c h / 15%); color: var(--color-accent, #ff6b35); }
	.plan-option-text { flex: 1; }
	.plan-custom-input { display: flex; align-items: flex-end; gap: 4px; }
	.plan-answer-input { flex: 1; background: var(--color-bg-primary, #0e0e14); border: 1px solid var(--color-border, #2a2a3a); border-radius: 8px; color: var(--color-text-primary, #e8e8ed); font-size: 12px; font-family: inherit; padding: 7px 10px; resize: none; outline: none; transition: border-color 0.15s; box-sizing: border-box; }
	.plan-answer-input:focus { border-color: var(--color-accent, #ff6b35); }
	.plan-answer-input::placeholder { color: var(--color-text-secondary, #8888a0); opacity: 0.4; }
	.plan-send-btn { display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; border: none; background: transparent; border-radius: 6px; color: var(--color-text-secondary, #8888a0); cursor: pointer; flex-shrink: 0; transition: background 0.15s, color 0.15s; }
	.plan-send-btn:hover { background: oklch(from var(--color-accent, #ff6b35) l c h / 12%); color: var(--color-accent, #ff6b35); }
</style>
