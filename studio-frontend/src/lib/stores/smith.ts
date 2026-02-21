import { writable, derived, get } from 'svelte/store';
import { api } from '$lib/api/client';
import { currentProject } from '$lib/stores/project';
import { nodes, edges } from '$lib/stores/pipeline';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SmithMessage {
	role: 'user' | 'assistant';
	content: string;
	timestamp: string;
	toolCalls?: Array<{ name: string; args: string; result: string }>;
}

interface PendingCommand {
	commandId: string;
	command: string;
	level: string;
}

export interface SmithFile {
	path: string;
	content: string;
	language: string;
}

// ---------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------

export const smithMessages = writable<SmithMessage[]>([]);
export const smithCode = writable<string>('');
export const smithFiles = writable<SmithFile[]>([]);
export const smithActiveFile = writable<string | null>(null);
export const smithIsThinking = writable(false);
export const smithConnected = writable(false);
export const pendingCommand = writable<PendingCommand | null>(null);

// ---------------------------------------------------------------------------
// WebSocket connection with reconnect
// ---------------------------------------------------------------------------

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempts = 0;
const MAX_RECONNECT = 5;
let intentionalClose = false;
let currentSmithProject = '';

function getWsUrl(): string {
	const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	const proj = get(currentProject);
	const projectParam = proj?.name ? `?project=${encodeURIComponent(proj.name)}` : '';
	currentSmithProject = proj?.name ?? '';
	return `${protocol}//${window.location.host}/ws/smith${projectParam}`;
}

function attemptReconnect(): void {
	if (intentionalClose) return;
	if (reconnectAttempts >= MAX_RECONNECT) return;
	reconnectAttempts++;
	const delay = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), 10000);
	reconnectTimer = setTimeout(() => {
		connectSmith();
	}, delay);
}

export function connectSmith(): void {
	if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
	intentionalClose = false;

	try {
		ws = new WebSocket(getWsUrl());
	} catch {
		return;
	}

	ws.onopen = () => {
		reconnectAttempts = 0;
		smithConnected.set(true);
		// Sync current canvas state on connect and start auto-sync
		syncCanvasToSmith();
		startCanvasAutoSync();
	};

	ws.onclose = () => {
		smithConnected.set(false);
		smithIsThinking.set(false);
		stopCanvasAutoSync();
		ws = null;
		attemptReconnect();
	};

	ws.onerror = () => {
		smithConnected.set(false);
	};

	ws.onmessage = (event) => {
		try {
			const data = JSON.parse(event.data);
			handleSmithMessage(data);
		} catch {
			// ignore malformed messages
		}
	};
}

function handleSmithMessage(data: Record<string, unknown>): void {
	const type = data.type as string;

	if (type === 'smith_token') {
		// Append streaming token to the last assistant message or create one
		const token = (data.content ?? data.token ?? '') as string;
		smithMessages.update((msgs) => {
			const last = msgs[msgs.length - 1];
			if (last && last.role === 'assistant' && !data.complete) {
				return [...msgs.slice(0, -1), { ...last, content: last.content + token }];
			}
			return [...msgs, { role: 'assistant', content: token, timestamp: new Date().toISOString() }];
		});
	} else if (type === 'smith_response_complete') {
		smithIsThinking.set(false);
		if (data.code) {
			smithCode.set(data.code as string);
		}
		const content = (data.full_text ?? data.content ?? '') as string;
		if (content) {
			smithMessages.update((msgs) => {
				const last = msgs[msgs.length - 1];
				// Replace streamed tokens with the final complete text
				if (last && last.role === 'assistant') {
					return [...msgs.slice(0, -1), { ...last, content }];
				}
				return [...msgs, { role: 'assistant', content, timestamp: new Date().toISOString() }];
			});
		} else if (data.code) {
			// Code-only response with no narrative — remove streamed placeholder
			smithMessages.update((msgs) => {
				const last = msgs[msgs.length - 1];
				if (last && last.role === 'assistant' && !last.content.trim()) {
					return msgs.slice(0, -1);
				}
				return msgs;
			});
		}
		// Auto-save chat history
		_autoSaveSmithHistory();
	} else if (type === 'code_generated') {
		const code = data.code as string;
		smithCode.set(code);
		smithFiles.set([{ path: 'main.py', content: code, language: 'python' }]);
		smithActiveFile.set('main.py');
		smithIsThinking.set(false);
	} else if (type === 'files_generated') {
		const files = (data.files ?? []) as SmithFile[];
		smithFiles.set(files);
		smithIsThinking.set(false);
		if (files.length > 0) {
			smithActiveFile.set(files[0].path);
		}
		const combined = files.map(f => `# --- ${f.path} ---\n${f.content}`).join('\n\n');
		smithCode.set(combined);
		// Auto-save generated files
		_autoSaveSmithFiles(files);
	} else if (type === 'approval_required') {
		pendingCommand.set({
			commandId: data.command_id as string,
			command: data.command as string,
			level: data.level as string,
		});
	} else if (type === 'execution_result') {
		const stdout = (data.stdout as string) || '';
		const stderr = (data.stderr as string) || '';
		const rc = data.return_code ?? 0;
		let output = stdout;
		if (stderr) output += (output ? '\n' : '') + `[stderr] ${stderr}`;
		if (rc !== 0) output += `\n[exit code: ${rc}]`;
		smithMessages.update((msgs) => [
			...msgs,
			{ role: 'assistant', content: output || '(no output)', timestamp: new Date().toISOString() },
		]);
		smithIsThinking.set(false);
	} else if (type === 'tool_call') {
		// Tool call visibility -- attach to last assistant message's toolCalls
		const toolCall = {
			name: (data.tool ?? data.name ?? 'unknown') as string,
			args: typeof data.args === 'string' ? data.args : JSON.stringify(data.args || {}),
			result: typeof data.result === 'string' ? data.result : JSON.stringify(data.result || ''),
		};
		smithMessages.update((msgs) => {
			const last = msgs[msgs.length - 1];
			if (last && last.role === 'assistant') {
				const calls = [...(last.toolCalls || []), toolCall];
				return [...msgs.slice(0, -1), { ...last, toolCalls: calls }];
			}
			// No assistant message yet -- create one to hold the tool call
			return [...msgs, { role: 'assistant', content: '', timestamp: new Date().toISOString(), toolCalls: [toolCall] }];
		});
	} else if (type === 'canvas_synced') {
		// Acknowledgement, nothing to do
	} else if (type === 'error') {
		smithIsThinking.set(false);
		smithMessages.update((msgs) => [
			...msgs,
			{ role: 'assistant', content: `Error: ${data.message}`, timestamp: new Date().toISOString() },
		]);
	}
}

