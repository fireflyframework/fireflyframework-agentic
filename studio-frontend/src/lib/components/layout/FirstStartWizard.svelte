<script lang="ts">
	import { firstStartWizardOpen } from '$lib/stores/ui';
	import { saveSettings, loadSettings } from '$lib/stores/settings';
	import { getDefaultModel } from '$lib/data/models';
	import Check from 'lucide-svelte/icons/check';
	import Key from 'lucide-svelte/icons/key';
	import Sparkles from 'lucide-svelte/icons/sparkles';
	import Zap from 'lucide-svelte/icons/zap';
	import User from 'lucide-svelte/icons/user';
	import ModelSelector from '$lib/components/shared/ModelSelector.svelte';
	import logo from '$lib/assets/favicon.svg';

	const PROVIDERS = [
		{ id: 'openai', label: 'OpenAI', description: 'GPT-4.1, o3, o4-mini', fields: [{ key: 'openai_api_key', label: 'API Key', placeholder: 'sk-...' }] },
		{ id: 'anthropic', label: 'Anthropic', description: 'Claude Sonnet, Opus, Haiku', fields: [{ key: 'anthropic_api_key', label: 'API Key', placeholder: 'sk-ant-...' }] },
		{ id: 'google', label: 'Google Gemini', description: 'Gemini 2.5 Pro & Flash', fields: [{ key: 'google_api_key', label: 'API Key', placeholder: 'AIza...' }] },
		{ id: 'groq', label: 'Groq', description: 'Fast Llama & Mixtral', fields: [{ key: 'groq_api_key', label: 'API Key', placeholder: 'gsk_...' }] },
		{ id: 'mistral', label: 'Mistral', description: 'Mistral Large & Codestral', fields: [{ key: 'mistral_api_key', label: 'API Key', placeholder: 'API key' }] },
		{ id: 'deepseek', label: 'DeepSeek', description: 'DeepSeek Chat & Reasoner', fields: [{ key: 'deepseek_api_key', label: 'API Key', placeholder: 'API key' }] },
		{ id: 'cohere', label: 'Cohere', description: 'Command R & R+', fields: [{ key: 'cohere_api_key', label: 'API Key', placeholder: 'API key' }] },
		{ id: 'azure', label: 'Azure OpenAI', description: 'Azure-hosted OpenAI models', fields: [
			{ key: 'azure_openai_api_key', label: 'API Key', placeholder: 'API key' },
			{ key: 'azure_openai_endpoint', label: 'Endpoint URL', placeholder: 'https://your-resource.openai.azure.com/' }
		] },
		{ id: 'bedrock', label: 'Amazon Bedrock', description: 'AWS-hosted foundation models', fields: [
			{ key: 'aws_access_key_id', label: 'Access Key ID', placeholder: 'AKIA...' },
			{ key: 'aws_secret_access_key', label: 'Secret Access Key', placeholder: 'Secret key' },
			{ key: 'aws_default_region', label: 'Region', placeholder: 'us-east-1' }
		] },
		{ id: 'ollama', label: 'Ollama', description: 'Local open-source models', fields: [{ key: 'ollama_base_url', label: 'Base URL', placeholder: 'http://localhost:11434' }] }
	] as const;

	const STEPS = [
		{ label: 'Welcome' },
		{ label: 'Providers' },
		{ label: 'API Keys' },
		{ label: 'Defaults' },
		{ label: 'Profile' },
		{ label: 'Ready' },
	];

	let step = $state(0);
	let selectedProviders = $state<Set<string>>(new Set());
	let credentialValues = $state<Record<string, string>>({});
	let defaultModel = $state('');
	let temperature = $state(0.7);
	let retries = $state(3);
	let saving = $state(false);

	// User profile
	let userName = $state('');
	let userRole = $state('');
	let userContext = $state('');
	// Both agents (The Architect and The Oracle) are built-in, no customization needed

	const TOTAL_STEPS = STEPS.length;

	// Auto-detect the best default model when entering defaults step
	function autoDetectModel(): void {
		if (defaultModel) return;
		const providerOrder = ['anthropic', 'openai', 'google', 'groq', 'mistral', 'deepseek', 'cohere', 'azure', 'bedrock', 'ollama'];
		for (const pid of providerOrder) {
			if (selectedProviders.has(pid)) {
				const model = getDefaultModel(pid);
				if (model) {
					defaultModel = model.id;
					return;
				}
			}
		}
	}

	function toggleProvider(id: string) {
		const next = new Set(selectedProviders);
		if (next.has(id)) {
			next.delete(id);
		} else {
			next.add(id);
		}
		selectedProviders = next;
	}

	function selectedProvidersList() {
		return PROVIDERS.filter((p) => selectedProviders.has(p.id));
	}

	function handleNext() {
		if (step === 1 && selectedProviders.size === 0) return;
		if (step < TOTAL_STEPS - 1) {
			step++;
			if (step === 3) autoDetectModel();
		}
	}

	function handleBack() {
		if (step > 0) step--;
	}

	async function handleFinish() {
		saving = true;
		try {
			const creds: Record<string, string | null> = {};
			for (const [key, val] of Object.entries(credentialValues)) {
				if (val.trim()) creds[key] = val.trim();
			}

			const profile: Record<string, string> = {};
			if (userName.trim()) profile.name = userName.trim();
			if (userRole.trim()) profile.role = userRole.trim();
			if (userContext.trim()) profile.context = userContext.trim();
			profile.assistant_name = 'The Architect';

			await saveSettings(
				Object.keys(creds).length > 0 ? creds : null,
				{ default_model: defaultModel, temperature, retries },
				true,
				Object.keys(profile).length > 0 ? profile : null
			);
			step = TOTAL_STEPS - 1; // Go to Done step
		} catch {
			// Error logged in store
		} finally {
			saving = false;
		}
	}

	async function handleSkip() {
		try {
			await saveSettings(null, null, true);
		} catch {
			// Best-effort
		}
		firstStartWizardOpen.set(false);
	}

	async function handleDone() {
		await loadSettings();
		firstStartWizardOpen.set(false);
	}
