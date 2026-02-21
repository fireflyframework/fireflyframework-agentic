import { writable, derived } from 'svelte/store';
import type { StudioSettingsResponse, SaveSettingsPayload, ProviderCredentials, ModelDefaults, UserProfile } from '$lib/types/graph';
import { api } from '$lib/api/client';

export const settingsData = writable<StudioSettingsResponse | null>(null);

/**
 * Derived set of provider IDs that have at least one credential configured.
 */
export const configuredProviders = derived(settingsData, ($data) => {
	const result = new Set<string>();
	if (!$data) return result;

	const c = $data.credentials;
	if (c.openai_api_key) result.add('openai');
	if (c.anthropic_api_key) result.add('anthropic');
	if (c.google_api_key) result.add('google');
	if (c.groq_api_key) result.add('groq');
	if (c.mistral_api_key) result.add('mistral');
	if (c.deepseek_api_key) result.add('deepseek');
	if (c.cohere_api_key) result.add('cohere');
	if (c.azure_openai_api_key) result.add('azure');
	if (c.aws_access_key_id) result.add('bedrock');
	if (c.ollama_base_url) result.add('ollama');

	return result;
});

export async function loadSettings(): Promise<void> {
	try {
		const data = await api.settings.get();
		settingsData.set(data);
	} catch (err) {
		console.warn('[studio] Failed to load settings:', err);
	}
}

export async function saveSettings(
	credentials?: Partial<ProviderCredentials> | null,
	modelDefaults?: Partial<ModelDefaults> | null,
	setupComplete?: boolean | null,
	userProfile?: Partial<UserProfile> | null,
	toolCredentials?: Record<string, string | null> | null
): Promise<void> {
	const payload: SaveSettingsPayload = {};
	if (credentials !== undefined) payload.credentials = credentials;
	if (modelDefaults !== undefined) payload.model_defaults = modelDefaults;
	if (setupComplete !== undefined) payload.setup_complete = setupComplete;
	if (userProfile !== undefined) payload.user_profile = userProfile;
	if (toolCredentials !== undefined && toolCredentials !== null) {
		(payload as Record<string, unknown>).tool_credentials = toolCredentials;
	}

	try {
		const data = await api.settings.save(payload);
		settingsData.set(data);
	} catch (err) {
		console.error('[studio] Failed to save settings:', err);
		throw err;
	}
}
