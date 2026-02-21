import { writable, derived, get } from 'svelte/store';
import { api } from '$lib/api/client';
import { StudioWebSocket } from '$lib/api/websocket';
import type { ExecutionEvent } from '$lib/types/graph';
import { nodes, edges } from './pipeline';
import { chatMessages } from './chat';
import { currentProject } from './project';

export interface OracleInsight {
	id: string;
	title: string;
	description: string;
	severity: 'info' | 'warning' | 'suggestion' | 'critical';
	action_instruction: string | null;
	timestamp: string;
	status: 'pending' | 'approved' | 'skipped';
}

export interface OracleChatMessage {
	id: string;
	role: 'user' | 'oracle';
	content: string;
	timestamp: string;
	streaming?: boolean;
}

export const oracleInsights = writable<OracleInsight[]>([]);
export const oracleConnected = writable(false);
export const oracleAnalyzing = writable(false);
export const oracleChatMessages = writable<OracleChatMessage[]>([]);
export const oracleChatStreaming = writable(false);

let oracleWs: StudioWebSocket | null = null;
let chatMsgCounter = 0;
let currentOracleMsgId = '';

// --- Canvas auto-sync ---
let syncTimeout: ReturnType<typeof setTimeout> | null = null;
let autoSyncUnsub: (() => void) | null = null;

export function syncCanvasToOracle(n?: unknown[], e?: unknown[]): void {
	if (oracleWs?.connected) {
		const syncNodes = n ?? get(nodes);
		const syncEdges = e ?? get(edges);
		oracleWs.send({ action: 'sync_canvas', nodes: syncNodes, edges: syncEdges });
	}
}

export function startCanvasAutoSync(): void {
	// Prevent duplicate subscriptions
	stopCanvasAutoSync();

	const combined = derived([nodes, edges], ([$n, $e]) => ({ nodes: $n, edges: $e }));
	autoSyncUnsub = combined.subscribe(({ nodes: n, edges: e }) => {
		if (syncTimeout) clearTimeout(syncTimeout);
		syncTimeout = setTimeout(() => {
			syncCanvasToOracle(n, e);
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

// --- WebSocket connection ---

export function connectOracle(project: string): void {
	disconnectOracle();

	oracleWs = new StudioWebSocket(`/ws/oracle?project=${encodeURIComponent(project)}`);

	oracleWs.on('_open', () => {
		oracleConnected.set(true);
		// Send initial canvas state and start auto-sync
		syncCanvasToOracle();
		startCanvasAutoSync();
	});

	oracleWs.on('_close', () => {
		oracleConnected.set(false);
		stopCanvasAutoSync();
	});

	oracleWs.on('insight', (data: ExecutionEvent) => {
		const insight = data as unknown as OracleInsight;
		oracleInsights.update((list) => [insight, ...list]);
	});

	oracleWs.on('analysis_complete', () => {
		oracleAnalyzing.set(false);
	});

	oracleWs.on('oracle_token', (data: ExecutionEvent) => {
		const token = (data as any).content as string;
		if (!currentOracleMsgId) {
			currentOracleMsgId = `oracle_msg_${++chatMsgCounter}`;
			oracleChatMessages.update((msgs) => [
				...msgs,
				{
					id: currentOracleMsgId,
					role: 'oracle',
					content: '',
					timestamp: new Date().toISOString(),
					streaming: true,
				},
			]);
			oracleChatStreaming.set(true);
		}
		oracleChatMessages.update((msgs) =>
			msgs.map((m) => (m.id === currentOracleMsgId ? { ...m, content: m.content + token } : m))
		);
	});

	oracleWs.on('oracle_response_complete', (data: ExecutionEvent) => {
		const fullText = (data as any).full_text as string;
		if (currentOracleMsgId) {
			oracleChatMessages.update((msgs) =>
				msgs.map((m) =>
					m.id === currentOracleMsgId ? { ...m, content: fullText, streaming: false } : m
				)
			);
		}
		currentOracleMsgId = '';
		oracleChatStreaming.set(false);
	});

	oracleWs.on('error', () => {
		oracleAnalyzing.set(false);
		if (currentOracleMsgId) {
			oracleChatMessages.update((msgs) =>
				msgs.map((m) =>
					m.id === currentOracleMsgId ? { ...m, streaming: false } : m
				)
			);
			currentOracleMsgId = '';
			oracleChatStreaming.set(false);
		}
	});

	oracleWs.on('canvas_synced', () => {
		// Canvas state acknowledged by Oracle
	});

	oracleWs.connect();
}

export function disconnectOracle(): void {
	stopCanvasAutoSync();
	if (oracleWs) {
		oracleWs.disconnect();
		oracleWs = null;
	}
	oracleConnected.set(false);
	oracleAnalyzing.set(false);
	oracleInsights.set([]);
	oracleChatMessages.set([]);
	currentOracleMsgId = '';
	oracleChatStreaming.set(false);
}

/**
 * Build a context summary with project info and recent Architect
 * conversation so the Oracle understands what the user is building.
 */
function _buildContext(): Record<string, unknown> {
	const proj = get(currentProject);
	const msgs = get(chatMessages);

	// Take up to last 20 Architect messages for context
	const recent = msgs.slice(-20).map((m) => ({
		role: m.role,
		content: m.content.length > 500 ? m.content.slice(0, 500) + '...' : m.content,
	}));

	return {
		project_name: proj?.name ?? '',
		project_description: proj?.description ?? '',
		architect_history: recent,
	};
}

export function requestAnalysis(): void {
	if (oracleWs?.connected) {
		oracleAnalyzing.set(true);
		oracleWs.send({ action: 'analyze', context: _buildContext() });
	}
}

export function requestNodeAnalysis(nodeId: string): void {
	if (oracleWs?.connected) {
		oracleAnalyzing.set(true);
		oracleWs.send({ action: 'analyze_node', node_id: nodeId, context: _buildContext() });
	}
}

export function sendOracleChat(message: string): void {
	if (!oracleWs?.connected || !message.trim()) return;

	// Add user message to chat
	const userMsgId = `oracle_user_${++chatMsgCounter}`;
	oracleChatMessages.update((msgs) => [
		...msgs,
		{
			id: userMsgId,
			role: 'user',
			content: message.trim(),
			timestamp: new Date().toISOString(),
		},
	]);

	// Send to backend with context
	oracleWs.send({ action: 'chat', message: message.trim(), context: _buildContext() });
}

export function clearOracleChat(): void {
	oracleChatMessages.set([]);
	currentOracleMsgId = '';
	oracleChatStreaming.set(false);
}

export async function approveInsight(project: string, insightId: string): Promise<string | null> {
	const result = await api.oracle.approveInsight(project, insightId);
	oracleInsights.update((list) =>
		list.map((i) => (i.id === insightId ? { ...i, status: 'approved' as const } : i))
	);
	return result.action_instruction ?? null;
}

export async function skipInsight(project: string, insightId: string): Promise<void> {
	await api.oracle.skipInsight(project, insightId);
	oracleInsights.update((list) =>
		list.map((i) => (i.id === insightId ? { ...i, status: 'skipped' as const } : i))
	);
}

export async function loadInsights(project: string): Promise<void> {
	const insights = await api.oracle.getInsights(project);
	oracleInsights.set(insights);
}
