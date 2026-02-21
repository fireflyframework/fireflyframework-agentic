<script lang="ts">
	import { settingsModalOpen } from '$lib/stores/ui';
	import { settingsData, loadSettings, saveSettings } from '$lib/stores/settings';
	import SettingsIcon from 'lucide-svelte/icons/settings';
	import Check from 'lucide-svelte/icons/check';
	import User from 'lucide-svelte/icons/user';
	import KeyRound from 'lucide-svelte/icons/key-round';
	import SlidersHorizontal from 'lucide-svelte/icons/sliders-horizontal';
	import Cpu from 'lucide-svelte/icons/cpu';
	import Info from 'lucide-svelte/icons/info';
	import Eye from 'lucide-svelte/icons/eye';
	import EyeOff from 'lucide-svelte/icons/eye-off';
	import X from 'lucide-svelte/icons/x';
	import Wrench from 'lucide-svelte/icons/wrench';
	import Search from 'lucide-svelte/icons/search';
	import Database from 'lucide-svelte/icons/database';
	import MessageSquare from 'lucide-svelte/icons/message-square';
	import Sparkles from 'lucide-svelte/icons/sparkles';
	import Brain from 'lucide-svelte/icons/brain';
	import Gem from 'lucide-svelte/icons/gem';
	import Zap from 'lucide-svelte/icons/zap';
	import Wind from 'lucide-svelte/icons/wind';
	import Telescope from 'lucide-svelte/icons/telescope';
	import Layers from 'lucide-svelte/icons/layers';
	import Cloud from 'lucide-svelte/icons/cloud';
	import Server from 'lucide-svelte/icons/server';
	import Monitor from 'lucide-svelte/icons/monitor';
	import Plus from 'lucide-svelte/icons/plus';
	import Trash2 from 'lucide-svelte/icons/trash-2';
	import FlaskConical from 'lucide-svelte/icons/flask-conical';
	import Loader from 'lucide-svelte/icons/loader';
	import ChevronDown from 'lucide-svelte/icons/chevron-down';
	import Link from 'lucide-svelte/icons/link';
	import ModelSelector from '$lib/components/shared/ModelSelector.svelte';
	import { api } from '$lib/api/client';

	type SettingsSection = 'profile' | 'providers' | 'tools' | 'models' | 'about';

	const SECTIONS: { id: SettingsSection; label: string; icon: typeof User; desc: string }[] = [
		{ id: 'profile', label: 'Profile', icon: User, desc: 'Your name, role, and assistant personality' },
		{ id: 'providers', label: 'API Keys', icon: KeyRound, desc: 'Configure LLM provider credentials' },
		{ id: 'tools', label: 'Tool Credentials', icon: Wrench, desc: 'Search, database, and messaging keys' },
		{ id: 'models', label: 'Model Defaults', icon: SlidersHorizontal, desc: 'Default model, temperature, and retries' },
		{ id: 'about', label: 'About', icon: Info, desc: 'Version and system information' },
	];

	const TOOL_CREDENTIAL_GROUPS = [
		{
			label: 'Search',
			icon: Search,
			color: '#f59e0b',
			fields: [
				{ key: 'serpapi_api_key', label: 'SerpAPI Key', placeholder: 'API key' },
				{ key: 'serper_api_key', label: 'Serper Key', placeholder: 'API key' },
				{ key: 'tavily_api_key', label: 'Tavily Key', placeholder: 'tvly-...' },
			]
		},
		{
			label: 'Data',
			icon: Database,
			color: '#3b82f6',
			fields: [
				{ key: 'database_url', label: 'Database URL', placeholder: 'postgresql://...' },
				{ key: 'redis_url', label: 'Redis URL', placeholder: 'redis://localhost:6379' },
			]
		},
		{
			label: 'Messaging',
			icon: MessageSquare,
			color: '#8b5cf6',
			fields: [
				{ key: 'slack_bot_token', label: 'Slack Bot Token', placeholder: 'xoxb-...' },
				{ key: 'telegram_bot_token', label: 'Telegram Bot Token', placeholder: 'Bot token' },
			]
		},
	] as const;

	const PROVIDERS = [
		{ id: 'openai', label: 'OpenAI', icon: Sparkles, color: '#10a37f', fields: [{ key: 'openai_api_key', label: 'API Key', placeholder: 'sk-...' }] },
		{ id: 'anthropic', label: 'Anthropic', icon: Brain, color: '#d4a574', fields: [{ key: 'anthropic_api_key', label: 'API Key', placeholder: 'sk-ant-...' }] },
		{ id: 'google', label: 'Google Gemini', icon: Gem, color: '#4285f4', fields: [{ key: 'google_api_key', label: 'API Key', placeholder: 'AIza...' }] },
		{ id: 'groq', label: 'Groq', icon: Zap, color: '#f55036', fields: [{ key: 'groq_api_key', label: 'API Key', placeholder: 'gsk_...' }] },
		{ id: 'mistral', label: 'Mistral', icon: Wind, color: '#ff7000', fields: [{ key: 'mistral_api_key', label: 'API Key', placeholder: 'API key' }] },
		{ id: 'deepseek', label: 'DeepSeek', icon: Telescope, color: '#4d6bfe', fields: [{ key: 'deepseek_api_key', label: 'API Key', placeholder: 'API key' }] },
		{ id: 'cohere', label: 'Cohere', icon: Layers, color: '#39594d', fields: [{ key: 'cohere_api_key', label: 'API Key', placeholder: 'API key' }] },
		{ id: 'azure', label: 'Azure OpenAI', icon: Cloud, color: '#0078d4', fields: [
			{ key: 'azure_openai_api_key', label: 'API Key', placeholder: 'API key' },
			{ key: 'azure_openai_endpoint', label: 'Endpoint URL', placeholder: 'https://your-resource.openai.azure.com/' }
		] },
		{ id: 'bedrock', label: 'Amazon Bedrock', icon: Server, color: '#ff9900', fields: [
			{ key: 'aws_access_key_id', label: 'Access Key ID', placeholder: 'AKIA...' },
			{ key: 'aws_secret_access_key', label: 'Secret Access Key', placeholder: 'Secret key' },
			{ key: 'aws_default_region', label: 'Region', placeholder: 'us-east-1' }
		] },
		{ id: 'ollama', label: 'Ollama (Local)', icon: Monitor, color: '#ffffff', fields: [{ key: 'ollama_base_url', label: 'Base URL', placeholder: 'http://localhost:11434' }] }
	] as const;

	const SERVICE_CATALOG = [
		{ type: 'serpapi', label: 'SerpAPI', category: 'Search', fields: ['api_key'] },
		{ type: 'serper', label: 'Serper', category: 'Search', fields: ['api_key'] },
		{ type: 'tavily', label: 'Tavily', category: 'Search', fields: ['api_key'] },
		{ type: 'postgresql', label: 'PostgreSQL', category: 'Databases', fields: ['host', 'port', 'username', 'password', 'database', 'ssl_enabled'], defaultPort: 5432 },
		{ type: 'mysql', label: 'MySQL', category: 'Databases', fields: ['host', 'port', 'username', 'password', 'database', 'ssl_enabled'], defaultPort: 3306 },
		{ type: 'sqlite', label: 'SQLite', category: 'Databases', fields: ['database'] },
		{ type: 'mongodb', label: 'MongoDB', category: 'Databases', fields: ['host', 'port', 'username', 'password', 'database', 'connection_url'], defaultPort: 27017 },
		{ type: 'redis', label: 'Redis', category: 'Queues', fields: ['host', 'port', 'password', 'database', 'ssl_enabled'], defaultPort: 6379 },
		{ type: 'rabbitmq', label: 'RabbitMQ', category: 'Queues', fields: ['host', 'port', 'username', 'password', 'ssl_enabled'], defaultPort: 5672 },
		{ type: 'slack', label: 'Slack', category: 'Messaging', fields: ['token'] },
		{ type: 'telegram', label: 'Telegram', category: 'Messaging', fields: ['token'] },
		{ type: 'discord', label: 'Discord', category: 'Messaging', fields: ['token'] },
	] as const;

	const SERVICE_CATEGORY_COLORS: Record<string, string> = {
		'Search': '#f59e0b',
		'Databases': '#3b82f6',
		'Queues': '#10b981',
		'Messaging': '#8b5cf6',
	};

	const SERVICE_FIELD_LABELS: Record<string, string> = {
		api_key: 'API Key',
		host: 'Host',
		port: 'Port',
		username: 'Username',
		password: 'Password',
		database: 'Database',
		ssl_enabled: 'SSL Enabled',
		connection_url: 'Connection URL',
		token: 'Token',
	};

	let services = $state<Array<Record<string, any>>>([]);
	let showAddService = $state(false);
	let testingService = $state<string | null>(null);
	let testResult = $state<{ id: string; status: string; message: string } | null>(null);
	let deletingService = $state<string | null>(null);
	let servicesLoaded = $state(false);

	async function loadServices() {
		try {
			services = await api.settings.services.list();
		} catch {
			services = [];
		}
		servicesLoaded = true;
	}

	async function addService(catalogEntry: typeof SERVICE_CATALOG[number]) {
		const newService: Record<string, unknown> = {
			id: globalThis.crypto.randomUUID(),
			service_type: catalogEntry.type,
			label: catalogEntry.label,
		};
		if ('defaultPort' in catalogEntry) {
			newService.port = (catalogEntry as any).defaultPort;
		}
		try {
			const result = await api.settings.services.add(newService);
			await loadServices();
			showAddService = false;
		} catch {
			// silently fail
		}
	}

	async function deleteService(id: string) {
		deletingService = id;
		try {
			await api.settings.services.delete(id);
			services = services.filter(s => s.id !== id);
		} catch {
			// silently fail
		} finally {
			deletingService = null;
		}
	}

	async function testService(id: string) {
		testingService = id;
		testResult = null;
		try {
			const result = await api.settings.services.test(id);
			testResult = { id, status: result.status, message: result.message };
		} catch (e: any) {
			testResult = { id, status: 'error', message: e.message || 'Connection failed' };
		} finally {
			testingService = null;
		}
	}

	async function updateServiceField(id: string, field: string, value: unknown) {
		const svc = services.find(s => s.id === id);
		if (!svc) return;
		const updated = { ...svc, [field]: value };
		try {
			await api.settings.services.add(updated);
			services = services.map(s => s.id === id ? updated : s);
		} catch {
			// silently fail
		}
	}

	function getServicesByCategory(): Array<{ category: string; items: Array<Record<string, any>> }> {
		const grouped: Record<string, Array<Record<string, any>>> = {};
		for (const svc of services) {
			const cat = SERVICE_CATALOG.find(c => c.type === svc.service_type);
			const category = cat?.category ?? 'Other';
			if (!grouped[category]) grouped[category] = [];
			grouped[category].push(svc);
		}
		return Object.entries(grouped).map(([category, items]) => ({ category, items }));
	}

	function getCatalogFieldsForType(type: string): readonly string[] {
		return SERVICE_CATALOG.find(c => c.type === type)?.fields ?? [];
	}

	const serviceCatalogCategories = [...new Set(SERVICE_CATALOG.map(c => c.category))];

	let activeSection = $state<SettingsSection>('profile');
	let saving = $state(false);
	let saved = $state(false);

	// Draft state
	let draftCreds = $state<Record<string, string>>({});
	let draftModel = $state('openai:gpt-4o');
	let draftTemperature = $state(0.7);
	let draftRetries = $state(3);

	// Profile drafts
	let draftName = $state('');
	let draftRole = $state('');
	let draftContext = $state('');
	let draftAssistantName = $state('The Architect');

	// Tool credential drafts
	let draftToolCreds = $state<Record<string, string>>({});

	// Toggle visibility for API key fields
	let visibleFields = $state<Set<string>>(new Set());

	function toggleFieldVisibility(key: string) {
		const next = new Set(visibleFields);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		visibleFields = next;
	}

	// Reset drafts when modal opens
	$effect(() => {
		if ($settingsModalOpen && $settingsData) {
			draftCreds = {};
			draftToolCreds = {};
			draftModel = $settingsData.model_defaults.default_model;
			draftTemperature = $settingsData.model_defaults.temperature;
			draftRetries = $settingsData.model_defaults.retries;
			if ($settingsData.user_profile) {
				draftName = $settingsData.user_profile.name || '';
				draftRole = $settingsData.user_profile.role || '';
				draftContext = $settingsData.user_profile.context || '';
				draftAssistantName = $settingsData.user_profile.assistant_name || 'The Architect';
			}
			activeSection = 'profile';
			saved = false;
			visibleFields = new Set();
			servicesLoaded = false;
			services = [];
		}
	});

	// Load services when tools section is active
	$effect(() => {
		if (activeSection === 'tools' && !servicesLoaded) {
			loadServices();
		}
	});

	function isConfigured(fieldKey: string): boolean {
		if (!$settingsData) return false;
		const val = ($settingsData.credentials as Record<string, string | null>)[fieldKey];
		return val !== null && val !== undefined;
	}

	function isToolConfigured(fieldKey: string): boolean {
		if (!$settingsData) return false;
		const tc = ($settingsData as Record<string, unknown>).tool_credentials as Record<string, string | null> | undefined;
		if (!tc) return false;
		const val = tc[fieldKey];
		return val !== null && val !== undefined && val !== '';
	}

	let configuredCount = $derived(
		$settingsData ? PROVIDERS.filter(p => p.fields.every(f => isConfigured(f.key))).length : 0
	);

	function close() {
		settingsModalOpen.set(false);
	}

	async function handleSave() {
		saving = true;
		try {
			const creds: Record<string, string | null> = {};
			for (const [key, val] of Object.entries(draftCreds)) {
				if (val.trim()) creds[key] = val.trim();
			}

			const profile: Record<string, string> = {
				name: draftName.trim(),
				role: draftRole.trim(),
				context: draftContext.trim(),
				assistant_name: draftAssistantName.trim() || 'The Architect',
			};

			const toolCreds: Record<string, string | null> = {};
			for (const [key, val] of Object.entries(draftToolCreds)) {
				toolCreds[key] = val.trim() || null;
			}

			const hasConfiguredProvider = PROVIDERS.some(p => p.fields.every(f => isConfigured(f.key)))
				|| Object.values(creds).some(v => v !== null);

			await saveSettings(
				Object.keys(creds).length > 0 ? creds : null,
				{ default_model: draftModel, temperature: draftTemperature, retries: draftRetries },
				hasConfiguredProvider,
				profile,
				Object.keys(toolCreds).length > 0 ? toolCreds : null
			);
			saved = true;
			setTimeout(() => { saved = false; }, 2000);
		} catch {
			// Error is logged in the store
		} finally {
			saving = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	}
</script>

{#if $settingsModalOpen}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="settings-overlay" onkeydown={handleKeydown}>
		<div class="settings-page">
			<!-- Sidebar -->
			<aside class="settings-sidebar">
				<div class="sidebar-header">
					<SettingsIcon size={18} />
					<span>Settings</span>
				</div>

				<nav class="sidebar-nav">
					{#each SECTIONS as section}
						<button
							class="sidebar-item"
							class:active={activeSection === section.id}
							onclick={() => activeSection = section.id}
						>
							<section.icon size={16} />
							<div class="sidebar-item-text">
								<span class="sidebar-item-label">{section.label}</span>
								<span class="sidebar-item-desc">{section.desc}</span>
							</div>
							{#if section.id === 'providers'}
								<span class="sidebar-badge">{configuredCount}/{PROVIDERS.length}</span>
							{/if}
						</button>
					{/each}
				</nav>

				<div class="sidebar-footer">
					<button class="btn-close-sidebar" onclick={close}>
						<X size={14} />
						<span>Close</span>
						<kbd class="esc-hint">ESC</kbd>
					</button>
				</div>
			</aside>

			<!-- Content -->
			<main class="settings-content">
				<div class="content-header">
					<h2 class="content-title">
						{SECTIONS.find(s => s.id === activeSection)?.label}
					</h2>
					<div class="content-actions">
						{#if saved}
							<span class="save-success"><Check size={14} /> Saved</span>
						{/if}
						<button class="btn-save" onclick={handleSave} disabled={saving}>
							{saving ? 'Saving...' : 'Save Changes'}
						</button>
					</div>
				</div>

				<div class="content-body">
					<!-- ===== Profile Section ===== -->
					{#if activeSection === 'profile'}
						<div class="section-card">
							<h3 class="card-title">Your Information</h3>
							<p class="card-desc">The Architect and Oracle use this to personalise interactions.</p>
							<div class="fields-grid">
								<div class="field">
									<label class="field-label" for="settings-name">Name</label>
									<input
										id="settings-name"
										type="text"
										class="field-input"
										placeholder="Your name"
										bind:value={draftName}
									/>
								</div>
								<div class="field">
									<label class="field-label" for="settings-role">Role</label>
									<input
										id="settings-role"
										type="text"
										class="field-input"
										placeholder="e.g. ML Engineer"
										bind:value={draftRole}
									/>
								</div>
							</div>
							<div class="field">
								<label class="field-label" for="settings-context">
									Context <span class="field-optional">(optional)</span>
								</label>
								<textarea
									id="settings-context"
									class="field-textarea"
									placeholder="Tell the assistant about your project, preferences, or constraints..."
									bind:value={draftContext}
									rows="3"
								></textarea>
							</div>
						</div>

						<div class="section-card">
							<h3 class="card-title">Assistant Personality</h3>
							<p class="card-desc">
								Choose the AI assistant's persona. "The Architect" uses a philosophical,
								Matrix-inspired personality. Any other name uses a standard helpful assistant.
							</p>
							<div class="field">
								<label class="field-label" for="settings-assistant-name">Assistant Name</label>
								<input
									id="settings-assistant-name"
									type="text"
									class="field-input"
									placeholder="The Architect"
									bind:value={draftAssistantName}
								/>
							</div>
							{#if draftAssistantName === 'The Architect'}
								<div class="personality-preview">
									<Cpu size={14} />
									<span>The Architect speaks with measured authority and philosophical precision. He will address you by name and guide you through the design of your pipeline.</span>
								</div>
							{:else}
								<div class="personality-preview neutral">
									<Cpu size={14} />
									<span>A friendly, helpful AI assistant that guides you through building pipelines.</span>
								</div>
							{/if}
						</div>

					<!-- ===== Providers Section ===== -->
					{:else if activeSection === 'providers'}
						<p class="section-intro">
							Configure API keys for your LLM providers. Keys are stored locally and never sent to external services.
						</p>
						<div class="providers-grid">
							{#each PROVIDERS as provider}
								{@const configured = provider.fields.every(f => isConfigured(f.key))}
								<div class="provider-card" class:configured>
									<div class="provider-header">
										<div class="provider-icon-wrap" style="--provider-color: {provider.color}">
											<provider.icon size={15} />
										</div>
										<span class="provider-name">{provider.label}</span>
										{#if configured}
											<span class="provider-badge"><Check size={10} /> Active</span>
										{/if}
									</div>
									<div class="provider-fields">
										{#each provider.fields as field}
											<div class="provider-field">
												<label class="field-label" for="settings-{field.key}">{field.label}</label>
												<div class="field-with-toggle">
													<input
														id="settings-{field.key}"
														type={visibleFields.has(field.key) ? 'text' : 'password'}
														class="field-input field-mono"
														placeholder={isConfigured(field.key) ? '••••••••  (configured)' : field.placeholder}
														value={draftCreds[field.key] ?? ''}
														oninput={(e) => { draftCreds[field.key] = (e.target as HTMLInputElement).value; }}
													/>
													<button class="field-toggle" onclick={() => toggleFieldVisibility(field.key)} type="button">
														{#if visibleFields.has(field.key)}
															<EyeOff size={14} />
														{:else}
															<Eye size={14} />
														{/if}
													</button>
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/each}
						</div>

					<!-- ===== Tool Credentials Section ===== -->
					{:else if activeSection === 'tools'}
						<p class="section-intro">
							Configure credentials for pipeline tools. These enable search, database, and messaging capabilities in your pipelines.
						</p>
						<div class="providers-grid">
							{#each TOOL_CREDENTIAL_GROUPS as group}
								{@const hasAny = group.fields.some(f => isToolConfigured(f.key))}
								<div class="provider-card" class:configured={hasAny}>
									<div class="provider-header">
										<div class="provider-icon-wrap" style="--provider-color: {group.color}">
											<group.icon size={15} />
										</div>
										<span class="provider-name">{group.label}</span>
										{#if hasAny}
											<span class="provider-badge"><Check size={10} /> Active</span>
										{/if}
									</div>
									<div class="provider-fields">
										{#each group.fields as field}
											<div class="provider-field">
												<label class="field-label" for="settings-tool-{field.key}">{field.label}</label>
												<div class="field-with-toggle">
													<input
														id="settings-tool-{field.key}"
														type={visibleFields.has(field.key) ? 'text' : 'password'}
														class="field-input field-mono"
														placeholder={isToolConfigured(field.key) ? '••••••••  (configured)' : field.placeholder}
														value={draftToolCreds[field.key] ?? ''}
														oninput={(e) => { draftToolCreds[field.key] = (e.target as HTMLInputElement).value; }}
													/>
													<button class="field-toggle" onclick={() => toggleFieldVisibility(field.key)} type="button">
														{#if visibleFields.has(field.key)}
															<EyeOff size={14} />
														{:else}
															<Eye size={14} />
														{/if}
													</button>
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/each}
						</div>

						<!-- ===== Service Connections (Dynamic) ===== -->
						<div class="service-connections-section">
							<div class="service-connections-header">
								<div class="service-connections-title-row">
									<Link size={16} />
									<h3 class="card-title" style="margin: 0;">Service Connections</h3>
								</div>
								<p class="card-desc" style="margin-bottom: 0;">
									Manage external service connections for databases, queues, and third-party APIs.
								</p>
							</div>

							<!-- Add Service Button / Dropdown -->
							<div class="add-service-wrap">
								<button class="btn-add-service" onclick={() => showAddService = !showAddService}>
									<Plus size={14} />
									<span>Add Service</span>
									<ChevronDown size={12} />
								</button>

								{#if showAddService}
									<!-- svelte-ignore a11y_no_static_element_interactions -->
									<div class="dropdown-backdrop" onclick={() => showAddService = false} onkeydown={() => {}}></div>
									<div class="add-service-dropdown">
										{#each serviceCatalogCategories as cat}
											<div class="dropdown-category">
												<span class="dropdown-category-label">{cat}</span>
												{#each SERVICE_CATALOG.filter(c => c.category === cat) as entry}
													<button
														class="dropdown-item"
														onclick={() => addService(entry)}
													>
														<span class="dropdown-item-dot" style="background: {SERVICE_CATEGORY_COLORS[cat] ?? '#888'}"></span>
														{entry.label}
													</button>
												{/each}
											</div>
										{/each}
									</div>
								{/if}
							</div>

							<!-- Service Cards by Category -->
							{#if services.length === 0 && servicesLoaded}
								<div class="empty-services">
									<span class="empty-services-text">No service connections configured yet. Click "Add Service" to get started.</span>
								</div>
							{:else}
								{#each getServicesByCategory() as group}
									<div class="service-category-group">
										<span class="service-category-label" style="color: {SERVICE_CATEGORY_COLORS[group.category] ?? '#888'}">{group.category}</span>
										<div class="service-cards-list">
											{#each group.items as svc (svc.id)}
												{@const catalogEntry = SERVICE_CATALOG.find(c => c.type === svc.service_type)}
												{@const fields = getCatalogFieldsForType(svc.service_type)}
												<div class="service-card">
													<div class="service-card-header">
														<div class="service-card-icon" style="background: {SERVICE_CATEGORY_COLORS[group.category] ?? '#888'}20; color: {SERVICE_CATEGORY_COLORS[group.category] ?? '#888'}">
															{#if group.category === 'Databases'}
																<Database size={14} />
															{:else if group.category === 'Queues'}
																<Server size={14} />
															{:else if group.category === 'Messaging'}
																<MessageSquare size={14} />
															{:else}
																<Search size={14} />
															{/if}
														</div>
														<span class="service-card-label">{svc.label || catalogEntry?.label || svc.service_type}</span>
														<span class="service-card-type">{svc.service_type}</span>
														<div class="service-card-actions">
															<button
																class="btn-service-action"
																title="Test connection"
																disabled={testingService === svc.id}
																onclick={() => testService(svc.id)}
															>
																{#if testingService === svc.id}
																	<Loader size={13} class="spinning" />
																{:else}
																	<FlaskConical size={13} />
																{/if}
															</button>
															<button
																class="btn-service-action btn-service-delete"
																title="Remove service"
																disabled={deletingService === svc.id}
																onclick={() => deleteService(svc.id)}
															>
																<Trash2 size={13} />
															</button>
														</div>
													</div>

													<!-- Test result banner -->
													{#if testResult && testResult.id === svc.id}
														<div class="test-result-banner" class:test-success={testResult.status === 'ok'} class:test-error={testResult.status !== 'ok'}>
															{testResult.message}
														</div>
													{/if}

													<!-- Dynamic fields -->
													<div class="service-card-fields">
														{#each fields as fieldName}
															<div class="service-field-row">
																<label class="field-label" for="svc-{svc.id}-{fieldName}">{SERVICE_FIELD_LABELS[fieldName] ?? fieldName}</label>
																{#if fieldName === 'ssl_enabled'}
																	<label class="toggle-switch">
																		<input
																			id="svc-{svc.id}-{fieldName}"
																			type="checkbox"
																			checked={svc[fieldName] ?? false}
																			onchange={(e) => updateServiceField(svc.id, fieldName, (e.target as HTMLInputElement).checked)}
																		/>
																		<span class="toggle-slider"></span>
																	</label>
																{:else if fieldName === 'port'}
																	<input
																		id="svc-{svc.id}-{fieldName}"
																		type="number"
																		class="field-input field-mono field-narrow"
																		placeholder={String(catalogEntry && 'defaultPort' in catalogEntry ? (catalogEntry as any).defaultPort : '')}
																		value={svc[fieldName] ?? ''}
																		onchange={(e) => updateServiceField(svc.id, fieldName, parseInt((e.target as HTMLInputElement).value) || null)}
																	/>
																{:else if fieldName === 'password' || fieldName === 'api_key' || fieldName === 'token'}
																	<div class="field-with-toggle">
																		<input
																			id="svc-{svc.id}-{fieldName}"
																			type={visibleFields.has(`svc-${svc.id}-${fieldName}`) ? 'text' : 'password'}
																			class="field-input field-mono"
																			placeholder={SERVICE_FIELD_LABELS[fieldName] ?? fieldName}
																			value={svc[fieldName] ?? ''}
																			onchange={(e) => updateServiceField(svc.id, fieldName, (e.target as HTMLInputElement).value)}
																		/>
																		<button class="field-toggle" onclick={() => toggleFieldVisibility(`svc-${svc.id}-${fieldName}`)} type="button">
																			{#if visibleFields.has(`svc-${svc.id}-${fieldName}`)}
																				<EyeOff size={14} />
																			{:else}
																				<Eye size={14} />
																			{/if}
																		</button>
																	</div>
																{:else}
																	<input
																		id="svc-{svc.id}-{fieldName}"
																		type="text"
																		class="field-input field-mono"
																		placeholder={SERVICE_FIELD_LABELS[fieldName] ?? fieldName}
																		value={svc[fieldName] ?? ''}
																		onchange={(e) => updateServiceField(svc.id, fieldName, (e.target as HTMLInputElement).value)}
																	/>
																{/if}
															</div>
														{/each}
													</div>
												</div>
											{/each}
										</div>
									</div>
								{/each}
							{/if}
						</div>

					<!-- ===== Model Defaults Section ===== -->
					{:else if activeSection === 'models'}
						<div class="section-card">
							<h3 class="card-title">Default Model</h3>
							<p class="card-desc">This model is used for new agent nodes and The Architect. You can override per-node.</p>
							<div class="field">
								<label class="field-label">Model</label>
								<ModelSelector bind:value={draftModel} placeholder="Select or type a model..." />
							</div>
						</div>

						<div class="section-card">
							<h3 class="card-title">Generation Parameters</h3>
							<p class="card-desc">Control the creativity and reliability of model outputs.</p>
							<div class="field">
								<label class="field-label" for="settings-temperature">
									Temperature
								</label>
								<div class="range-row">
									<input
										id="settings-temperature"
										type="range"
										class="field-range"
										min="0"
										max="2"
										step="0.01"
										bind:value={draftTemperature}
									/>
									<span class="range-value">{draftTemperature.toFixed(2)}</span>
								</div>
								<div class="range-labels">
									<span>Precise</span>
									<span>Creative</span>
								</div>
							</div>
							<div class="field">
								<label class="field-label" for="settings-retries">Max Retries</label>
								<p class="field-hint">Number of retry attempts if a model call fails.</p>
								<input
									id="settings-retries"
									type="number"
									class="field-input field-narrow"
									min="0"
									max="10"
									bind:value={draftRetries}
								/>
							</div>
						</div>

					<!-- ===== About Section ===== -->
					{:else if activeSection === 'about'}
						<div class="section-card">
							<h3 class="card-title">Firefly Agentic Studio</h3>
							<p class="card-desc">A visual IDE for building, testing, and deploying AI agent pipelines.</p>
							<div class="about-rows">
								<div class="about-row">
									<span class="about-label">Version</span>
									<span class="about-value">0.1.0-alpha</span>
								</div>
								<div class="about-row">
									<span class="about-label">Framework</span>
									<span class="about-value">Firefly Framework GenAI</span>
								</div>
								<div class="about-row">
									<span class="about-label">Backend</span>
									<span class="about-value">FastAPI + Python 3.11+</span>
								</div>
								<div class="about-row">
									<span class="about-label">Frontend</span>
									<span class="about-value">SvelteKit 5 + TypeScript</span>
								</div>
								<div class="about-row">
									<span class="about-label">License</span>
									<span class="about-value">Apache 2.0</span>
								</div>
							</div>
						</div>

						<div class="section-card">
							<h3 class="card-title">Keyboard Shortcuts</h3>
							<div class="shortcuts-grid">
								<div class="shortcut-row">
									<span class="shortcut-label">Save Pipeline</span>
									<kbd>Cmd + S</kbd>
								</div>
								<div class="shortcut-row">
									<span class="shortcut-label">Toggle Architect</span>
									<kbd>Cmd + /</kbd>
								</div>
								<div class="shortcut-row">
									<span class="shortcut-label">Command Palette</span>
									<kbd>Cmd + K</kbd>
								</div>
								<div class="shortcut-row">
									<span class="shortcut-label">Close Modal / Panel</span>
									<kbd>ESC</kbd>
								</div>
							</div>
						</div>
					{/if}
				</div>
			</main>
		</div>
	</div>
{/if}

<style>
	/* ===== Full-page overlay ===== */
	.settings-overlay {
		position: fixed;
		inset: 0;
		z-index: 9999;
		background: var(--color-bg-primary);
		animation: settings-in 0.2s ease-out;
	}

	@keyframes settings-in {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	.settings-page {
		display: flex;
		height: 100%;
		overflow: hidden;
	}

	/* ===== Sidebar ===== */
	.settings-sidebar {
		width: 280px;
		min-width: 280px;
		background: var(--color-bg-secondary);
		border-right: 1px solid var(--color-border);
		display: flex;
		flex-direction: column;
		padding: 0;
	}

	.sidebar-header {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 20px 20px 16px;
		font-family: var(--font-sans);
		font-size: 15px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.sidebar-nav {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 0 10px;
		overflow-y: auto;
	}

	.sidebar-item {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		padding: 10px 12px;
		border: none;
		background: transparent;
		border-radius: 8px;
		cursor: pointer;
		text-align: left;
		color: var(--color-text-secondary);
		transition: background 0.15s, color 0.15s;
	}

	.sidebar-item:hover {
		background: oklch(from var(--color-text-primary) l c h / 4%);
		color: var(--color-text-primary);
	}

	.sidebar-item.active {
		background: oklch(from var(--color-accent) l c h / 8%);
		color: var(--color-accent);
	}

	.sidebar-item :global(svg) {
		margin-top: 2px;
		flex-shrink: 0;
	}

	.sidebar-item-text {
		display: flex;
		flex-direction: column;
		gap: 2px;
		flex: 1;
		min-width: 0;
	}

	.sidebar-item-label {
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 600;
	}

	.sidebar-item-desc {
		font-family: var(--font-sans);
		font-size: 11px;
		font-weight: 400;
		color: var(--color-text-secondary);
		opacity: 0.7;
		line-height: 1.4;
	}

	.sidebar-item.active .sidebar-item-desc {
		opacity: 0.8;
	}

	.sidebar-badge {
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 600;
		color: var(--color-text-secondary);
		background: oklch(from var(--color-text-primary) l c h / 5%);
		border-radius: 4px;
		padding: 2px 6px;
		margin-top: 2px;
		flex-shrink: 0;
	}

	.sidebar-footer {
		padding: 12px 10px;
		border-top: 1px solid var(--color-border);
	}

	.btn-close-sidebar {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 8px 12px;
		border: none;
		background: transparent;
		border-radius: 8px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.btn-close-sidebar:hover {
		background: oklch(from var(--color-text-primary) l c h / 4%);
		color: var(--color-text-primary);
	}

	.esc-hint {
		margin-left: auto;
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 500;
		color: var(--color-text-secondary);
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 4px;
		padding: 1px 5px;
		opacity: 0.6;
	}

	/* ===== Content area ===== */
	.settings-content {
		flex: 1;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.content-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 20px 32px 16px;
		border-bottom: 1px solid var(--color-border);
		flex-shrink: 0;
	}

	.content-title {
		font-family: var(--font-sans);
		font-size: 20px;
		font-weight: 700;
		color: var(--color-text-primary);
		margin: 0;
		letter-spacing: -0.01em;
	}

	.content-actions {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.save-success {
		display: flex;
		align-items: center;
		gap: 4px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 500;
		color: var(--color-success);
		animation: fade-in-out 2s ease forwards;
	}

	@keyframes fade-in-out {
		0% { opacity: 0; }
		10% { opacity: 1; }
		80% { opacity: 1; }
		100% { opacity: 0; }
	}

	.btn-save {
		background: var(--color-accent);
		border: none;
		border-radius: 8px;
		padding: 8px 18px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 600;
		color: white;
		cursor: pointer;
		transition: opacity 0.15s, transform 0.1s;
	}

	.btn-save:hover:not(:disabled) {
		opacity: 0.92;
		transform: translateY(-0.5px);
	}

	.btn-save:active:not(:disabled) {
		transform: scale(0.97);
	}

	.btn-save:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.content-body {
		flex: 1;
		overflow-y: auto;
		padding: 24px 32px 40px;
		display: flex;
		flex-direction: column;
		gap: 20px;
		max-width: 720px;
	}

	/* ===== Section intro ===== */
	.section-intro {
		font-family: var(--font-sans);
		font-size: 13px;
		color: var(--color-text-secondary);
		margin: 0 0 4px;
		line-height: 1.55;
	}

	/* ===== Section cards ===== */
	.section-card {
		border: 1px solid var(--color-border);
		border-radius: 12px;
		padding: 20px;
		background: var(--color-bg-secondary);
	}

	.card-title {
		font-family: var(--font-sans);
		font-size: 14px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0 0 4px;
	}

	.card-desc {
		font-family: var(--font-sans);
		font-size: 12px;
		color: var(--color-text-secondary);
		margin: 0 0 16px;
		line-height: 1.55;
	}

	/* ===== Fields ===== */
	.field {
		margin-top: 12px;
	}

	.field:first-of-type {
		margin-top: 0;
	}

	.fields-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 12px;
		margin-bottom: 4px;
	}

	.fields-grid .field {
		margin-top: 0;
	}

	.field-label {
		display: block;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-secondary);
		margin-bottom: 6px;
	}

	.field-optional {
		opacity: 0.5;
		font-weight: 400;
	}

	.field-hint {
		font-family: var(--font-sans);
		font-size: 11px;
		color: var(--color-text-secondary);
		margin: 0 0 6px;
		opacity: 0.6;
	}

	.field-input {
		width: 100%;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		padding: 9px 12px;
		font-family: var(--font-sans);
		font-size: 13px;
		color: var(--color-text-primary);
		outline: none;
		transition: border-color 0.2s, box-shadow 0.2s;
		box-sizing: border-box;
	}

	.field-input.field-mono {
		font-family: var(--font-mono);
		font-size: 12px;
	}

	.field-input.field-narrow {
		width: 100px;
	}

	.field-input:focus {
		border-color: oklch(from var(--color-accent) l c h / 50%);
		box-shadow: 0 0 0 3px oklch(from var(--color-accent) l c h / 8%);
	}

	.field-input::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.45;
	}

	.field-with-toggle {
		display: flex;
		gap: 0;
		position: relative;
	}

	.field-with-toggle .field-input {
		padding-right: 40px;
	}

	.field-toggle {
		position: absolute;
		right: 4px;
		top: 50%;
		transform: translateY(-50%);
		display: flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		border: none;
		background: transparent;
		border-radius: 6px;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.field-toggle:hover {
		background: var(--color-overlay-subtle);
		color: var(--color-text-primary);
	}

	.field-textarea {
		width: 100%;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		padding: 9px 12px;
		font-family: var(--font-sans);
		font-size: 13px;
		color: var(--color-text-primary);
		outline: none;
		transition: border-color 0.2s, box-shadow 0.2s;
		box-sizing: border-box;
		resize: vertical;
		min-height: 60px;
		line-height: 1.55;
	}

	.field-textarea:focus {
		border-color: oklch(from var(--color-accent) l c h / 50%);
		box-shadow: 0 0 0 3px oklch(from var(--color-accent) l c h / 8%);
	}

	.field-textarea::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.45;
	}

	/* Range slider */
	.range-row {
		display: flex;
		align-items: center;
		gap: 14px;
	}

	.field-range {
		flex: 1;
		accent-color: var(--color-accent);
		height: 4px;
	}

	.range-value {
		font-family: var(--font-mono);
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary);
		min-width: 36px;
		text-align: right;
	}

	.range-labels {
		display: flex;
		justify-content: space-between;
		font-family: var(--font-sans);
		font-size: 10px;
		color: var(--color-text-secondary);
		opacity: 0.5;
		margin-top: 4px;
	}

	/* Personality preview */
	.personality-preview {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		margin-top: 12px;
		padding: 10px 14px;
		background: oklch(from var(--color-accent) l c h / 5%);
		border: 1px solid oklch(from var(--color-accent) l c h / 12%);
		border-radius: 8px;
		font-family: var(--font-sans);
		font-size: 11px;
		color: var(--color-text-secondary);
		line-height: 1.55;
	}

	.personality-preview.neutral {
		background: oklch(from var(--color-text-primary) l c h / 2%);
		border-color: var(--color-border);
	}

	.personality-preview :global(svg) {
		flex-shrink: 0;
		margin-top: 1px;
		color: var(--color-accent);
	}

	.personality-preview.neutral :global(svg) {
		color: var(--color-text-secondary);
	}

	/* ===== Providers grid ===== */
	.providers-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 12px;
	}

	.provider-card {
		border: 1px solid var(--color-border);
		border-radius: 12px;
		padding: 16px;
		background: var(--color-bg-secondary);
		transition: border-color 0.2s, box-shadow 0.2s;
	}

	.provider-card:hover {
		border-color: oklch(from var(--color-border) calc(l + 0.05) c h);
	}

	.provider-card.configured {
		border-color: oklch(from var(--color-success) l c h / 25%);
	}

	.provider-header {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 14px;
	}

	.provider-icon-wrap {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		border-radius: 8px;
		background: oklch(from var(--provider-color, #888) l c h / 10%);
		color: var(--provider-color, var(--color-text-secondary));
		flex-shrink: 0;
	}

	.provider-name {
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary);
		flex: 1;
	}

	.provider-badge {
		display: flex;
		align-items: center;
		gap: 3px;
		font-family: var(--font-sans);
		font-size: 10px;
		font-weight: 600;
		color: var(--color-success);
		background: oklch(from var(--color-success) l c h / 10%);
		border-radius: 6px;
		padding: 3px 8px;
	}

	.provider-fields {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.provider-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.provider-field .field-label {
		margin-bottom: 0;
		font-size: 11px;
	}

	/* ===== About section ===== */
	.about-rows {
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.about-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 10px 0;
		border-bottom: 1px solid oklch(from var(--color-text-primary) l c h / 4%);
	}

	.about-row:last-child {
		border-bottom: none;
	}

	.about-label {
		font-family: var(--font-sans);
		font-size: 13px;
		color: var(--color-text-secondary);
	}

	.about-value {
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--color-text-primary);
		font-weight: 500;
	}

	/* ===== Shortcuts grid ===== */
	.shortcuts-grid {
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.shortcut-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 0;
		border-bottom: 1px solid oklch(from var(--color-text-primary) l c h / 4%);
	}

	.shortcut-row:last-child {
		border-bottom: none;
	}

	.shortcut-label {
		font-family: var(--font-sans);
		font-size: 13px;
		color: var(--color-text-secondary);
	}

	.shortcut-row kbd {
		font-family: var(--font-mono);
		font-size: 11px;
		font-weight: 500;
		color: var(--color-text-secondary);
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 5px;
		padding: 3px 8px;
	}

	/* ===== Service Connections ===== */
	.service-connections-section {
		margin-top: 24px;
		padding-top: 24px;
		border-top: 1px solid var(--color-border);
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.service-connections-header {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.service-connections-title-row {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--color-text-primary);
	}

	.add-service-wrap {
		position: relative;
	}

	.btn-add-service {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 7px 14px;
		border: 1px dashed var(--color-border);
		background: transparent;
		border-radius: 8px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: border-color 0.15s, color 0.15s, background 0.15s;
	}

	.btn-add-service:hover {
		border-color: var(--color-accent);
		color: var(--color-accent);
		background: oklch(from var(--color-accent) l c h / 5%);
	}

	.dropdown-backdrop {
		position: fixed;
		inset: 0;
		z-index: 99;
	}

	.add-service-dropdown {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		z-index: 100;
		min-width: 220px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		padding: 6px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
		display: flex;
		flex-direction: column;
		gap: 2px;
		max-height: 320px;
		overflow-y: auto;
	}

	.dropdown-category {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.dropdown-category + .dropdown-category {
		margin-top: 4px;
		padding-top: 4px;
		border-top: 1px solid oklch(from var(--color-text-primary) l c h / 4%);
	}

	.dropdown-category-label {
		font-family: var(--font-sans);
		font-size: 10px;
		font-weight: 600;
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 4px 10px 2px;
		opacity: 0.6;
	}

	.dropdown-item {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 7px 10px;
		border: none;
		background: transparent;
		border-radius: 6px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-primary);
		cursor: pointer;
		text-align: left;
		transition: background 0.1s;
	}

	.dropdown-item:hover {
		background: var(--color-overlay-subtle);
	}

	.dropdown-item-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.empty-services {
		padding: 24px;
		text-align: center;
		border: 1px dashed var(--color-border);
		border-radius: 10px;
	}

	.empty-services-text {
		font-family: var(--font-sans);
		font-size: 12px;
		color: var(--color-text-secondary);
		opacity: 0.6;
	}

	.service-category-group {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.service-category-label {
		font-family: var(--font-sans);
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.service-cards-list {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.service-card {
		border: 1px solid var(--color-border);
		border-radius: 10px;
		background: var(--color-bg-secondary);
		overflow: hidden;
		transition: border-color 0.2s;
	}

	.service-card:hover {
		border-color: oklch(from var(--color-border) calc(l + 0.05) c h);
	}

	.service-card-header {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 12px 14px;
		border-bottom: 1px solid oklch(from var(--color-text-primary) l c h / 3%);
	}

	.service-card-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border-radius: 7px;
		flex-shrink: 0;
	}

	.service-card-label {
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary);
		flex: 1;
	}

	.service-card-type {
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--color-text-secondary);
		background: oklch(from var(--color-text-primary) l c h / 4%);
		border-radius: 4px;
		padding: 2px 6px;
		opacity: 0.7;
	}

	.service-card-actions {
		display: flex;
		gap: 4px;
		flex-shrink: 0;
	}

	.btn-service-action {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border: none;
		background: transparent;
		border-radius: 6px;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.btn-service-action:hover {
		background: var(--color-overlay-subtle);
		color: var(--color-text-primary);
	}

	.btn-service-action:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.btn-service-delete:hover {
		background: oklch(from var(--color-error) l c h / 10%);
		color: var(--color-error);
	}

	.btn-service-action :global(.spinning) {
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		from { transform: rotate(0deg); }
		to { transform: rotate(360deg); }
	}

	.test-result-banner {
		padding: 8px 14px;
		font-family: var(--font-sans);
		font-size: 11px;
		font-weight: 500;
		line-height: 1.4;
	}

	.test-result-banner.test-success {
		background: oklch(from var(--color-success) l c h / 8%);
		color: var(--color-success);
	}

	.test-result-banner.test-error {
		background: oklch(from var(--color-error) l c h / 8%);
		color: var(--color-error);
	}

	.service-card-fields {
		padding: 12px 14px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.service-field-row {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.service-field-row .field-label {
		margin-bottom: 0;
		font-size: 11px;
	}

	/* Toggle switch for SSL */
	.toggle-switch {
		position: relative;
		display: inline-block;
		width: 36px;
		height: 20px;
		cursor: pointer;
	}

	.toggle-switch input {
		opacity: 0;
		width: 0;
		height: 0;
	}

	.toggle-slider {
		position: absolute;
		inset: 0;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		transition: background 0.2s, border-color 0.2s;
	}

	.toggle-slider::before {
		content: '';
		position: absolute;
		left: 2px;
		top: 2px;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: var(--color-text-secondary);
		transition: transform 0.2s, background 0.2s;
	}

	.toggle-switch input:checked + .toggle-slider {
		background: oklch(from var(--color-accent) l c h / 15%);
		border-color: var(--color-accent);
	}

	.toggle-switch input:checked + .toggle-slider::before {
		transform: translateX(16px);
		background: var(--color-accent);
	}

	/* ===== Responsive ===== */
	@media (max-width: 900px) {
		.providers-grid {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 640px) {
		.settings-sidebar {
			width: 60px;
			min-width: 60px;
		}

		.sidebar-item-text {
			display: none;
		}

		.sidebar-badge {
			display: none;
		}

		.sidebar-header span {
			display: none;
		}

		.btn-close-sidebar span,
		.btn-close-sidebar .esc-hint {
			display: none;
		}

		.content-body {
			padding: 16px 20px 32px;
		}

		.fields-grid {
			grid-template-columns: 1fr;
		}

		.providers-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
