<script lang="ts">
	import {
		RefreshCw, Plus, Trash2, Download, Plug, Wrench, Check, X,
		MessageSquare, Send, Hash, Users, GitPullRequest, Mail, Globe, Webhook,
		Code, Zap, ExternalLink, ChevronDown, ChevronUp, TestTube
	} from 'lucide-svelte';
	import { api } from '$lib/api/client';
	import { addToast } from '$lib/stores/notifications';
	import type { CustomToolDefinition } from '$lib/types/graph';

	type SubTab = 'connectors' | 'tools';

	interface CatalogEntry {
		id: string;
		name: string;
		category: string;
		description: string;
		icon: string;
		requires_credential: string | null;
		installed: boolean;
		tool_name: string;
		setup_guide: string;
	}

	// Map backend icon names to lucide components
	const ICON_MAP: Record<string, typeof MessageSquare> = {
		'message-square': MessageSquare,
		'send': Send,
		'hash': Hash,
		'users': Users,
		'git-pull-request': GitPullRequest,
		'mail': Mail,
		'globe': Globe,
		'webhook': Zap,
	};

	let subTab: SubTab = $state('connectors');
	let loading = $state(false);

	// Connectors state
	let catalog: CatalogEntry[] = $state([]);
	let installingId: string | null = $state(null);
	let expandedGuideId: string | null = $state(null);

	// Custom tools state
	let tools: CustomToolDefinition[] = $state([]);
	let showCreateForm = $state(false);

	// Create form fields
	let newToolName = $state('');
	let newToolDesc = $state('');
	let newToolType: 'api' | 'webhook' | 'python' = $state('api');
	let newToolApiUrl = $state('');
	let newToolApiPath = $state('');
	let newToolApiMethod = $state('POST');
	let newToolAuthType = $state('none');
	let newToolAuthValue = $state('');
	let newToolWebhookUrl = $state('');
	let newToolCode = $state('');
	let saving = $state(false);

	async function loadConnectors() {
		loading = true;
		try {
			catalog = await api.customTools.catalog();
		} catch {
			catalog = [];
			addToast('Failed to load connector catalog', 'error');
		} finally {
			loading = false;
		}
	}

	async function loadTools() {
		loading = true;
		try {
			tools = await api.customTools.list();
		} catch {
			tools = [];
			addToast('Failed to load custom tools', 'error');
		} finally {
			loading = false;
		}
	}

	async function installConnector(id: string) {
		installingId = id;
		try {
			await api.customTools.installConnector(id);
			addToast('Connector installed', 'success');
			await loadConnectors();
		} catch {
			addToast('Failed to install connector', 'error');
		} finally {
			installingId = null;
		}
	}

	async function deleteTool(name: string) {
		try {
			await api.customTools.delete(name);
			addToast('Tool deleted', 'success');
			await loadTools();
		} catch {
			addToast('Failed to delete tool', 'error');
		}
	}

	async function testTool(name: string) {
		try {
			const result = await api.customTools.test(name);
			if (result.status === 'success') {
				addToast(`Tool "${name}" test passed (${result.response_time ?? 0}ms)`, 'success');
			} else {
				addToast(`Tool test failed: ${result.error ?? 'Unknown error'}`, 'error');
			}
		} catch {
			addToast('Failed to test tool', 'error');
		}
	}

	function resetForm() {
		newToolName = '';
		newToolDesc = '';
		newToolType = 'api';
		newToolApiUrl = '';
		newToolApiPath = '';
		newToolApiMethod = 'POST';
		newToolAuthType = 'none';
		newToolAuthValue = '';
		newToolWebhookUrl = '';
		newToolCode = '';
	}

	async function createTool() {
		if (!newToolName.trim()) {
			addToast('Tool name is required', 'error');
			return;
		}
		saving = true;
		try {
			const payload: Record<string, unknown> = {
				name: newToolName.trim().toLowerCase().replace(/\s+/g, '_'),
				description: newToolDesc.trim() || `Custom ${newToolType} tool`,
				tool_type: newToolType,
				tags: ['custom'],
			};

			if (newToolType === 'api') {
				payload.api_base_url = newToolApiUrl;
				payload.api_path = newToolApiPath;
				payload.api_method = newToolApiMethod;
				payload.api_auth_type = newToolAuthType;
				if (newToolAuthValue) payload.api_auth_value = newToolAuthValue;
			} else if (newToolType === 'webhook') {
				payload.webhook_url = newToolWebhookUrl;
				payload.webhook_method = newToolApiMethod;
			} else if (newToolType === 'python') {
				payload.python_code = newToolCode;
			}

			await api.customTools.save(payload as any);
			addToast(`Tool "${newToolName}" created`, 'success');
			showCreateForm = false;
			resetForm();
			await loadTools();
		} catch {
			addToast('Failed to create tool', 'error');
		} finally {
			saving = false;
		}
	}

	function getCategoryColor(category: string): string {
		switch (category.toLowerCase()) {
			case 'messaging': return '#6366f1';
			case 'developer': return '#22c55e';
			case 'email': return '#f59e0b';
			case 'integration': return '#8b5cf6';
			default: return '#64748b';
		}
	}

	$effect(() => {
		if (subTab === 'connectors') {
			loadConnectors();
		} else {
			loadTools();
		}
	});