</script>

{#if $firstStartWizardOpen}
	<div class="wizard-backdrop">
		<div class="wizard-modal" role="dialog" aria-modal="true" aria-label="Setup Wizard">
			<!-- Progress bar -->
			<div class="wizard-progress">
				{#each STEPS as s, i}
					<div class="wizard-step-indicator" class:active={i === step} class:completed={i < step}>
						<div class="wizard-step-dot">
							{#if i < step}
								<Check size={10} />
							{:else}
								<span class="wizard-step-num">{i + 1}</span>
							{/if}
						</div>
						{#if i < STEPS.length - 1}
							<div class="wizard-step-line" class:filled={i < step}></div>
						{/if}
					</div>
				{/each}
			</div>

			<!-- Content -->
			<div class="wizard-body">
				{#if step === 0}
					<!-- Welcome -->
					<div class="wizard-welcome">
						<img src={logo} alt="Firefly Agentic Studio" class="wizard-logo" />
						<h2 class="wizard-heading">Welcome to Firefly Agentic Studio</h2>
						<p class="wizard-text">
							Build, test, and deploy AI agent pipelines visually.
							We'll help you configure your AI providers in just a few steps.
						</p>
						<div class="wizard-features">
							<div class="wizard-feature">
								<Zap size={16} />
								<span>Visual pipeline builder</span>
							</div>
							<div class="wizard-feature">
								<Sparkles size={16} />
								<span>Multi-provider AI support</span>
							</div>
							<div class="wizard-feature">
								<Key size={16} />
								<span>Local credential storage</span>
							</div>
						</div>
					</div>
				{:else if step === 1}
					<!-- Select providers -->
					<h3 class="wizard-step-title">Choose your AI providers</h3>
					<p class="wizard-text">Select the providers you have API keys for. You can add more later in Settings.</p>
					<div class="wizard-providers-grid">
						{#each PROVIDERS as provider}
							<button
								class="wizard-provider-card"
								class:selected={selectedProviders.has(provider.id)}
								onclick={() => toggleProvider(provider.id)}
							>
								{#if selectedProviders.has(provider.id)}
									<span class="wizard-provider-check"><Check size={10} /></span>
								{/if}
								<span class="wizard-provider-label">{provider.label}</span>
								<span class="wizard-provider-desc">{provider.description}</span>
							</button>
						{/each}
					</div>
					{#if selectedProviders.size === 0}
						<p class="wizard-hint">Select at least one provider to continue</p>
					{/if}
				{:else if step === 2}
					<!-- Enter keys -->
					<h3 class="wizard-step-title">Enter your API keys</h3>
					<p class="wizard-text">
						Credentials are stored locally at <code>~/.firefly-studio/settings.json</code> and never sent to our servers.
					</p>
					<div class="wizard-keys-list">
						{#each selectedProvidersList() as provider}
							<div class="wizard-key-section">
								<span class="wizard-key-provider">{provider.label}</span>
								{#each provider.fields as field}
									<div class="wizard-key-field">
										<label class="wizard-key-label" for="wizard-{field.key}">{field.label}</label>
										<input
											id="wizard-{field.key}"
											type="password"
											class="wizard-key-input"
											placeholder={field.placeholder}
											value={credentialValues[field.key] ?? ''}
											oninput={(e) => { credentialValues[field.key] = (e.target as HTMLInputElement).value; }}
										/>
									</div>
								{/each}
							</div>
						{/each}
					</div>
				{:else if step === 3}
					<!-- Model defaults -->
					<h3 class="wizard-step-title">Configure defaults</h3>
					<p class="wizard-text">Choose the default model for new agent nodes. You can override per-node later.</p>
					<div class="wizard-defaults">
						<div class="wizard-default-card">
							<label class="wizard-key-label">Default Model</label>
							<ModelSelector bind:value={defaultModel} placeholder="Select or type a model..." />
							{#if defaultModel}
								<span class="wizard-model-hint">This will be used for all new agent nodes</span>
							{/if}
						</div>
						<div class="wizard-defaults-row">
							<div class="wizard-default-card wizard-default-half">
								<label class="wizard-key-label" for="wizard-temp">Temperature</label>
								<div class="wizard-range-wrapper">
									<input
										id="wizard-temp"
										type="range"
										class="wizard-range"
										min="0"
										max="2"
										step="0.01"
										bind:value={temperature}
									/>
									<span class="wizard-range-value">{temperature.toFixed(2)}</span>
								</div>
							</div>
							<div class="wizard-default-card wizard-default-half">
								<label class="wizard-key-label" for="wizard-retries">Retries</label>
								<input
									id="wizard-retries"
									type="number"
									class="wizard-key-input"
									min="0"
									max="10"
									bind:value={retries}
								/>
							</div>
						</div>
					</div>
				{:else if step === 4}
					<!-- User profile -->
					<h3 class="wizard-step-title">Personalise your experience</h3>
					<p class="wizard-text">Tell us about yourself so the AI assistant can address you properly and provide contextual help.</p>
					<div class="wizard-defaults">
						<div class="wizard-defaults-row">
							<div class="wizard-default-card wizard-default-half">
								<label class="wizard-key-label" for="wizard-name">Your Name</label>
								<input
									id="wizard-name"
									type="text"
									class="wizard-key-input wizard-text-input"
									placeholder="e.g. Alex Chen"
									bind:value={userName}
								/>
							</div>
							<div class="wizard-default-card wizard-default-half">
								<label class="wizard-key-label" for="wizard-role">Your Role</label>
								<input
									id="wizard-role"
									type="text"
									class="wizard-key-input wizard-text-input"
									placeholder="e.g. ML Engineer, Product Manager"
									bind:value={userRole}
								/>
							</div>
						</div>
						<div class="wizard-default-card">
							<label class="wizard-key-label" for="wizard-context">Additional Context <span class="wizard-optional">(optional)</span></label>
							<textarea
								id="wizard-context"
								class="wizard-textarea"
								placeholder="e.g. Working on a customer support chatbot, focusing on healthcare domain..."
								bind:value={userContext}
								rows="3"
							></textarea>
						</div>
					</div>
				{:else}
					<!-- Done -->
					<div class="wizard-welcome">
						<div class="wizard-done-icon"><Check size={32} /></div>
						<h2 class="wizard-heading">
							{#if userName}
								Welcome, {userName}!
							{:else}
								You're all set!
							{/if}
						</h2>
						<p class="wizard-text">
							Your {selectedProviders.size} provider{selectedProviders.size !== 1 ? 's are' : ' is'} configured
							with <strong>{defaultModel ? defaultModel.split(':')[1] : 'default model'}</strong> as default.
							<strong>The Architect</strong> and <strong>The Oracle</strong> are ready.
							The Architect will build your pipelines, and The Oracle will guide your decisions.
						</p>
						<p class="wizard-text wizard-text-subtle">
							You can change these anytime from the Settings menu.
						</p>
					</div>
				{/if}
			</div>

			<!-- Footer -->
			<div class="wizard-footer">
				{#if step === 0}
					<button class="wizard-btn-skip" onclick={handleSkip}>Skip setup</button>
					<button class="wizard-btn-next" onclick={handleNext}>Get started</button>
				{:else if step === TOTAL_STEPS - 1}
					<div></div>
					<button class="wizard-btn-next wizard-btn-launch" onclick={handleDone}>
						<Sparkles size={14} />
						Open Studio
					</button>
				{:else}
					<div class="wizard-footer-left">
						<button class="wizard-btn-skip" onclick={handleSkip}>Skip</button>
						<button class="wizard-btn-back" onclick={handleBack}>Back</button>
					</div>
					{#if step === 4}
						<button class="wizard-btn-next" onclick={handleFinish} disabled={saving || !defaultModel}>
							{saving ? 'Saving...' : 'Finish Setup'}
						</button>
					{:else}
						<button
							class="wizard-btn-next"
							onclick={handleNext}
							disabled={step === 1 && selectedProviders.size === 0}
						>Next</button>
					{/if}
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.wizard-backdrop {
		position: fixed;
		inset: 0;
		z-index: 10000;
		background: rgba(0, 0, 0, 0.75);
		display: flex;
		align-items: center;
		justify-content: center;
		animation: wizard-backdrop-in 0.2s ease-out;
	}

	@keyframes wizard-backdrop-in {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	.wizard-modal {
		width: 580px;
		max-width: 90vw;
		max-height: 85vh;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 16px;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		box-shadow:
			0 0 0 1px rgba(255, 255, 255, 0.04),
			0 24px 64px rgba(0, 0, 0, 0.7),
			0 0 120px color-mix(in srgb, var(--color-accent) 6%, transparent);
		animation: wizard-slide-in 0.25s ease-out;
	}

	@keyframes wizard-slide-in {
		from { opacity: 0; transform: translateY(16px) scale(0.96); }
		to { opacity: 1; transform: translateY(0) scale(1); }
	}

	/* Progress bar */
	.wizard-progress {
		display: flex;
		align-items: center;
		padding: 20px 32px 0;
	}

	.wizard-step-indicator {
		display: flex;
		align-items: center;
		flex: 1;
	}

	.wizard-step-indicator:last-child {
		flex: 0;
	}

	.wizard-step-dot {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--color-bg-elevated);
		border: 2px solid var(--color-border);
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--color-text-secondary);
		font-size: 11px;
		font-weight: 600;
		flex-shrink: 0;
		transition: all 0.2s ease;
	}

	.wizard-step-num { font-family: var(--font-sans); }

	.wizard-step-indicator.active .wizard-step-dot {
		border-color: var(--color-accent);
		background: color-mix(in srgb, var(--color-accent) 15%, transparent);
		color: var(--color-accent);
	}

	.wizard-step-indicator.completed .wizard-step-dot {
		border-color: var(--color-success);
		background: var(--color-success);
		color: white;
	}

	.wizard-step-line {
		flex: 1;
		height: 2px;
		background: var(--color-border);
		margin: 0 6px;
		transition: background 0.2s;
	}

	.wizard-step-line.filled { background: var(--color-success); }

	.wizard-body {
		flex: 1;
		overflow-y: auto;
		padding: 24px 32px;
	}

	.wizard-welcome {
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		padding: 16px 0;
	}

	.wizard-logo {
		width: 64px;
		height: 64px;
		border-radius: 14px;
		margin-bottom: 20px;
	}

	.wizard-heading {
		font-family: var(--font-sans);
		font-size: 22px;
		font-weight: 700;
		color: var(--color-text-primary);
		margin: 0 0 8px;
	}

	.wizard-text {
		font-family: var(--font-sans);
		font-size: 13px;
		color: var(--color-text-secondary);
		margin: 0 0 16px;
		line-height: 1.6;
	}

	.wizard-text strong { color: var(--color-text-primary); font-weight: 600; }
	.wizard-text-subtle { font-size: 12px; opacity: 0.7; margin-top: -8px; }

	.wizard-text code {
		font-family: var(--font-mono);
		font-size: 11px;
		background: var(--color-bg-elevated);
		padding: 2px 6px;
		border-radius: 4px;
	}

	.wizard-features {
		display: flex;
		gap: 16px;
		margin-top: 8px;
	}

	.wizard-feature {
		display: flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-sans);
		font-size: 12px;
		color: var(--color-text-secondary);
		background: rgba(255, 255, 255, 0.03);
		padding: 8px 14px;
		border-radius: 8px;
		border: 1px solid var(--color-border);
	}

	.wizard-step-title {
		font-family: var(--font-sans);
		font-size: 16px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0 0 4px;
	}

	.wizard-hint {
		font-family: var(--font-sans);
		font-size: 12px;
		color: var(--color-warning);
		margin: 12px 0 0;
		text-align: center;
	}

	.wizard-providers-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 8px;
	}

	.wizard-provider-card {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 4px;
		padding: 16px 12px 14px;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		cursor: pointer;
		transition: border-color 0.15s, background 0.15s, transform 0.1s;
	}

	.wizard-provider-card:hover {
		background: rgba(255, 255, 255, 0.04);
		transform: translateY(-1px);
	}

	.wizard-provider-card.selected {
		border-color: var(--color-accent);
		background: color-mix(in srgb, var(--color-accent) 6%, transparent);
	}

	.wizard-provider-check {
		position: absolute;
		top: 6px;
		right: 6px;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		background: var(--color-accent);
		color: white;
	}

	.wizard-provider-label {
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.wizard-provider-desc {
		font-family: var(--font-sans);
		font-size: 10px;
		color: var(--color-text-secondary);
		opacity: 0.7;
	}

	.wizard-keys-list {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.wizard-key-section {
		border: 1px solid var(--color-border);
		border-radius: 10px;
		padding: 14px 16px;
		background: rgba(255, 255, 255, 0.02);
	}

	.wizard-key-provider {
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.wizard-key-field { margin-top: 10px; }

	.wizard-key-label {
		display: block;
		font-family: var(--font-sans);
		font-size: 11px;
		font-weight: 500;
		color: var(--color-text-secondary);
		margin-bottom: 4px;
	}

	.wizard-key-input {
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

	.wizard-text-input {
		font-family: var(--font-sans);
		font-size: 13px;
	}

	.wizard-key-input:focus { border-color: var(--color-accent); }
	.wizard-key-input::placeholder { color: var(--color-text-secondary); opacity: 0.5; }

	.wizard-defaults {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.wizard-default-card {
		border: 1px solid var(--color-border);
		border-radius: 10px;
		padding: 14px 16px;
		background: rgba(255, 255, 255, 0.02);
	}

	.wizard-defaults-row {
		display: flex;
		gap: 12px;
	}

	.wizard-default-half { flex: 1; }

	.wizard-model-hint {
		display: block;
		font-family: var(--font-sans);
		font-size: 10px;
		color: var(--color-text-secondary);
		margin-top: 6px;
		opacity: 0.7;
	}

	.wizard-optional {
		opacity: 0.5;
		font-weight: 400;
	}

	.wizard-textarea {
		width: 100%;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 8px 10px;
		font-family: var(--font-sans);
		font-size: 13px;
		color: var(--color-text-primary);
		outline: none;
		transition: border-color 0.15s;
		box-sizing: border-box;
		resize: vertical;
		min-height: 60px;
	}

	.wizard-textarea:focus { border-color: var(--color-accent); }
	.wizard-textarea::placeholder { color: var(--color-text-secondary); opacity: 0.5; }

	.wizard-range-wrapper {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.wizard-range {
		flex: 1;
		accent-color: var(--color-accent);
	}

	.wizard-range-value {
		font-family: var(--font-mono);
		font-size: 12px;
		color: var(--color-accent);
		font-weight: 600;
		min-width: 32px;
		text-align: right;
	}

	.wizard-done-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 56px;
		height: 56px;
		border-radius: 50%;
		background: color-mix(in srgb, var(--color-success) 14%, transparent);
		color: var(--color-success);
		margin-bottom: 16px;
	}

	.wizard-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 24px;
		border-top: 1px solid var(--color-border);
	}

	.wizard-footer-left {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.wizard-btn-skip {
		background: transparent;
		border: none;
		padding: 7px 12px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: color 0.15s;
	}

	.wizard-btn-skip:hover { color: var(--color-text-primary); }

	.wizard-btn-back {
		background: transparent;
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 7px 14px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s;
	}

	.wizard-btn-back:hover { background: var(--color-bg-elevated); }

	.wizard-btn-next {
		background: var(--color-accent);
		border: none;
		border-radius: 6px;
		padding: 7px 18px;
		font-family: var(--font-sans);
		font-size: 12px;
		font-weight: 600;
		color: white;
		cursor: pointer;
		transition: opacity 0.15s;
	}

	.wizard-btn-next:hover:not(:disabled) { opacity: 0.9; }
	.wizard-btn-next:disabled { opacity: 0.4; cursor: not-allowed; }

	.wizard-btn-launch {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 20px;
	}
</style>
