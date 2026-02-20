import type { ExecutionEvent } from '$lib/types/graph';

type EventCallback = (event: ExecutionEvent) => void;

export class StudioWebSocket {
	private ws: WebSocket | null = null;
	private listeners = new Map<string, Set<EventCallback>>();
	private url: string;

	constructor(path: string) {
		const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
		this.url = `${protocol}//${window.location.host}${path}`;
	}

	connect(): void {
		this.ws = new WebSocket(this.url);
		this.ws.onmessage = (event) => {
			try {
				const data = JSON.parse(event.data) as ExecutionEvent;
				this.notify(data.type, data);
				this.notify('*', data);
			} catch {
				console.warn('[StudioWebSocket] Unparseable frame:', event.data);
			}
		};
		this.ws.onclose = () => {
			this.notify('_close', { type: '_close' } as ExecutionEvent);
		};
		this.ws.onerror = () => {
			this.notify('_error', { type: '_error' } as ExecutionEvent);
		};
	}

	private notify(type: string, data: ExecutionEvent): void {
		const callbacks = this.listeners.get(type);
		if (callbacks) {
			for (const cb of callbacks) cb(data);
		}
	}

	on(eventType: string, callback: EventCallback): () => void {
		if (!this.listeners.has(eventType)) {
			this.listeners.set(eventType, new Set());
		}
		this.listeners.get(eventType)!.add(callback);
		return () => this.listeners.get(eventType)?.delete(callback);
	}

	send(data: unknown): void {
		this.ws?.send(JSON.stringify(data));
	}

	disconnect(): void {
		this.ws?.close();
		this.ws = null;
	}
}
