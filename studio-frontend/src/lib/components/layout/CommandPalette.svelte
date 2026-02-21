<script lang="ts">
	import { goto } from '$app/navigation';
	import { commandPaletteOpen, bottomPanelOpen, bottomPanelTab, rightPanelOpen, settingsModalOpen, architectSidebarOpen, shortcutsModalOpen } from '$lib/stores/ui';
	import { addNode, getGraphSnapshot } from '$lib/stores/pipeline';
	import { runPipeline, debugPipeline } from '$lib/execution/bridge';
	import { projects, currentProject, selectProject, createAndSelectProject } from '$lib/stores/project';
	import { cycleTheme } from '$lib/stores/theme';
	import { generateCode } from '$lib/stores/smith';
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	type IconComponent = any;

	// Navigation icons
	import LayoutDashboard from 'lucide-svelte/icons/layout-dashboard';
	import Blocks from 'lucide-svelte/icons/blocks';
	import FlaskConical from 'lucide-svelte/icons/flask-conical';
	import GitBranch from 'lucide-svelte/icons/git-branch';
	import Rocket from 'lucide-svelte/icons/rocket';
	import Activity from 'lucide-svelte/icons/activity';
	import FolderOpen from 'lucide-svelte/icons/folder-open';
	import Plug from 'lucide-svelte/icons/plug';

	// Node icons
	import Bot from 'lucide-svelte/icons/bot';
	import Wrench from 'lucide-svelte/icons/wrench';
	import Brain from 'lucide-svelte/icons/brain';
	import CircleDot from 'lucide-svelte/icons/circle-dot';
	import Database from 'lucide-svelte/icons/database';
	import Shield from 'lucide-svelte/icons/shield';
	import Code from 'lucide-svelte/icons/code';
	import GitFork from 'lucide-svelte/icons/git-fork';
	import GitMerge from 'lucide-svelte/icons/git-merge';
	import Antenna from 'lucide-svelte/icons/antenna';
	import Download from 'lucide-svelte/icons/download';

	// Action icons
	import Play from 'lucide-svelte/icons/play';
	import Bug from 'lucide-svelte/icons/bug';
	import PanelBottom from 'lucide-svelte/icons/panel-bottom';
	import PanelRight from 'lucide-svelte/icons/panel-right';
	import Terminal from 'lucide-svelte/icons/terminal';
	import CodeXml from 'lucide-svelte/icons/code-xml';
	import Clock from 'lucide-svelte/icons/clock';
	import MessageSquare from 'lucide-svelte/icons/message-square';
	import Search from 'lucide-svelte/icons/search';
	import SettingsIcon from 'lucide-svelte/icons/settings';
	import SunMoon from 'lucide-svelte/icons/sun-moon';
	import Plus from 'lucide-svelte/icons/plus';
	import FolderKanban from 'lucide-svelte/icons/folder-kanban';
	import Eye from 'lucide-svelte/icons/eye';
	import History from 'lucide-svelte/icons/history';
	import ListChecks from 'lucide-svelte/icons/list-checks';
	import Keyboard from 'lucide-svelte/icons/keyboard';
	import FileCode from 'lucide-svelte/icons/file-code';

	interface Command {
		id: string;
		label: string;
		category: string;
		icon: IconComponent;
		action: () => void;
		shortcut?: string;
		keywords?: string;
	}

	const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent);
	const mod = isMac ? '\u2318' : 'Ctrl';

	const staticCommands: Command[] = [
		// Navigation
		{ id: 'nav-home', label: 'Go to Home', category: 'Navigation', icon: LayoutDashboard, action: () => goto('/'), keywords: 'dashboard overview' },
		{ id: 'nav-construct', label: 'Go to Construct', category: 'Navigation', icon: Blocks, action: () => goto('/construct'), keywords: 'canvas build design pipeline' },
		{ id: 'nav-integrations', label: 'Go to Integrations', category: 'Navigation', icon: Plug, action: () => goto('/integrations'), keywords: 'connect tools custom webhook api' },
		{ id: 'nav-evaluate', label: 'Go to Evaluate', category: 'Navigation', icon: FlaskConical, action: () => goto('/evaluate'), keywords: 'test benchmark' },
		{ id: 'nav-experiments', label: 'Go to Experiments', category: 'Navigation', icon: GitBranch, action: () => goto('/experiments'), keywords: 'ab test compare variants' },
		{ id: 'nav-deploy', label: 'Go to Deploy', category: 'Navigation', icon: Rocket, action: () => goto('/deploy'), keywords: 'publish launch ship' },
		{ id: 'nav-monitor', label: 'Go to Monitor', category: 'Navigation', icon: Activity, action: () => goto('/monitor'), keywords: 'metrics logs performance' },
		{ id: 'nav-files', label: 'Go to Files', category: 'Navigation', icon: FolderOpen, action: () => goto('/files'), keywords: 'browse documents' },

		// Pipeline Actions
		{ id: 'pipeline-run', label: 'Run Pipeline', category: 'Pipeline', icon: Play, action: () => runPipeline(getGraphSnapshot()), shortcut: `${mod}+\u23CE`, keywords: 'execute start' },
		{ id: 'pipeline-debug', label: 'Debug Pipeline', category: 'Pipeline', icon: Bug, action: () => debugPipeline(getGraphSnapshot()), shortcut: `${mod}+\u21E7+D`, keywords: 'step breakpoint inspect' },
		{ id: 'pipeline-codegen', label: 'Generate Code', category: 'Pipeline', icon: FileCode, action: () => { bottomPanelOpen.set(true); bottomPanelTab.set('code'); queueMicrotask(() => generateCode(getGraphSnapshot())); }, keywords: 'smith code export python' },

		// Add Node
		{ id: 'node-input', label: 'Add Input Node', category: 'Add Node', icon: Antenna, action: () => addNode('input', 'Input') },
		{ id: 'node-output', label: 'Add Output Node', category: 'Add Node', icon: Download, action: () => addNode('output', 'Output') },
		{ id: 'node-agent', label: 'Add Agent Node', category: 'Add Node', icon: Bot, action: () => addNode('agent', 'Agent'), keywords: 'llm model ai' },
		{ id: 'node-tool', label: 'Add Tool Node', category: 'Add Node', icon: Wrench, action: () => addNode('tool', 'Tool'), keywords: 'function utility' },
		{ id: 'node-reasoning', label: 'Add Reasoning Node', category: 'Add Node', icon: Brain, action: () => addNode('reasoning', 'Reasoning'), keywords: 'react cot chain thought' },
		{ id: 'node-condition', label: 'Add Condition Node', category: 'Add Node', icon: CircleDot, action: () => addNode('condition', 'Condition'), keywords: 'branch if else switch' },
		{ id: 'node-memory', label: 'Add Memory Node', category: 'Add Node', icon: Database, action: () => addNode('memory', 'Memory'), keywords: 'store retrieve context' },
		{ id: 'node-validator', label: 'Add Validator Node', category: 'Add Node', icon: Shield, action: () => addNode('validator', 'Validator'), keywords: 'check validate guard' },
		{ id: 'node-code', label: 'Add Code Node', category: 'Add Node', icon: Code, action: () => addNode('custom_code', 'Code'), keywords: 'python custom script' },
		{ id: 'node-fanout', label: 'Add Fan Out Node', category: 'Add Node', icon: GitFork, action: () => addNode('fan_out', 'Fan Out'), keywords: 'parallel split' },
		{ id: 'node-fanin', label: 'Add Fan In Node', category: 'Add Node', icon: GitMerge, action: () => addNode('fan_in', 'Fan In'), keywords: 'merge join collect' },

		// View / Panels
		{ id: 'view-architect', label: 'Toggle Architect Sidebar', category: 'View', icon: MessageSquare, action: () => architectSidebarOpen.update((v) => !v), shortcut: `${mod}+/`, keywords: 'ai assistant chat architect' },
		{ id: 'view-bottom-panel', label: 'Toggle Bottom Panel', category: 'View', icon: PanelBottom, action: () => bottomPanelOpen.update((v) => !v) },
		{ id: 'view-right-panel', label: 'Toggle Right Panel', category: 'View', icon: PanelRight, action: () => rightPanelOpen.update((v) => !v) },
		{ id: 'view-tab-console', label: 'Open Console Tab', category: 'View', icon: Terminal, action: () => { bottomPanelOpen.set(true); bottomPanelTab.set('console'); }, keywords: 'log output events' },
		{ id: 'view-tab-code', label: 'Open Code Tab', category: 'View', icon: CodeXml, action: () => { bottomPanelOpen.set(true); bottomPanelTab.set('code'); }, keywords: 'smith codegen' },
		{ id: 'view-tab-timeline', label: 'Open Timeline Tab', category: 'View', icon: Clock, action: () => { bottomPanelOpen.set(true); bottomPanelTab.set('timeline'); }, keywords: 'checkpoints' },
		{ id: 'view-tab-oracle', label: 'Open Oracle Tab', category: 'View', icon: Eye, action: () => { bottomPanelOpen.set(true); bottomPanelTab.set('oracle'); }, keywords: 'insights analysis suggestions' },
		{ id: 'view-tab-history', label: 'Open History Tab', category: 'View', icon: History, action: () => { bottomPanelOpen.set(true); bottomPanelTab.set('history'); }, keywords: 'past runs versions' },
		{ id: 'view-tab-executions', label: 'Open Executions Tab', category: 'View', icon: ListChecks, action: () => { bottomPanelOpen.set(true); bottomPanelTab.set('executions'); }, keywords: 'runs results' },
		{ id: 'view-tab-integrations', label: 'Open Integrations Tab', category: 'View', icon: Plug, action: () => { bottomPanelOpen.set(true); bottomPanelTab.set('integrations'); }, keywords: 'connect tools' },

		// Settings & Preferences
		{ id: 'open-settings', label: 'Open Settings', category: 'Settings', icon: SettingsIcon, action: () => settingsModalOpen.set(true), shortcut: `${mod}+,`, keywords: 'preferences config api keys' },
		{ id: 'toggle-theme', label: 'Cycle Theme (Dark / Light / System)', category: 'Settings', icon: SunMoon, action: () => cycleTheme(), keywords: 'dark light mode appearance' },
		{ id: 'open-shortcuts', label: 'Keyboard Shortcuts', category: 'Settings', icon: Keyboard, action: () => shortcutsModalOpen.set(true), shortcut: '?', keywords: 'help hotkeys keys bindings' },

		// Project (create new — dynamic project switch items are appended below)
		{ id: 'project-new', label: 'New Project', category: 'Project', icon: Plus, action: () => promptNewProject(), keywords: 'create project' },
	];

	function promptNewProject() {
		const name = window.prompt('Project name:');
		if (name?.trim()) {
			createAndSelectProject(name.trim()).then(() => goto('/construct')).catch(() => {});
		}
	}

	// Build the full commands list including dynamic project-switch entries
	let commands = $derived.by(() => {
		const projectList = $projects;
		const current = $currentProject;
		const projectCommands: Command[] = projectList
			.filter((p) => p.name !== current?.name)
			.map((p) => ({
				id: `project-switch-${p.name}`,
				label: `Switch to "${p.name}"`,
				category: 'Project',
				icon: FolderKanban,
				action: () => { selectProject(p); goto('/construct'); },
				keywords: 'project switch',
			}));
		return [...staticCommands, ...projectCommands];
	});

	let query = $state('');
	let selectedIndex = $state(0);
	let inputRef = $state<HTMLInputElement | null>(null);

	function fuzzyScore(text: string, pattern: string): number {
		let pi = 0;
		let gaps = 0;
		let lastMatch = -1;
		for (let ti = 0; ti < text.length && pi < pattern.length; ti++) {
			if (text[ti] === pattern[pi]) {
				if (lastMatch >= 0) gaps += ti - lastMatch - 1;
				lastMatch = ti;
				pi++;
			}
		}
		return pi === pattern.length ? gaps : -1;
	}

	let filtered = $derived.by(() => {
		if (!query.trim()) return commands;
		const q = query.toLowerCase();
		const scored = commands
			.map((cmd) => {
				const labelScore = fuzzyScore(cmd.label.toLowerCase(), q);
				const catScore = fuzzyScore(cmd.category.toLowerCase(), q);
				const kwScore = cmd.keywords ? fuzzyScore(cmd.keywords.toLowerCase(), q) : -1;
				// Pick the best (lowest non-negative) score
				const scores = [labelScore, catScore, kwScore].filter((s) => s >= 0);
				const best = scores.length > 0 ? Math.min(...scores) : -1;
				return { cmd, score: best };
			})
			.filter((s) => s.score >= 0);
		scored.sort((a, b) => a.score - b.score);
		return scored.map((s) => s.cmd);
	});

	// Group filtered commands by category, preserving order
	let grouped = $derived.by(() => {
		const groups: { category: string; items: (Command & { globalIndex: number })[] }[] = [];
		let globalIndex = 0;
		const categoryMap = new Map<string, (Command & { globalIndex: number })[]>();
		const categoryOrder: string[] = [];

		for (const cmd of filtered) {
			if (!categoryMap.has(cmd.category)) {
				categoryMap.set(cmd.category, []);
				categoryOrder.push(cmd.category);
			}
			categoryMap.get(cmd.category)!.push({ ...cmd, globalIndex });
			globalIndex++;
		}

		for (const cat of categoryOrder) {
			groups.push({ category: cat, items: categoryMap.get(cat)! });
		}

		return groups;
	});

	// Clamp selected index when filtered list changes
	$effect(() => {
		if (selectedIndex >= filtered.length) {
			selectedIndex = Math.max(0, filtered.length - 1);
		}
	});

	// Reset state and focus input when opened
	$effect(() => {
		if ($commandPaletteOpen) {
			query = '';
			selectedIndex = 0;
			queueMicrotask(() => inputRef?.focus());
		}
	});

	function close() {
		commandPaletteOpen.set(false);
	}

	function execute(cmd: Command) {
		close();
		// Defer execution to after the palette closes
		queueMicrotask(() => cmd.action());
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			close();
			return;
		}

		if (e.key === 'ArrowDown') {
			e.preventDefault();
			selectedIndex = (selectedIndex + 1) % filtered.length;
			scrollSelectedIntoView();
			return;
		}

		if (e.key === 'ArrowUp') {
			e.preventDefault();
			selectedIndex = (selectedIndex - 1 + filtered.length) % filtered.length;
			scrollSelectedIntoView();
			return;
		}

		if (e.key === 'Enter') {
			e.preventDefault();
			const cmd = filtered[selectedIndex];
			if (cmd) execute(cmd);
			return;
		}
	}

	function scrollSelectedIntoView() {
		queueMicrotask(() => {
			const cmd = filtered[selectedIndex];
			if (cmd) {
				const el = document.getElementById(`cmd-item-${cmd.id}`);
				el?.scrollIntoView({ block: 'nearest' });
			}
		});
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) {
			close();
		}
	}
