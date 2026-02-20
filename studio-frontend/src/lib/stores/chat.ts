import { writable } from 'svelte/store';

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	timestamp: string;
	/** For assistant messages that are still streaming */
	streaming?: boolean;
	/** Tool calls made during this message */
	toolCalls?: ToolCallInfo[];
}

export interface ToolCallInfo {
	tool: string;
	args: Record<string, unknown>;
	result: string;
}

export const chatMessages = writable<ChatMessage[]>([]);
export const chatStreaming = writable<boolean>(false);

let messageCounter = 0;

export function addUserMessage(content: string): string {
	const id = `msg_${++messageCounter}`;
	chatMessages.update((msgs) => [
		...msgs,
		{
			id,
			role: 'user',
			content,
			timestamp: new Date().toISOString()
		}
	]);
	return id;
}

export function addAssistantMessage(): string {
	const id = `msg_${++messageCounter}`;
	chatMessages.update((msgs) => [
		...msgs,
		{
			id,
			role: 'assistant',
			content: '',
			timestamp: new Date().toISOString(),
			streaming: true,
			toolCalls: []
		}
	]);
	chatStreaming.set(true);
	return id;
}

export function appendToken(msgId: string, token: string): void {
	chatMessages.update((msgs) =>
		msgs.map((m) => (m.id === msgId ? { ...m, content: m.content + token } : m))
	);
}

export function completeMessage(msgId: string, fullText: string): void {
	chatMessages.update((msgs) =>
		msgs.map((m) => (m.id === msgId ? { ...m, content: fullText, streaming: false } : m))
	);
	chatStreaming.set(false);
}

export function addToolCall(msgId: string, toolCall: ToolCallInfo): void {
	chatMessages.update((msgs) =>
		msgs.map((m) =>
			m.id === msgId ? { ...m, toolCalls: [...(m.toolCalls || []), toolCall] } : m
		)
	);
}

export function clearChat(): void {
	chatMessages.set([]);
	chatStreaming.set(false);
}
