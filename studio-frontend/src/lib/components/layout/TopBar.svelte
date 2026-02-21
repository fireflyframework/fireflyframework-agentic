<script lang="ts">
	import Play from 'lucide-svelte/icons/play';
	import Bug from 'lucide-svelte/icons/bug';
	import Settings from 'lucide-svelte/icons/settings';
	import PanelLeft from 'lucide-svelte/icons/panel-left';
	import Loader from 'lucide-svelte/icons/loader';
	import Plus from 'lucide-svelte/icons/plus';
	import Save from 'lucide-svelte/icons/save';
	import ChevronDown from 'lucide-svelte/icons/chevron-down';
	import Trash2 from 'lucide-svelte/icons/trash-2';
	import LinkIcon from 'lucide-svelte/icons/link';
	import Power from 'lucide-svelte/icons/power';
	import { isRunning, isDebugging } from '$lib/stores/execution';
	import { runtimeStatus } from '$lib/stores/runtime';
	import { runPipeline, debugPipeline } from '$lib/execution/bridge';
	import { getGraphSnapshot, nodes as nodesStore } from '$lib/stores/pipeline';
	import { settingsModalOpen, architectSidebarOpen } from '$lib/stores/ui';
	import { connectionState } from '$lib/stores/connection';
	import { currentProject, projects, selectProject, initProjects } from '$lib/stores/project';
	import { api } from '$lib/api/client';
	import { get } from 'svelte/store';
	import { afterNavigate } from '$app/navigation';
	import { addToast } from '$lib/stores/notifications';
	import logo from '$lib/assets/favicon.svg';
	import ShareModal from './ShareModal.svelte';

	let { isHomePage = false }: { isHomePage?: boolean } = $props();

	let running = $derived($isRunning);
	let debugging = $derived($isDebugging);
	let busy = $derived(running || debugging);
	let connState = $derived($connectionState);

	// Project dropdown
	let projectDropdownOpen = $state(false);
	let newProjectName = $state('');
	let creatingProject = $state(false);
	let confirmDeleteProject = $state<string | null>(null);

	// Share modal
	let shareModalOpen = $state(false);

	// Run input dialog
	let showRunDialog = $state(false);
	let runInput = $state('');

	// Close overlays on navigation to prevent stale backdrops
	afterNavigate(() => {
		projectDropdownOpen = false;
		showRunDialog = false;
		shareModalOpen = false;
		confirmDeleteProject = null;
	});

	function toggleProjectDropdown() {
		projectDropdownOpen = !projectDropdownOpen;
		newProjectName = '';
	}

	async function createProject() {
		const name = newProjectName.trim();
		if (!name || creatingProject) return;
		creatingProject = true;
		try {
			await api.projects.create(name);
			await initProjects();
			const list = get(projects);
			const created = list.find((p) => p.name === name);
			if (created) selectProject(created);
			newProjectName = '';
			projectDropdownOpen = false;
		} catch {
			addToast('Failed to create project', 'error');
		} finally {
			creatingProject = false;
		}
	}

	async function switchProject(project: typeof $currentProject) {
		if (!project) return;
		selectProject(project);
		projectDropdownOpen = false;
	}

	function requestDeleteProject(projectName: string) {
		if (get(projects).length <= 1) {
			addToast('Cannot delete the only project', 'error');
			return;
		}
		confirmDeleteProject = projectName;
	}

	async function confirmAndDeleteProject() {
		if (!confirmDeleteProject) return;
		const name = confirmDeleteProject;
		confirmDeleteProject = null;
		try {
			await api.projects.delete(name);
			await initProjects();
			addToast(`Project "${name}" deleted`, 'success');
		} catch {
			addToast('Failed to delete project', 'error');
		}
	}

	function cancelDeleteProject() {
		confirmDeleteProject = null;
	}

	async function savePipeline() {
		const proj = get(currentProject);
		if (!proj) return;
		try {
			const graph = getGraphSnapshot();
			await api.projects.savePipeline(proj.name, 'main', graph);
			addToast('Pipeline saved', 'success');
		} catch {
			addToast('Failed to save pipeline', 'error');
		}
	}

	function handleRun() {
		const currentNodes = get(nodesStore);
		if (currentNodes.length === 0) return;
		showRunDialog = true;
		runInput = '';
	}

	function executeRun() {
		showRunDialog = false;
		runPipeline(getGraphSnapshot(), runInput || undefined);
	}

	function handleDebug() {
		debugPipeline(getGraphSnapshot());
	}

	function toggleArchitect() {
		architectSidebarOpen.update((v) => !v);
	}

	// Runtime controls
	let rtStatus = $derived($runtimeStatus);
	let runtimeToggling = $state(false);

	async function toggleRuntime() {
		const proj = get(currentProject);
		if (!proj || runtimeToggling) return;
		runtimeToggling = true;
		try {
			if (rtStatus === 'running') {
				runtimeStatus.set('stopped');
				await api.runtime.stop(proj.name);
				runtimeStatus.set('stopped');
				addToast('Runtime stopped', 'success');
			} else {
				runtimeStatus.set('starting');
				await api.runtime.start(proj.name);
				runtimeStatus.set('running');
				addToast('Runtime started', 'success');
			}
		} catch {
			runtimeStatus.set('error');
			addToast('Runtime toggle failed', 'error');
		} finally {
			runtimeToggling = false;
		}
	}