</script>

{#if $commandPaletteOpen}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="command-palette-backdrop" onclick={handleBackdropClick}>
		<div class="command-palette" role="dialog" aria-modal="true" aria-label="Command palette">
			<div class="command-palette-input-wrapper">
				<Search size={16} />
				<input
					bind:this={inputRef}
					bind:value={query}
					onkeydown={handleKeydown}
					type="text"
					class="command-palette-input"
					placeholder="Type a command..."
					spellcheck="false"
					autocomplete="off"
					role="combobox"
					aria-expanded="true"
					aria-controls="command-palette-results"
					aria-activedescendant={filtered.length > 0 ? `cmd-item-${filtered[selectedIndex]?.id}` : undefined}
				/>
				<kbd class="command-palette-kbd">ESC</kbd>
			</div>

			<div id="command-palette-results" class="command-palette-results" role="listbox">
				{#if filtered.length === 0}
					<div class="command-palette-empty">No matching commands</div>
				{:else}
					{#each grouped as group}
						<div class="command-palette-category">{group.category}</div>
						{#each group.items as item}
							<button
								id="cmd-item-{item.id}"
								class="command-palette-item"
								class:selected={item.globalIndex === selectedIndex}
								role="option"
								aria-selected={item.globalIndex === selectedIndex}
								onclick={() => execute(item)}
								onmouseenter={() => { selectedIndex = item.globalIndex; }}
							>
								<span class="command-palette-item-icon">
									<item.icon size={16} />
								</span>
								<span class="command-palette-item-label">{item.label}</span>
								{#if item.shortcut}
									<kbd class="command-palette-item-shortcut">{item.shortcut}</kbd>
								{/if}
							</button>
						{/each}
					{/each}
				{/if}
			</div>

			<div class="command-palette-footer">
				<span class="command-palette-hint">
					<kbd>↑↓</kbd> navigate
				</span>
				<span class="command-palette-hint">
					<kbd>↵</kbd> select
				</span>
				<span class="command-palette-hint">
					<kbd>esc</kbd> close
				</span>
			</div>
		</div>
	</div>
{/if}

<style>
	.command-palette-backdrop {
		position: fixed;
		inset: 0;
		z-index: 9999;
		background: rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding-top: 15vh;
		animation: backdrop-fade-in 0.12s ease-out;
	}

	@keyframes backdrop-fade-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	.command-palette {
		width: 560px;
		max-width: 90vw;
		max-height: 480px;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		box-shadow:
			0 0 0 1px var(--color-overlay-subtle),
			var(--shadow-lg),
			0 0 80px color-mix(in srgb, var(--color-accent) 4%, transparent);
		animation: palette-slide-in 0.15s ease-out;
	}

	@keyframes palette-slide-in {
		from {
			opacity: 0;
			transform: translateY(-8px) scale(0.98);
		}
		to {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}

	.command-palette-input-wrapper {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 14px 16px;
		border-bottom: 1px solid var(--color-border);
		color: var(--color-text-secondary);
	}

	.command-palette-input {
		flex: 1;
		background: transparent;
		border: none;
		outline: none;
		color: var(--color-text-primary);
		font-family: var(--font-sans);
		font-size: 15px;
		line-height: 1;
		caret-color: var(--color-accent);
	}

	.command-palette-input::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.6;
	}

	.command-palette-kbd {
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 500;
		color: var(--color-text-secondary);
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 4px;
		padding: 2px 6px;
		line-height: 1.4;
	}

	.command-palette-results {
		flex: 1;
		overflow-y: auto;
		padding: 6px;
	}

	.command-palette-empty {
		padding: 32px 16px;
		text-align: center;
		color: var(--color-text-secondary);
		font-size: 13px;
		font-family: var(--font-sans);
	}

	.command-palette-category {
		font-family: var(--font-sans);
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-text-secondary);
		padding: 10px 10px 4px;
		user-select: none;
	}

	.command-palette-item {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		padding: 8px 10px;
		background: transparent;
		border: none;
		border-radius: 8px;
		cursor: pointer;
		transition: background 0.08s ease;
		text-align: left;
		color: inherit;
	}

	.command-palette-item:hover,
	.command-palette-item.selected {
		background: var(--color-bg-elevated);
	}

	.command-palette-item.selected {
		outline: 1px solid var(--color-border-light, var(--color-border));
	}

	.command-palette-item-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border-radius: 6px;
		background: var(--color-overlay-subtle);
		color: var(--color-text-secondary);
		flex-shrink: 0;
	}

	.command-palette-item.selected .command-palette-item-icon {
		color: var(--color-accent);
		background: color-mix(in srgb, var(--color-accent) 10%, transparent);
	}

	.command-palette-item-label {
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 500;
		color: var(--color-text-primary);
		flex: 1;
	}

	.command-palette-item-shortcut {
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--color-text-secondary);
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 4px;
		padding: 2px 6px;
		line-height: 1.4;
	}

	.command-palette-footer {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 10px 16px;
		border-top: 1px solid var(--color-border);
	}

	.command-palette-hint {
		display: flex;
		align-items: center;
		gap: 4px;
		font-family: var(--font-sans);
		font-size: 11px;
		color: var(--color-text-secondary);
		opacity: 0.7;
	}

	.command-palette-hint kbd {
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--color-text-secondary);
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 3px;
		padding: 1px 4px;
		line-height: 1.4;
	}
</style>
