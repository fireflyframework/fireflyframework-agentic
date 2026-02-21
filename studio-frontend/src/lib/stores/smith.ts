import { writable, derived, get } from 'svelte/store';
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

// ---------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------

export const smithMessages = writable<SmithMessage[]>([]);
export const smithCode = writable<string>('');
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

function getWsUrl(): string {
	const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	return `${protocol}//${window.location.host}/ws/smith`;
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
		// If this response includes generated code, update only the code pane
		if (data.code) {
			smithCode.set(data.code as string);
		}
		// Only add full_text as a chat message when it is NOT a code response
		const content = (data.full_text ?? data.content ?? '') as string;
		if (content && !data.code) {
			smithMessages.update((msgs) => {
				const last = msgs[msgs.length - 1];
				// If last message was streamed, replace it with complete content
				if (last && last.role === 'assistant') {
					return [...msgs.slice(0, -1), { ...last, content }];
				}
				return [...msgs, { role: 'assistant', content, timestamp: new Date().toISOString() }];
			});
		}
	} else if (type === 'code_generated') {
		smithCode.set(data.code as string);
		smithIsThinking.set(false);
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
