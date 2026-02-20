<script lang="ts">
	import { firstStartWizardOpen } from '$lib/stores/ui';
	import { saveSettings } from '$lib/stores/settings';
	import Check from 'lucide-svelte/icons/check';
	import logo from '$lib/assets/favicon.svg';

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

	let step = $state(0);
	let selectedProviders = $state<Set<string>>(new Set(['openai']));
	let credentialValues = $state<Record<string, string>>({});
	let defaultModel = $state('openai:gpt-4o');
	let temperature = $state(0.7);
	let retries = $state(3);
	let saving = $state(false);

	const TOTAL_STEPS = 5;

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
		if (step < TOTAL_STEPS - 1) step++;
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
			await saveSettings(
				Object.keys(creds).length > 0 ? creds : null,
				{ default_model: defaultModel, temperature, retries },
				true
			);
			step = TOTAL_STEPS - 1; // Go to Done step
		} catch {
			// Error logged in store
		} finally {
			saving = false;
		}
	}

	function handleSkip() {
		// Mark setup as complete with defaults
		saveSettings(null, null, true);
		firstStartWizardOpen.set(false);
	}

	function handleDone() {
		firstStartWizardOpen.set(false);
	}
</script>

{#if $firstStartWizardOpen}
	<div class="wizard-backdrop">
		<div class="wizard-modal" role="dialog" aria-modal="true" aria-label="Setup Wizard">
			<!-- Progress dots -->
			<div class="wizard-progress">
				{#each Array(TOTAL_STEPS) as _, i}
					<div class="wizard-dot" class:active={i === step} class:completed={i < step}></div>
				{/each}
			</div>

			<!-- Content -->
			<div class="wizard-body">
				{#if step === 0}
					<!-- Welcome -->
					<div class="wizard-welcome">
						<img src={logo} alt="Firefly Studio" class="wizard-logo" />
						<h2 class="wizard-heading">Welcome to Firefly Studio</h2>
						<p class="wizard-text">Build, test, and deploy AI agent pipelines visually. Let's configure your AI providers to get started.</p>
					</div>
				{:else if step === 1}
					<!-- Select providers -->
					<h3 class="wizard-step-title">Select your providers</h3>
					<p class="wizard-text">Choose which AI providers you want to configure.</p>
					<div class="wizard-providers-grid">
						{#each PROVIDERS as provider}
							<button
								class="wizard-provider-card"
								class:selected={selectedProviders.has(provider.id)}
								onclick={() => toggleProvider(provider.id)}
							>
								{#if selectedProviders.has(provider.id)}
									<span class="wizard-provider-check"><Check size={12} /></span>
								{/if}
								<span class="wizard-provider-label">{provider.label}</span>
							</button>
						{/each}
					</div>
				{:else if step === 2}
					<!-- Enter keys -->
					<h3 class="wizard-step-title">Enter your API keys</h3>
					<p class="wizard-text">Credentials are stored locally at <code>~/.firefly-studio/settings.json</code>.</p>
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
					<p class="wizard-text">Set the default model and parameters for new pipelines.</p>
					<div class="wizard-defaults">
						<div class="wizard-key-field">
							<label class="wizard-key-label" for="wizard-model">Default Model</label>
							<input
								id="wizard-model"
								type="text"
								class="wizard-key-input"
								placeholder="openai:gpt-4o"
								bind:value={defaultModel}
							/>
						</div>
						<div class="wizard-key-field">
							<label class="wizard-key-label" for="wizard-temp">Temperature: {temperature.toFixed(2)}</label>
							<input
								id="wizard-temp"
								type="range"
								class="wizard-range"
								min="0"
								max="2"
								step="0.01"
								bind:value={temperature}
							/>
						</div>
						<div class="wizard-key-field">
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
				{:else}
					<!-- Done -->
					<div class="wizard-welcome">
						<div class="wizard-done-icon"><Check size={32} /></div>
						<h2 class="wizard-heading">You're all set!</h2>
						<p class="wizard-text">Your providers are configured. You can change these anytime in Settings.</p>
					</div>
				{/if}
			</div>

			<!-- Footer -->
			<div class="wizard-footer">
				{#if step === 0}
					<button class="wizard-btn-skip" onclick={handleSkip}>Skip</button>
					<button class="wizard-btn-next" onclick={handleNext}>Let's get started</button>
				{:else if step === TOTAL_STEPS - 1}
					<div></div>
					<button class="wizard-btn-next" onclick={handleDone}>Open Studio</button>
				{:else}
					<div class="wizard-footer-left">
						<button class="wizard-btn-skip" onclick={handleSkip}>Skip</button>
						<button class="wizard-btn-back" onclick={handleBack}>Back</button>
					</div>
					{#if step === 3}
						<button class="wizard-btn-next" onclick={handleFinish} disabled={saving}>
							{saving ? 'Saving...' : 'Finish Setup'}
						</button>
					{:else}
						<button class="wizard-btn-next" onclick={handleNext}>Next</button>
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
		width: 560px;
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
		animation: wizard-slide-in 0.2s ease-out;
	}

	@keyframes wizard-slide-in {
		from { opacity: 0; transform: translateY(16px) scale(0.96); }
		to { opacity: 1; transform: translateY(0) scale(1); }
	}

	.wizard-progress {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		padding: 20px 20px 0;
	}

	.wizard-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--color-border);
		transition: background 0.2s, transform 0.2s;
	}

	.wizard-dot.active {
		background: var(--color-accent);
		transform: scale(1.3);
	}

	.wizard-dot.completed {
		background: var(--color-success);
	}

	.wizard-body {
		flex: 1;
		overflow-y: auto;
		padding: 24px 28px;
	}

	.wizard-welcome {
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		padding: 24px 0;
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
		line-height: 1.5;
	}

	.wizard-text code {
		font-family: var(--font-mono);
		font-size: 11px;
		background: var(--color-bg-elevated);
		padding: 2px 6px;
		border-radius: 4px;
	}

	.wizard-step-title {
		font-family: var(--font-sans);
		font-size: 16px;
		font-weight: 600;
		color: var(--color-text-primary);
		margin: 0 0 4px;
	}

	.wizard-providers-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 8px;
	}

	.wizard-provider-card {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 14px 12px;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		cursor: pointer;
		transition: border-color 0.15s, background 0.15s;
	}

	.wizard-provider-card:hover {
		background: rgba(255, 255, 255, 0.04);
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
		font-weight: 500;
		color: var(--color-text-primary);
	}

	.wizard-keys-list {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.wizard-key-section {
		border: 1px solid var(--color-border);
		border-radius: 8px;
		padding: 12px 14px;
	}

	.wizard-key-provider {
		font-family: var(--font-sans);
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary);
	}

	.wizard-key-field {
		margin-top: 8px;
	}

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

	.wizard-key-input:focus {
		border-color: var(--color-accent);
	}

	.wizard-key-input::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.5;
	}

	.wizard-range {
		width: 100%;
		accent-color: var(--color-accent);
	}

	.wizard-defaults {
		display: flex;
		flex-direction: column;
		gap: 16px;
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
		padding: 14px 20px;
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

	.wizard-btn-skip:hover {
		color: var(--color-text-primary);
	}

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

	.wizard-btn-back:hover {
		background: var(--color-bg-elevated);
	}

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

	.wizard-btn-next:hover:not(:disabled) {
		opacity: 0.9;
	}

	.wizard-btn-next:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
</style>
