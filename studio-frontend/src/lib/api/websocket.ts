import type { ExecutionEvent } from '$lib/types/graph';

type EventCallback = (event: ExecutionEvent) => void;

export class StudioWebSocket {
	private ws: WebSocket | null = null;
	private listeners = new Map<string, Set<EventCallback>>();
	private url: string;
	private reconnectAttempts = 0;
	private maxReconnectAttempts = 5;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private _intentionalClose = false;

	constructor(path: string) {
		const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
		this.url = `${protocol}//${window.location.host}${path}`;
	}

	connect(): void {
		this._intentionalClose = false;
		this.ws = new WebSocket(this.url);

		this.ws.onopen = () => {
			this.reconnectAttempts = 0;
			this.notify('_open', { type: '_open', timestamp: '' } as ExecutionEvent);
		};

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
			this.notify('_close', { type: '_close', timestamp: '' } as ExecutionEvent);
			if (!this._intentionalClose) {
				this.attemptReconnect();
			}
		};

		this.ws.onerror = () => {
			this.notify('_error', { type: '_error', timestamp: '' } as ExecutionEvent);
		};
	}

	private attemptReconnect(): void {
		if (this.reconnectAttempts >= this.maxReconnectAttempts) {
			this.notify('_reconnect_failed', { type: '_reconnect_failed', timestamp: '' } as ExecutionEvent);
			return;
		}
		this.reconnectAttempts++;
		const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 10000);
		this.reconnectTimer = setTimeout(() => {
			this.connect();
		}, delay);
	}

	private notify(type: string, data: ExecutionEvent): void {
		const callbacks = this.listeners.get(type);
		if (callbacks) {
			for (const cb of callbacks) {
				try {
					cb(data);
				} catch (err) {
					console.error(`[StudioWebSocket] Listener error for '${type}':`, err);
				}
			}
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
		if (this.ws?.readyState === WebSocket.OPEN) {
			this.ws.send(JSON.stringify(data));
		} else {
			console.warn('[StudioWebSocket] Cannot send: WebSocket not open');
		}
	}

	get connected(): boolean {
		return this.ws?.readyState === WebSocket.OPEN;
	}

	disconnect(): void {
		this._intentionalClose = true;
		if (this.reconnectTimer) {
			clearTimeout(this.reconnectTimer);
			this.reconnectTimer = null;
		}
		this.ws?.close();
		this.ws = null;
	}
}