</script>

<header class="top-bar">
	<div class="top-bar-left">
		<a href="/" class="brand-link" title="Home">
			<img src={logo} alt="Firefly Agentic Studio" class="brand-logo" />
			<span class="brand">Firefly Agentic Studio</span>
		</a>
		{#if !isHomePage}
			<span
				class="conn-dot"
				class:conn-ok={connState === 'connected'}
				class:conn-fail={connState === 'disconnected'}
				class:conn-check={connState === 'checking'}
				title={connState === 'connected' ? 'Backend connected' : connState === 'disconnected' ? 'Backend disconnected' : 'Checking connection...'}
			></span>
			<span class="separator">/</span>
			<div class="project-container">
				<button class="project-selector" onclick={toggleProjectDropdown}>
					<span class="project-dot"></span>
					<span class="project-name">{$currentProject?.name ?? 'No project'}</span>
					<ChevronDown size={10} class="project-chevron" />
				</button>
				{#if projectDropdownOpen}
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div class="project-backdrop" onclick={() => { projectDropdownOpen = false; confirmDeleteProject = null; }} onkeydown={() => {}}></div>
					<div class="project-dropdown">
						<div class="dropdown-header">
							<span>Projects</span>
							<span class="dropdown-count">{$projects.length}</span>
						</div>
						{#if confirmDeleteProject}
							<div class="dropdown-confirm-delete">
								<p class="confirm-delete-msg">Delete <strong>{confirmDeleteProject}</strong>?</p>
								<p class="confirm-delete-warn">This action cannot be undone.</p>
								<div class="confirm-delete-actions">
									<button class="confirm-cancel-btn" onclick={cancelDeleteProject}>Cancel</button>
									<button class="confirm-delete-btn" onclick={confirmAndDeleteProject}>Delete</button>
								</div>
							</div>
						{:else}
						<div class="dropdown-items">
							{#each $projects as project}
								<!-- svelte-ignore a11y_no_static_element_interactions -->
								<div
									class="dropdown-item"
									class:active={$currentProject?.name === project.name}
									onclick={() => switchProject(project)}
								>
									<span class="dropdown-item-dot" class:dot-active={$currentProject?.name === project.name}></span>
									<span class="dropdown-item-name">{project.name}</span>
									{#if $currentProject?.name === project.name}
										<span class="dropdown-active-label">active</span>
									{/if}
									{#if $projects.length > 1}
										<button
											class="dropdown-item-delete"
											onclick={(e) => { e.stopPropagation(); requestDeleteProject(project.name); }}
											title="Delete project"
										>
											<Trash2 size={12} />
										</button>
									{/if}
								</div>
							{/each}
						</div>
						<div class="dropdown-create">
							<input
								class="dropdown-input"
								type="text"
								placeholder="New project name..."
								bind:value={newProjectName}
								onkeydown={(e) => e.key === 'Enter' && createProject()}
							/>
							<button class="dropdown-create-btn" disabled={!newProjectName.trim() || creatingProject} onclick={createProject}>
								<Plus size={14} />
							</button>
						</div>
						{/if}
					</div>
				{/if}
			</div>
			<button class="btn-save" onclick={savePipeline} title="Save pipeline (Cmd+S)">
				<Save size={14} />
			</button>
		{/if}
	</div>

	<div class="top-bar-spacer"></div>

	<div class="top-bar-right">
		{#if !isHomePage}
			<button class="btn-run" class:btn-run-active={running} disabled={busy} onclick={handleRun} title="Run">
				{#if running}
					<span class="spin-icon"><Loader size={14} /></span>
					<span>Running...</span>
					<span class="pulse-dot"></span>
				{:else}
					<Play size={14} />
					<span>Run</span>
				{/if}
			</button>
			<button class="btn-icon" class:btn-debug-active={debugging} disabled={busy} onclick={handleDebug} title="Debug">
				<Bug size={16} />
				{#if debugging}
					<span class="pulse-dot debug-dot"></span>
				{/if}
			</button>
			<button
				class="btn-runtime"
				class:runtime-running={rtStatus === 'running'}
				class:runtime-error={rtStatus === 'error'}
				class:runtime-starting={rtStatus === 'starting'}
				disabled={runtimeToggling}
				onclick={toggleRuntime}
				title={rtStatus === 'running' ? 'Stop runtime' : 'Start runtime'}
			>
				<span
					class="runtime-dot"
					class:rt-running={rtStatus === 'running'}
					class:rt-stopped={rtStatus === 'stopped'}
					class:rt-error={rtStatus === 'error'}
					class:rt-starting={rtStatus === 'starting'}
				></span>
				<Power size={13} />
			</button>
			<div class="divider"></div>
		{/if}
		{#if !isHomePage}
			<button class="btn-icon" title="Share" onclick={() => shareModalOpen = true}>
				<LinkIcon size={16} />
			</button>
		{/if}
		<button class="btn-icon" title="Settings" onclick={() => settingsModalOpen.set(true)}>
			<Settings size={16} />
		</button>
		{#if !isHomePage}
			<button class="btn-icon" class:architect-active={$architectSidebarOpen} title="Architect (Cmd+/)" onclick={toggleArchitect}>
				<PanelLeft size={16} />
			</button>
		{/if}
	</div>
</header>

<ShareModal open={shareModalOpen} onclose={() => shareModalOpen = false} />

<!-- Run Input Dialog -->
{#if showRunDialog}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="run-dialog-backdrop" onclick={() => showRunDialog = false} onkeydown={(e) => e.key === 'Escape' && (showRunDialog = false)}>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="run-dialog" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
			<h3 class="run-dialog-title">Run Pipeline</h3>
			<p class="run-dialog-hint">Provide input for your pipeline (or leave blank to run without input)</p>
			<textarea
				class="run-dialog-input"
				placeholder="Enter your question or input..."
				bind:value={runInput}
				rows={4}
				onkeydown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) executeRun(); }}
			></textarea>
			<div class="run-dialog-actions">
				<button class="run-dialog-cancel" onclick={() => showRunDialog = false}>Cancel</button>
				<button class="run-dialog-go" onclick={executeRun}>
					<Play size={14} />
					Run
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.top-bar {
		height: 48px;
		min-height: 48px;
		display: flex;
		align-items: center;
		padding: 0 12px;
		background: var(--color-bg-secondary);
		border-bottom: 1px solid var(--color-border);
		user-select: none;
		gap: 8px;
	}

	.top-bar-left {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
	}

	.brand-link {
		display: flex;
		align-items: center;
		gap: 8px;
		text-decoration: none;
		border-radius: 6px;
		padding: 4px 6px;
		margin: -4px -6px;
		transition: background 0.15s;
	}

	.brand-link:hover {
		background: var(--color-bg-elevated);
	}

	.brand-logo {
		width: 24px;
		height: 24px;
		border-radius: 5px;
	}

	.brand {
		font-family: var(--font-sans);
		font-size: 14px;
		font-weight: 600;
		color: var(--color-accent);
		letter-spacing: -0.01em;
	}

	.conn-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--color-text-secondary);
		flex-shrink: 0;
		transition: background 0.3s;
	}

	.conn-dot.conn-ok {
		background: var(--color-success, #22c55e);
		box-shadow: 0 0 6px oklch(from var(--color-success, #22c55e) l c h / 50%);
	}

	.conn-dot.conn-fail {
		background: var(--color-error, #ef4444);
		box-shadow: 0 0 6px oklch(from var(--color-error, #ef4444) l c h / 50%);
	}

	.conn-dot.conn-check {
		animation: conn-pulse 1s ease-in-out infinite;
	}

	@keyframes conn-pulse {
		0%, 100% { opacity: 0.3; }
		50% { opacity: 1; }
	}

	.separator {
		color: var(--color-text-secondary);
		font-size: 14px;
		opacity: 0.5;
	}

	/* Project dropdown */
	.project-container {
		position: relative;
	}

	.project-selector {
		display: flex;
		align-items: center;
		gap: 6px;
		background: transparent;
		border: 1px solid transparent;
		color: var(--color-text-primary);
		font-family: var(--font-mono);
		font-size: 13px;
		padding: 4px 10px 4px 8px;
		border-radius: 6px;
		cursor: pointer;
		transition: background 0.15s, border-color 0.15s;
	}

	.project-selector:hover {
		background: var(--color-bg-elevated);
		border-color: var(--color-border);
	}

	.project-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--color-accent);
		flex-shrink: 0;
	}

	.project-name {
		font-weight: 500;
	}

	:global(.project-chevron) {
		color: var(--color-text-secondary);
		opacity: 0.6;
		flex-shrink: 0;
	}

	.project-backdrop {
		position: fixed;
		inset: 0;
		z-index: 999;
	}

	.project-dropdown {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		width: 260px;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
		z-index: 1000;
		overflow: hidden;
		animation: dropdown-in 0.15s ease;
	}

	@keyframes dropdown-in {
		from { opacity: 0; transform: translateY(-4px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.dropdown-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary);
		padding: 10px 12px 6px;
	}

	.dropdown-count {
		font-size: 9px;
		font-weight: 600;
		min-width: 16px;
		height: 16px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 8px;
		background: var(--color-bg-elevated);
		color: var(--color-text-secondary);
	}

	.dropdown-items {
		max-height: 240px;
		overflow-y: auto;
		padding: 2px 4px;
		scrollbar-width: thin;
		scrollbar-color: var(--color-border) transparent;
	}

	.dropdown-item {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 8px 10px;
		background: none;
		border: none;
		border-radius: 6px;
		color: var(--color-text-primary);
		font-family: var(--font-mono);
		font-size: 12px;
		cursor: pointer;
		text-align: left;
		transition: background 0.1s;
	}

	.dropdown-item:hover {
		background: var(--color-bg-elevated);
	}

	.dropdown-item.active {
		color: var(--color-accent);
		background: oklch(from var(--color-accent) l c h / 8%);
	}

	.dropdown-item-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--color-border);
		flex-shrink: 0;
		transition: background 0.15s;
	}

	.dropdown-item-dot.dot-active {
		background: var(--color-accent);
		box-shadow: 0 0 6px oklch(from var(--color-accent) l c h / 40%);
	}

	.dropdown-item-name {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.dropdown-item-delete {
		display: flex;
		align-items: center;
		background: none;
		border: none;
		color: var(--color-text-secondary);
		cursor: pointer;
		padding: 2px;
		border-radius: 4px;
		opacity: 0;
		transition: opacity 0.15s, color 0.15s;
	}

	.dropdown-item:hover .dropdown-item-delete {
		opacity: 1;
	}

	.dropdown-item-delete:hover {
		color: var(--color-error);
	}

	.dropdown-create {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px;
		border-top: 1px solid var(--color-border);
	}

	.dropdown-input {
		flex: 1;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 6px 10px;
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--color-text-primary);
		outline: none;
		transition: border-color 0.15s;
	}

	.dropdown-input:focus {
		border-color: var(--color-accent);
	}

	.dropdown-input::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.5;
	}

	.dropdown-create-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		background: var(--color-accent);
		color: white;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		flex-shrink: 0;
		transition: opacity 0.15s;
	}

	.dropdown-create-btn:hover:not(:disabled) {
		opacity: 0.9;
	}

	.dropdown-create-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.dropdown-active-label {
		font-size: 9px;
		font-weight: 600;
		color: var(--color-accent);
		background: oklch(from var(--color-accent) l c h / 10%);
		padding: 1px 6px;
		border-radius: 4px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		margin-left: auto;
	}

	.dropdown-confirm-delete {
		padding: 14px 12px;
		text-align: center;
	}

	.confirm-delete-msg {
		font-size: 13px;
		color: var(--color-text-primary);
		margin: 0 0 4px;
	}

	.confirm-delete-warn {
		font-size: 11px;
		color: var(--color-text-secondary);
		margin: 0 0 12px;
		opacity: 0.7;
	}

	.confirm-delete-actions {
		display: flex;
		gap: 8px;
		justify-content: center;
	}

	.confirm-cancel-btn {
		padding: 5px 14px;
		border: 1px solid var(--color-border);
		border-radius: 6px;
		background: transparent;
		color: var(--color-text-secondary);
		font-size: 12px;
		cursor: pointer;
		transition: background 0.15s;
	}

	.confirm-cancel-btn:hover {
		background: var(--color-bg-elevated);
		color: var(--color-text-primary);
	}

	.confirm-delete-btn {
		padding: 5px 14px;
		border: 1px solid rgba(239, 68, 68, 0.3);
		border-radius: 6px;
		background: rgba(239, 68, 68, 0.15);
		color: var(--color-error, #ef4444);
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		transition: background 0.15s;
	}

	.confirm-delete-btn:hover {
		background: rgba(239, 68, 68, 0.25);
	}

	/* Save button */
	.btn-save {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		background: transparent;
		border: none;
		color: var(--color-text-secondary);
		border-radius: 6px;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.btn-save:hover {
		background: var(--color-bg-elevated);
		color: var(--color-text-primary);
	}

	.top-bar-spacer {
		flex: 1;
	}

	@media (max-width: 850px) {
		.brand {
			display: none;
		}
	}

	.top-bar-right {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}

	.btn-run {
		display: flex;
		align-items: center;
		gap: 6px;
		background: var(--color-accent);
		color: white;
		border: none;
		padding: 5px 12px;
		border-radius: 6px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		transition: opacity 0.15s, background 0.3s ease;
	}

	.btn-run:hover:not(:disabled) {
		opacity: 0.9;
	}

	.btn-run:disabled {
		cursor: not-allowed;
		opacity: 0.7;
	}

	.btn-run-active {
		background: var(--color-success);
	}

	/* Runtime toggle button */
	.btn-runtime {
		display: flex;
		align-items: center;
		gap: 5px;
		background: transparent;
		border: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		padding: 4px 10px;
		border-radius: 6px;
		font-family: var(--font-sans);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s, color 0.15s, border-color 0.15s;
	}

	.btn-runtime:hover:not(:disabled) {
		background: var(--color-bg-elevated);
		color: var(--color-text-primary);
	}

	.btn-runtime:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-runtime.runtime-running {
		border-color: color-mix(in srgb, var(--color-success) 40%, transparent);
		color: var(--color-success);
	}

	.btn-runtime.runtime-error {
		border-color: color-mix(in srgb, var(--color-error) 40%, transparent);
		color: var(--color-error);
	}

	.btn-runtime.runtime-starting {
		border-color: color-mix(in srgb, #f59e0b 40%, transparent);
		color: #f59e0b;
	}

	.runtime-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		flex-shrink: 0;
		transition: background 0.3s;
	}

	.runtime-dot.rt-stopped {
		background: var(--color-text-secondary);
	}

	.runtime-dot.rt-running {
		background: var(--color-success);
		box-shadow: 0 0 6px color-mix(in srgb, var(--color-success) 50%, transparent);
	}

	.runtime-dot.rt-error {
		background: var(--color-error);
		box-shadow: 0 0 6px color-mix(in srgb, var(--color-error) 50%, transparent);
	}

	.runtime-dot.rt-starting {
		background: #f59e0b;
		animation: runtime-pulse 1s ease-in-out infinite;
	}

	@keyframes runtime-pulse {
		0%, 100% { opacity: 0.4; }
		50% { opacity: 1; }
	}

	.btn-icon {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		background: transparent;
		border: none;
		color: var(--color-text-secondary);
		border-radius: 6px;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.btn-icon:hover:not(:disabled) {
		background: var(--color-bg-elevated);
		color: var(--color-text-primary);
	}

	.btn-icon:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}

	.btn-debug-active {
		color: var(--color-warning);
	}

	.architect-active {
		color: var(--color-accent);
		background: oklch(from var(--color-accent) l c h / 10%);
	}

	.divider {
		width: 1px;
		height: 20px;
		background: var(--color-border);
		margin: 0 4px;
	}

	.pulse-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: white;
		animation: pulse-indicator 1s ease-in-out infinite;
	}

	.debug-dot {
		position: absolute;
		top: 4px;
		right: 4px;
		width: 5px;
		height: 5px;
		background: var(--color-warning);
	}

	@keyframes pulse-indicator {
		0%, 100% { opacity: 0.4; }
		50% { opacity: 1; }
	}

	.spin-icon {
		display: flex;
		align-items: center;
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		from { transform: rotate(0deg); }
		to { transform: rotate(360deg); }
	}

	/* Run Input Dialog */
	.run-dialog-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 10000;
	}

	.run-dialog {
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 14px;
		padding: 24px;
		width: 480px;
		max-width: 90vw;
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
	}

	.run-dialog-title {
		font-size: 16px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0 0 4px;
	}

	.run-dialog-hint {
		font-size: 12px;
		color: var(--color-text-secondary);
		margin: 0 0 14px;
	}

	.run-dialog-input {
		width: 100%;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		padding: 10px 12px;
		font-family: var(--font-sans);
		font-size: 13px;
		color: var(--color-text-primary);
		resize: vertical;
		outline: none;
		box-sizing: border-box;
	}

	.run-dialog-input:focus {
		border-color: var(--color-accent);
	}

	.run-dialog-input::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.5;
	}

	.run-dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 14px;
	}

	.run-dialog-cancel {
		background: transparent;
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 7px 14px;
		font-size: 12px;
		color: var(--color-text-secondary);
		cursor: pointer;
	}

	.run-dialog-go {
		display: flex;
		align-items: center;
		gap: 6px;
		background: var(--color-accent);
		border: none;
		border-radius: 6px;
		padding: 7px 16px;
		font-size: 12px;
		font-weight: 600;
		color: white;
		cursor: pointer;
	}

	.run-dialog-go:hover {
		opacity: 0.9;
	}
</style>