function send(action: string, payload: Record<string, unknown> = {}): void {
	if (!ws || ws.readyState !== WebSocket.OPEN) return;
	ws.send(JSON.stringify({ action, ...payload }));
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Sync the current canvas graph to Smith's per-connection state.
 * Can be called with an explicit graph or will read from pipeline stores.
 */
export function syncCanvasToSmith(graph?: object): void {
	if (graph) {
		send('sync_canvas', graph as Record<string, unknown>);
		return;
	}
	const currentNodes = get(nodes);
	const currentEdges = get(edges);
	send('sync_canvas', {
		nodes: currentNodes.map((n: any) => ({
			id: n.id,
			type: n.type,
			data: n.data,
			position: n.position,
		})),
		edges: currentEdges.map((e: any) => ({
			id: e.id,
			source: e.source,
			target: e.target,
		})),
	});
}

export function generateCode(graph?: object): void {
	smithIsThinking.set(true);
	if (graph) {
		send('generate', { graph });
	} else {
		send('generate');
	}
}

export function triggerSmithGeneration(): void {
	generateCode();
}

export function executeCode(code: string): void {
	smithIsThinking.set(true);
	send('execute', { code });
}

// --- Canvas auto-sync (debounced) ---

let syncTimeout: ReturnType<typeof setTimeout> | null = null;
let autoSyncUnsub: (() => void) | null = null;

export function startCanvasAutoSync(): void {
	stopCanvasAutoSync();
	const combined = derived([nodes, edges], ([$n, $e]) => ({ nodes: $n, edges: $e }));
	autoSyncUnsub = combined.subscribe(({ nodes: n, edges: e }) => {
		if (syncTimeout) clearTimeout(syncTimeout);
		syncTimeout = setTimeout(() => {
			syncCanvasToSmith({
				nodes: n.map((nd: any) => ({ id: nd.id, type: nd.type, data: nd.data, position: nd.position })),
				edges: e.map((ed: any) => ({ id: ed.id, source: ed.source, target: ed.target })),
			});
		}, 500);
	});
}

export function stopCanvasAutoSync(): void {
	if (autoSyncUnsub) {
		autoSyncUnsub();
		autoSyncUnsub = null;
	}
	if (syncTimeout) {
		clearTimeout(syncTimeout);
		syncTimeout = null;
	}
}

export function chatWithSmith(message: string): void {
	smithMessages.update((msgs) => [
		...msgs,
		{ role: 'user', content: message, timestamp: new Date().toISOString() },
	]);
	smithIsThinking.set(true);
	send('chat', { message });
}

export function approveCommand(commandId: string, approved: boolean): void {
	send('approve_command', { command_id: commandId, approved });
	pendingCommand.set(null);
	if (approved) {
		smithIsThinking.set(true);
	}
}

export function disconnectSmith(): void {
	intentionalClose = true;
	stopCanvasAutoSync();
	if (reconnectTimer) {
		clearTimeout(reconnectTimer);
		reconnectTimer = null;
	}
	ws?.close();
	ws = null;
}

// ---------------------------------------------------------------------------
// Persistence — auto-save & load
// ---------------------------------------------------------------------------

function _autoSaveSmithHistory(): void {
	if (!currentSmithProject) return;
	const msgs = get(smithMessages).map((m) => ({
		role: m.role,
		content: m.content,
		timestamp: m.timestamp,
	}));
	api.smith.saveHistory(currentSmithProject, msgs).catch(() => {});
}

function _autoSaveSmithFiles(files: SmithFile[]): void {
	if (!currentSmithProject) return;
	api.smith.saveFiles(currentSmithProject, files).catch(() => {});
}

export async function loadSmithHistory(project: string): Promise<void> {
	try {
		const msgs = await api.smith.getHistory(project);
		if (msgs.length > 0) {
			smithMessages.set(
				msgs.map((m) => ({
					role: m.role as 'user' | 'assistant',
					content: m.content,
					timestamp: m.timestamp,
				}))
			);
		}
	} catch {
		// No saved history — start fresh
	}
}

export async function loadSmithFiles(project: string): Promise<void> {
	try {
		const files = await api.smith.getFiles(project);
		if (files.length > 0) {
			smithFiles.set(files);
			smithActiveFile.set(files[0].path);
			const combined = files.map((f) => `# --- ${f.path} ---\n${f.content}`).join('\n\n');
			smithCode.set(combined);
		}
	} catch {
		// No saved files — start fresh
	}
}

export function clearSmithChat(): void {
	smithMessages.set([]);
	smithCode.set('');
	smithFiles.set([]);
	smithActiveFile.set(null);
	if (currentSmithProject) {
		api.smith.clearHistory(currentSmithProject).catch(() => {});
	}
}