</script>

<div class="panel">
	<div class="header">
		<div class="sub-tabs">
			<button
				class="sub-tab"
				class:active={subTab === 'connectors'}
				onclick={() => (subTab = 'connectors')}
			>
				<Plug size={12} />
				Connectors
			</button>
			<button
				class="sub-tab"
				class:active={subTab === 'tools'}
				onclick={() => (subTab = 'tools')}
			>
				<Wrench size={12} />
				Custom Tools
			</button>
		</div>
		<div class="header-actions">
			{#if subTab === 'tools'}
				<button class="create-btn" onclick={() => { showCreateForm = !showCreateForm; }}>
					<Plus size={12} />
					Create Tool
				</button>
			{/if}
			<button class="action-btn" onclick={() => subTab === 'connectors' ? loadConnectors() : loadTools()} title="Refresh">
				<RefreshCw size={13} />
			</button>
		</div>
	</div>

	<div class="content">
		{#if loading}
			<div class="empty-state">
				<RefreshCw size={16} class="spin" />
				<span>Loading...</span>
			</div>
		{:else if subTab === 'connectors'}
			{#if catalog.length === 0}
				<div class="empty-state">
					<Plug size={16} />
					<span>No connectors available</span>
				</div>
			{:else}
				<div class="connector-grid">
					{#each catalog as connector (connector.id)}
						{@const IconComponent = ICON_MAP[connector.icon]}
						<div class="connector-card" class:installed={connector.installed}>
							<div class="card-top">
								<div class="connector-icon" style:--cat-color={getCategoryColor(connector.category)}>
									{#if IconComponent}
										<IconComponent size={18} />
									{:else}
										<Plug size={18} />
									{/if}
								</div>
								<div class="connector-meta">
									<div class="connector-header-row">
										<span class="connector-name">{connector.name}</span>
										{#if connector.installed}
											<span class="installed-badge"><Check size={9} /> Installed</span>
										{/if}
									</div>
									<span class="connector-category" style:color={getCategoryColor(connector.category)}>
										{connector.category.toUpperCase()}
									</span>
								</div>
							</div>
							<p class="connector-desc">{connector.description}</p>
							<div class="card-footer">
								{#if connector.setup_guide}
									<button
										class="guide-toggle"
										onclick={() => expandedGuideId = expandedGuideId === connector.id ? null : connector.id}
									>
										{#if expandedGuideId === connector.id}
											<ChevronUp size={11} /> Hide Guide
										{:else}
											<ChevronDown size={11} /> Setup Guide
										{/if}
									</button>
								{/if}
								{#if !connector.installed}
									<button
										class="install-btn"
										onclick={() => installConnector(connector.id)}
										disabled={installingId === connector.id}
									>
										{#if installingId === connector.id}
											<RefreshCw size={11} class="spin" /> Installing...
										{:else}
											<Download size={11} /> Install
										{/if}
									</button>
								{/if}
							</div>
							{#if expandedGuideId === connector.id && connector.setup_guide}
								<div class="setup-guide">
									{#each connector.setup_guide.split('\n') as step}
										<p class="guide-step">{step}</p>
									{/each}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		{:else}
			<!-- Custom Tools tab -->
			{#if showCreateForm}
				<div class="create-form">
					<div class="form-header">
						<span class="form-title">Create Custom Tool</span>
						<button class="icon-btn" onclick={() => { showCreateForm = false; resetForm(); }}>
							<X size={14} />
						</button>
					</div>

					<div class="form-grid">
						<div class="form-field">
							<label class="field-label" for="tool-name">Name</label>
							<input id="tool-name" class="field-input" bind:value={newToolName} placeholder="my_custom_tool" />
						</div>

						<div class="form-field">
							<label class="field-label" for="tool-type">Type</label>
							<select id="tool-type" class="field-input" bind:value={newToolType}>
								<option value="api">REST API</option>
								<option value="webhook">Webhook</option>
								<option value="python">Python Function</option>
							</select>
						</div>

						<div class="form-field full-width">
							<label class="field-label" for="tool-desc">Description</label>
							<input id="tool-desc" class="field-input" bind:value={newToolDesc} placeholder="What this tool does..." />
						</div>

						{#if newToolType === 'api'}
							<div class="form-field">
								<label class="field-label" for="tool-url">Base URL</label>
								<input id="tool-url" class="field-input" bind:value={newToolApiUrl} placeholder="https://api.example.com" />
							</div>
							<div class="form-field">
								<label class="field-label" for="tool-path">Path</label>
								<input id="tool-path" class="field-input" bind:value={newToolApiPath} placeholder="/v1/endpoint" />
							</div>
							<div class="form-field">
								<label class="field-label" for="tool-method">Method</label>
								<select id="tool-method" class="field-input" bind:value={newToolApiMethod}>
									<option value="GET">GET</option>
									<option value="POST">POST</option>
									<option value="PUT">PUT</option>
									<option value="PATCH">PATCH</option>
									<option value="DELETE">DELETE</option>
								</select>
							</div>
							<div class="form-field">
								<label class="field-label" for="tool-auth">Auth Type</label>
								<select id="tool-auth" class="field-input" bind:value={newToolAuthType}>
									<option value="none">None</option>
									<option value="bearer">Bearer Token</option>
									<option value="api_key">API Key (Header)</option>
								</select>
							</div>
							{#if newToolAuthType !== 'none'}
								<div class="form-field full-width">
									<label class="field-label" for="tool-auth-val">
										{newToolAuthType === 'bearer' ? 'Bearer Token' : 'API Key'}
									</label>
									<input id="tool-auth-val" class="field-input" type="password" bind:value={newToolAuthValue} placeholder="Enter credential..." />
								</div>
							{/if}
						{:else if newToolType === 'webhook'}
							<div class="form-field full-width">
								<label class="field-label" for="tool-webhook">Webhook URL</label>
								<input id="tool-webhook" class="field-input" bind:value={newToolWebhookUrl} placeholder="https://hooks.example.com/..." />
							</div>
							<div class="form-field">
								<label class="field-label" for="tool-wh-method">Method</label>
								<select id="tool-wh-method" class="field-input" bind:value={newToolApiMethod}>
									<option value="POST">POST</option>
									<option value="PUT">PUT</option>
									<option value="GET">GET</option>
								</select>
							</div>
						{:else if newToolType === 'python'}
							<div class="form-field full-width">
								<label class="field-label" for="tool-code">Python Code</label>
								<textarea id="tool-code" class="field-input code-input" bind:value={newToolCode} placeholder="def run(input_data: dict) -> dict:&#10;    # Your tool logic here&#10;    return {'{'}result': 'hello'{'}'}" rows="6"></textarea>
							</div>
						{/if}
					</div>

					<div class="form-actions">
						<button class="cancel-btn" onclick={() => { showCreateForm = false; resetForm(); }}>Cancel</button>
						<button class="save-btn" onclick={createTool} disabled={saving || !newToolName.trim()}>
							{#if saving}
								<RefreshCw size={12} class="spin" /> Saving...
							{:else}
								<Check size={12} /> Create Tool
							{/if}
						</button>
					</div>
				</div>
			{/if}

			{#if tools.length === 0 && !showCreateForm}
				<div class="empty-state">
					<Wrench size={20} />
					<div class="empty-text">
						<span>No custom tools defined</span>
						<span class="empty-sub">Create a custom API, webhook, or Python tool to extend your agents</span>
					</div>
					<button class="empty-create-btn" onclick={() => (showCreateForm = true)}>
						<Plus size={14} /> Create Your First Tool
					</button>
				</div>
			{:else if tools.length > 0}
				<div class="tools-list">
					{#each tools as tool (tool.name)}
						<div class="tool-item">
							<div class="tool-icon-wrap">
								{#if tool.tool_type === 'api'}
									<Globe size={14} />
								{:else if tool.tool_type === 'webhook'}
									<Zap size={14} />
								{:else}
									<Code size={14} />
								{/if}
							</div>
							<div class="tool-info">
								<div class="tool-header">
									<span class="tool-name">{tool.name}</span>
									<span class="tool-type-badge">{tool.tool_type}</span>
								</div>
								<span class="tool-desc">{tool.description}</span>
							</div>
							<div class="tool-actions">
								<button class="icon-btn" onclick={() => testTool(tool.name)} title="Test tool">
									<TestTube size={13} />
								</button>
								<button class="icon-btn danger" onclick={() => deleteTool(tool.name)} title="Delete tool">
									<Trash2 size={13} />
								</button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		{/if}
	</div>
</div>

<style>
	.panel {
		height: 100%;
		display: flex;
		flex-direction: column;
		background: var(--color-bg-primary, #0a0a12);
		font-family: var(--font-sans, system-ui, -apple-system, sans-serif);
	}

	.header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 12px;
		height: 40px;
		min-height: 40px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
	}

	.sub-tabs {
		display: flex;
		align-items: center;
		gap: 2px;
	}

	.sub-tab {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 5px 10px;
		border: none;
		background: transparent;
		border-radius: 6px;
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.sub-tab:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-text-primary, #e8e8ed);
	}

	.sub-tab.active {
		background: rgba(255, 255, 255, 0.08);
		color: var(--color-text-primary, #e8e8ed);
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.create-btn {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px 10px;
		border: 1px solid var(--color-accent, #ff6b35);
		background: oklch(from var(--color-accent, #ff6b35) l c h / 10%);
		border-radius: 6px;
		color: var(--color-accent, #ff6b35);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s;
	}

	.create-btn:hover {
		background: oklch(from var(--color-accent, #ff6b35) l c h / 18%);
	}

	.action-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 26px;
		height: 26px;
		border: none;
		background: transparent;
		border-radius: 6px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.action-btn:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-text-primary, #e8e8ed);
	}

	.content {
		flex: 1;
		overflow-y: auto;
		padding: 12px;
	}

	.content::-webkit-scrollbar { width: 6px; }
	.content::-webkit-scrollbar-track { background: transparent; }
	.content::-webkit-scrollbar-thumb { background: var(--color-border, #2a2a3a); border-radius: 3px; }

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		height: 100%;
		color: var(--color-text-secondary, #8888a0);
		font-size: 13px;
	}

	.empty-text {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		text-align: center;
	}

	.empty-sub {
		font-size: 11px;
		opacity: 0.6;
	}

	.empty-create-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 16px;
		border: 1px solid var(--color-accent, #ff6b35);
		background: oklch(from var(--color-accent, #ff6b35) l c h / 10%);
		border-radius: 8px;
		color: var(--color-accent, #ff6b35);
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s;
		margin-top: 4px;
	}

	.empty-create-btn:hover {
		background: oklch(from var(--color-accent, #ff6b35) l c h / 18%);
	}

	/* Connector grid */
	.connector-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: 10px;
	}

	.connector-card {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 14px;
		background: var(--color-bg-secondary, #12121a);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 10px;
		transition: border-color 0.15s, box-shadow 0.15s;
	}

	.connector-card:hover {
		border-color: rgba(255, 255, 255, 0.12);
		box-shadow: 0 2px 12px -4px rgba(0,0,0,0.3);
	}

	.connector-card.installed {
		border-color: rgba(34, 197, 94, 0.2);
	}

	.card-top {
		display: flex;
		align-items: flex-start;
		gap: 10px;
	}

	.connector-icon {
		width: 36px;
		height: 36px;
		border-radius: 8px;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		background: oklch(from var(--cat-color, #6366f1) l c h / 12%);
		color: var(--cat-color, #6366f1);
	}

	.connector-meta {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.connector-header-row {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.connector-name {
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.installed-badge {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		font-size: 9px;
		font-weight: 600;
		padding: 1px 6px;
		border-radius: 4px;
		background: rgba(34, 197, 94, 0.15);
		color: #22c55e;
	}

	.connector-category {
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.06em;
		opacity: 0.8;
	}

	.connector-desc {
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
		line-height: 1.45;
		margin: 0;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.card-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin-top: 2px;
	}

	.guide-toggle {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 0;
		border: none;
		background: transparent;
		color: var(--color-text-secondary, #8888a0);
		font-size: 10px;
		cursor: pointer;
		transition: color 0.15s;
	}

	.guide-toggle:hover {
		color: var(--color-text-primary, #e8e8ed);
	}

	.install-btn {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 5px 12px;
		border: 1px solid var(--color-border, #2a2a3a);
		background: transparent;
		border-radius: 6px;
		color: var(--color-text-primary, #e8e8ed);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s, border-color 0.15s;
		margin-left: auto;
	}

	.install-btn:hover:not(:disabled) {
		background: rgba(255, 255, 255, 0.05);
		border-color: var(--color-accent, #ff6b35);
	}

	.install-btn:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.setup-guide {
		padding: 10px;
		background: var(--color-bg-elevated, #1a1a2a);
		border-radius: 6px;
		margin-top: 2px;
	}

	.guide-step {
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
		line-height: 1.6;
		margin: 0 0 2px;
	}

	/* Tools list */
	.tools-list {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.tool-item {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 10px 12px;
		background: var(--color-bg-secondary, #12121a);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 8px;
		transition: border-color 0.15s;
	}

	.tool-item:hover {
		border-color: rgba(255, 255, 255, 0.12);
	}

	.tool-icon-wrap {
		width: 32px;
		height: 32px;
		border-radius: 7px;
		display: flex;
		align-items: center;
		justify-content: center;
		background: oklch(from var(--color-accent, #ff6b35) l c h / 10%);
		color: var(--color-accent, #ff6b35);
		flex-shrink: 0;
	}

	.tool-info {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.tool-header {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.tool-name {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.tool-type-badge {
		font-size: 9px;
		padding: 1px 6px;
		border-radius: 4px;
		background: rgba(255, 255, 255, 0.06);
		color: var(--color-text-secondary, #8888a0);
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.tool-desc {
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.tool-actions {
		display: flex;
		align-items: center;
		gap: 2px;
		flex-shrink: 0;
	}

	.icon-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: none;
		background: transparent;
		border-radius: 6px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.icon-btn:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-text-primary, #e8e8ed);
	}

	.icon-btn.danger:hover {
		color: #ef4444;
		background: rgba(239, 68, 68, 0.1);
	}

	/* Create form */
	.create-form {
		background: var(--color-bg-secondary, #12121a);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 10px;
		padding: 16px;
		margin-bottom: 12px;
	}

	.form-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 14px;
	}

	.form-title {
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.form-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 10px;
	}

	.form-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.form-field.full-width {
		grid-column: 1 / -1;
	}

	.field-label {
		font-size: 10px;
		font-weight: 600;
		color: var(--color-text-secondary, #8888a0);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.field-input {
		padding: 7px 10px;
		background: var(--color-bg-primary, #0a0a12);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
		color: var(--color-text-primary, #e8e8ed);
		font-size: 12px;
		font-family: var(--font-sans, system-ui);
		outline: none;
		transition: border-color 0.15s;
	}

	.field-input:focus {
		border-color: var(--color-accent, #ff6b35);
	}

	.code-input {
		font-family: var(--font-mono, 'JetBrains Mono', monospace);
		font-size: 11px;
		line-height: 1.5;
		resize: vertical;
		min-height: 80px;
	}

	.form-actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 14px;
	}

	.cancel-btn {
		padding: 6px 14px;
		border: 1px solid var(--color-border, #2a2a3a);
		background: transparent;
		border-radius: 6px;
		color: var(--color-text-secondary, #8888a0);
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.cancel-btn:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-text-primary, #e8e8ed);
	}

	.save-btn {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 6px 14px;
		border: none;
		background: var(--color-accent, #ff6b35);
		border-radius: 6px;
		color: #fff;
		font-size: 11px;
		font-weight: 500;
		cursor: pointer;
		transition: filter 0.15s;
	}

	.save-btn:hover:not(:disabled) {
		filter: brightness(1.12);
	}

	.save-btn:disabled {
		opacity: 0.5;
		cursor: default;
	}

	:global(.spin) {
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}
</style>
