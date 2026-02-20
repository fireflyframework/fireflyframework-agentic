<script lang="ts">
	import { settingsModalOpen } from '$lib/stores/ui';
	import { settingsData, loadSettings, saveSettings } from '$lib/stores/settings';
	import Settings from 'lucide-svelte/icons/settings';
	import Check from 'lucide-svelte/icons/check';

	const PROVIDERS = [
		{ id: 'openai', label: 'OpenAI', fields: [{ key: 'openai_api_key', label: 'API Key', placeholder: 'sk-...' }] },
		{ id: 'anthropic', label: 'Anthropic', fields: [{ key: 'anthropic_api_key', label: 'API Key', placeholder: 'sk-ant-...' }] },
		{ id: 'google', label: 'Google Gemini', fields: [{ key: 'google_api_key', label: 'API Key', placeholder: 'AIza...' }] },
		{ id: 'groq', label: 'Groq', fields: [{ key: 'groq_api_key', label: 'API Key', placeholder: 'gsk_...' }] },
		{ id: 'mistral', label: 'Mistral', fields: [{ key: 'mistral_api_key', label: 'API Key', placeholder: 'API key' }] },
		{ id: 'deepseek', label: 'DeepSeek', fields: [{ key: 'deepseek_api_key', label: 'API Key', placeholder: 'API key' }] },
		{ id: 'cohere', label: 'Cohere', fields: [{ key: 'cohere_api_key', label: 'API Key', placeholder: 'API key' }] },
		{ id: 'azure', label: 'Azure OpenAI', fields: [
			{ key: 'azure_openai_api_key', label: 'API Key', placeholder: 'API key' },
			{ key: 'azure_openai_endpoint', label: 'Endpoint URL', placeholder: 'https://your-resource.openai.azure.com/' }
		] },
		{ id: 'bedrock', label: 'Amazon Bedrock', fields: [
			{ key: 'aws_access_key_id', label: 'Access Key ID', placeholder: 'AKIA...' },
			{ key: 'aws_secret_access_key', label: 'Secret Access Key', placeholder: 'Secret key' },
			{ key: 'aws_default_region', label: 'Region', placeholder: 'us-east-1' }
		] },
		{ id: 'ollama', label: 'Ollama', fields: [{ key: 'ollama_base_url', label: 'Base URL', placeholder: 'http://localhost:11434' }] }
	] as const;

	type CredKey = keyof typeof draftCreds;

	let activeTab = $state<'credentials' | 'model'>('credentials');
	let saving = $state(false);

	// Draft state — local copies edited by the user, committed on Save
	let draftCreds = $state<Record<string, string>>({});
	let draftModel = $state('openai:gpt-4o');
	let draftTemperature = $state(0.7);
	let draftRetries = $state(3);

	// Reset drafts when modal opens
	$effect(() => {
		if ($settingsModalOpen && $settingsData) {
			draftCreds = {};
			draftModel = $settingsData.model_defaults.default_model;
			draftTemperature = $settingsData.model_defaults.temperature;
			draftRetries = $settingsData.model_defaults.retries;
			activeTab = 'credentials';
		}
	});

	function isConfigured(fieldKey: string): boolean {
		if (!$settingsData) return false;
		const val = ($settingsData.credentials as Record<string, string | null>)[fieldKey];
		return val !== null && val !== undefined;
	}

	function close() {
		settingsModalOpen.set(false);
	}

	async function handleSave() {
		saving = true;
		try {
			// Only send credential fields the user actually typed
			const creds: Record<string, string | null> = {};
			for (const [key, val] of Object.entries(draftCreds)) {
				if (val.trim()) creds[key] = val.trim();
			}

			await saveSettings(
				Object.keys(creds).length > 0 ? creds : null,
				{ default_model: draftModel, temperature: draftTemperature, retries: draftRetries },
				true
			);
			close();
		} catch {
			// Error is logged in the store
		} finally {
			saving = false;
		}
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) close();
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
	<div class="settings-backdrop" onclick={handleBackdropClick} onkeydown={handleKeydown}>
		<div class="settings-modal" role="dialog" aria-modal="true" aria-label="Settings">
			<!-- Header -->
			<div class="settings-header">
				<div class="settings-title">
					<Settings size={18} />
					<span>Settings</span>
				</div>
				<kbd class="settings-close-hint">ESC</kbd>
			</div>

			<!-- Tabs -->
			<div class="settings-tabs">
				<button
					class="settings-tab"
					class:active={activeTab === 'credentials'}
					onclick={() => activeTab = 'credentials'}
				>Provider Credentials</button>
				<button
					class="settings-tab"
					class:active={activeTab === 'model'}
					onclick={() => activeTab = 'model'}
				>Model Defaults</button>
			</div>

			<!-- Body -->
			<div class="settings-body">
				{#if activeTab === 'credentials'}
					<div class="providers-list">
						{#each PROVIDERS as provider}
							<div class="provider-section">
								<div class="provider-header">
									<span class="provider-name">{provider.label}</span>
									{#if provider.fields.every((f) => isConfigured(f.key))}
										<span class="provider-badge"><Check size={10} /> Configured</span>
									{/if}
								</div>
								{#each provider.fields as field}
									<div class="provider-field">
										<label class="field-label" for="settings-{field.key}">{field.label}</label>
										<input
											id="settings-{field.key}"
											type="password"
											class="field-input"
											placeholder={field.placeholder}
											value={draftCreds[field.key] ?? ''}
											oninput={(e) => { draftCreds[field.key] = (e.target as HTMLInputElement).value; }}
										/>
									</div>
								{/each}
							</div>
						{/each}
					</div>
				{:else}
					<div class="model-defaults">
						<div class="provider-field">
							<label class="field-label" for="settings-default-model">Default Model</label>
							<input
								id="settings-default-model"
								type="text"
								class="field-input"
								placeholder="openai:gpt-4o"
								bind:value={draftModel}
							/>
						</div>
						<div class="provider-field">
							<label class="field-label" for="settings-temperature">
								Temperature: {draftTemperature.toFixed(2)}
							</label>
							<input
								id="settings-temperature"
								type="range"
								class="field-range"
								min="0"
								max="2"
								step="0.01"
								bind:value={draftTemperature}
							/>
						</div>
						<div class="provider-field">
							<label class="field-label" for="settings-retries">Retries</label>
							<input
								id="settings-retries"
								type="number"
								class="field-input"
								min="0"
								max="10"
								bind:value={draftRetries}
							/>
						</div>
					</div>
				{/if}
			</div>

			<!-- Footer -->
			<div class="settings-footer">
				<button class="btn-cancel" onclick={close}>Cancel</button>
				<button class="btn-save" onclick={handleSave} disabled={saving}>
					{saving ? 'Saving...' : 'Save Settings'}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.settings-backdrop {
		position: fixed;
		inset: 0;
		z-index: 9999;
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding-top: 8vh;
		animation: settings-backdrop-in 0.12s ease-out;
	}

	@keyframes settings-backdrop-in {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	.settings-modal {
		width: 600px;
		max-width: 90vw;
		max-height: 80vh;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		box-shadow:
			0 0 0 1px rgba(255, 255, 255, 0.04),
			0 16px 48px rgba(0, 0, 0, 0.6),
			0 0 80px color-mix(in srgb, var(--color-accent) 4%, transparent);
		animation: settings-slide-in 0.15s ease-out;
	}

	@keyframes settings-slide-in {
		from { opacity: 0; transform: translateY(-8px) scale(0.98); }
		to { opacity: 1; transform: translateY(0) scale(1); }
	}

	.settings-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 20px;
		border-bottom: 1px solid var(--color-border);
	}

	.settings-title {
		display: flex;
		align-items: center;
		gap: 10px;
		font-family: var(--font-sans);
		font-size: 15px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.settings-close-hint {
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

	.settings-tabs {
		display: flex;
		border-bottom: 1px solid var(--color-border);
		padding: 0 20px;
	}

	.settings-tab {
		background: transparent;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--color-text-secondary);
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 500;
		padding: 10px 16px;
		cursor: pointer;
		transition: color 0.15s, border-color 0.15s;
	}

	.settings-tab:hover {
		color: var(--color-text-primary);
	}

	.settings-tab.active {
		color: var(--color-accent);
		border-bottom-color: var(--color-accent);
	}

	.settings-body {
		flex: 1;
		overflow-y: auto;
		padding: 16px 20px;
	}

	.providers-list {
		display: flex;
		flex-direction: column;
		gap: 20px;
	}

	.provider-section {
		border: 1px solid var(--color-border);
		border-radius: 8px;
		padding: 14px 16px;
		background: rgba(255, 255, 255, 0.02);
	}

	.provider-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 10px;
	}

	.provider-name {
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.provider-badge {
		display: flex;
		align-items: center;
		gap: 4px;
		font-family: var(--font-sans);
		font-size: 10px;
		font-weight: 600;
		color: var(--color-success);
		background: color-mix(in srgb, var(--color-success) 12%, transparent);
		border-radius: 4px;
		padding: 2px 8px;
	}

	.provider-field {
		margin-top: 8px;
	}

	.field-label {
		display: block;
		font-family: var(--font-sans);
		font-size: 11px;
		font-weight: 500;
		color: var(--color-text-secondary);
		margin-bottom: 4px;
	}

	.field-input {
		width: 100%;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 8px 10px;
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--color-text-primary);
		outline: none;
		transition: border-color 0.15s;
		box-sizing: border-box;
	}

	.field-input:focus {
		border-color: var(--color-accent);
	}

	.field-input::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.5;
	}

	.field-range {
		width: 100%;
		accent-color: var(--color-accent);
	}

	.model-defaults {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.settings-footer {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px;
		border-top: 1px solid var(--color-border);
	}

	.btn-cancel {
		background: transparent;
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 7px 16px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s;
	}

	.btn-cancel:hover {
		background: var(--color-bg-elevated);
	}

	.btn-save {
		background: var(--color-accent);
		border: none;
		border-radius: 6px;
		padding: 7px 16px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 600;
		color: white;
		cursor: pointer;
		transition: opacity 0.15s;
	}

	.btn-save:hover:not(:disabled) {
		opacity: 0.9;
	}

	.btn-save:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
</style>
