import { writable, derived } from 'svelte/store';

export type AgentTab = 'architect' | 'smith' | 'oracle';
export type BottomPanelTab = 'console' | 'timeline' | 'executions' | 'oracle' | 'history';
export type AppView = 'home' | 'construct';

// Persist activeAgentTab to localStorage
function createPersistedAgentTab() {
	const stored = typeof localStorage !== 'undefined' ? localStorage.getItem('firefly:activeAgentTab') as AgentTab | null : null;
	const store = writable<AgentTab>(stored || 'architect');
	store.subscribe(val => {
		if (typeof localStorage !== 'undefined') {
			localStorage.setItem('firefly:activeAgentTab', val);
		}
	});
	return store;
}

export const activeAgentTab = createPersistedAgentTab();
export const agentSidebarOpen = writable(true);
// Backward compat alias — TopBar, AppShell, shortcuts reference this
export const architectSidebarOpen = agentSidebarOpen;

export const rightPanelOpen = writable(true);
export const bottomPanelOpen = writable(false);
export const bottomPanelTab = writable<BottomPanelTab>('console');
export const appView = writable<AppView>('home');
export const commandPaletteOpen = writable(false);
export const shortcutsModalOpen = writable(false);
export const settingsModalOpen = writable(false);
export const firstStartWizardOpen = writable(false);
export const projectSettingsModalOpen = writable(false);

/**
 * Pending message from the home page prompt to be sent to The Architect
 * when the sidebar connects. Consumed once by ArchitectSidebar.
 */
export interface PendingArchitectMessage {
	text: string;
	attachments?: { name: string; size: number; category: string; data: string; type: string; docType: string }[];
}
export const pendingArchitectMessage = writable<PendingArchitectMessage | null>(null);
