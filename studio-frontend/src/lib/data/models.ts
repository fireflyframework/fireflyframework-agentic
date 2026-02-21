export interface ModelInfo {
	id: string;
	name: string;
	provider: string;
	contextWindow: number;
	isDefault: boolean;
}

export interface ProviderModels {
	provider: string;
	label: string;
	models: ModelInfo[];
}

export const MODEL_CATALOG: ProviderModels[] = [
	{
		provider: 'openai',
		label: 'OpenAI',
		models: [
			{ id: 'openai:gpt-4.1', name: 'GPT-4.1', provider: 'openai', contextWindow: 1047576, isDefault: true },
			{ id: 'openai:gpt-4.1-mini', name: 'GPT-4.1 Mini', provider: 'openai', contextWindow: 1047576, isDefault: false },
			{ id: 'openai:gpt-4.1-nano', name: 'GPT-4.1 Nano', provider: 'openai', contextWindow: 1047576, isDefault: false },
			{ id: 'openai:gpt-4o', name: 'GPT-4o', provider: 'openai', contextWindow: 128000, isDefault: false },
			{ id: 'openai:gpt-4o-mini', name: 'GPT-4o Mini', provider: 'openai', contextWindow: 128000, isDefault: false },
			{ id: 'openai:o3', name: 'o3', provider: 'openai', contextWindow: 200000, isDefault: false },
			{ id: 'openai:o4-mini', name: 'o4-mini', provider: 'openai', contextWindow: 200000, isDefault: false },
		]
	},
	{
		provider: 'anthropic',
		label: 'Anthropic',
		models: [
			{ id: 'anthropic:claude-sonnet-4-6', name: 'Claude Sonnet 4.6', provider: 'anthropic', contextWindow: 200000, isDefault: true },
			{ id: 'anthropic:claude-opus-4-6', name: 'Claude Opus 4.6', provider: 'anthropic', contextWindow: 200000, isDefault: false },
			{ id: 'anthropic:claude-haiku-4-5', name: 'Claude Haiku 4.5', provider: 'anthropic', contextWindow: 200000, isDefault: false },
		]
	},
	{
		provider: 'google',
		label: 'Google Gemini',
		models: [
			{ id: 'google:gemini-2.5-pro', name: 'Gemini 2.5 Pro', provider: 'google', contextWindow: 1048576, isDefault: true },
			{ id: 'google:gemini-2.5-flash', name: 'Gemini 2.5 Flash', provider: 'google', contextWindow: 1048576, isDefault: false },
			{ id: 'google:gemini-2.0-flash', name: 'Gemini 2.0 Flash', provider: 'google', contextWindow: 1048576, isDefault: false },
		]
	},
	{
		provider: 'groq',
		label: 'Groq',
		models: [
			{ id: 'groq:llama-3.3-70b-versatile', name: 'Llama 3.3 70B', provider: 'groq', contextWindow: 128000, isDefault: true },
			{ id: 'groq:mixtral-8x7b-32768', name: 'Mixtral 8x7B', provider: 'groq', contextWindow: 32768, isDefault: false },
			{ id: 'groq:gemma2-9b-it', name: 'Gemma 2 9B', provider: 'groq', contextWindow: 8192, isDefault: false },
		]
	},
	{
		provider: 'mistral',
		label: 'Mistral',
		models: [
			{ id: 'mistral:mistral-large-latest', name: 'Mistral Large', provider: 'mistral', contextWindow: 128000, isDefault: true },
			{ id: 'mistral:mistral-small-latest', name: 'Mistral Small', provider: 'mistral', contextWindow: 128000, isDefault: false },
			{ id: 'mistral:codestral-latest', name: 'Codestral', provider: 'mistral', contextWindow: 256000, isDefault: false },
		]
	},
	{
		provider: 'deepseek',
		label: 'DeepSeek',
		models: [
			{ id: 'deepseek:deepseek-chat', name: 'DeepSeek Chat', provider: 'deepseek', contextWindow: 64000, isDefault: true },
			{ id: 'deepseek:deepseek-reasoner', name: 'DeepSeek Reasoner', provider: 'deepseek', contextWindow: 64000, isDefault: false },
		]
	},
	{
		provider: 'cohere',
		label: 'Cohere',
		models: [
			{ id: 'cohere:command-r-plus', name: 'Command R+', provider: 'cohere', contextWindow: 128000, isDefault: true },
			{ id: 'cohere:command-r', name: 'Command R', provider: 'cohere', contextWindow: 128000, isDefault: false },
		]
	},
	{
		provider: 'azure',
		label: 'Azure OpenAI',
		models: [
			{ id: 'azure:gpt-4o', name: 'GPT-4o (Azure)', provider: 'azure', contextWindow: 128000, isDefault: true },
			{ id: 'azure:gpt-4o-mini', name: 'GPT-4o Mini (Azure)', provider: 'azure', contextWindow: 128000, isDefault: false },
		]
	},
	{
		provider: 'bedrock',
		label: 'Amazon Bedrock',
		models: [
			{ id: 'bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0', name: 'Claude 3.5 Sonnet (Bedrock)', provider: 'bedrock', contextWindow: 200000, isDefault: true },
			{ id: 'bedrock:anthropic.claude-3-haiku-20240307-v1:0', name: 'Claude 3 Haiku (Bedrock)', provider: 'bedrock', contextWindow: 200000, isDefault: false },
			{ id: 'bedrock:amazon.nova-pro-v1:0', name: 'Amazon Nova Pro', provider: 'bedrock', contextWindow: 300000, isDefault: false },
		]
	},
	{
		provider: 'ollama',
		label: 'Ollama',
		models: [
			{ id: 'ollama:llama3.3', name: 'Llama 3.3', provider: 'ollama', contextWindow: 128000, isDefault: true },
			{ id: 'ollama:mistral', name: 'Mistral', provider: 'ollama', contextWindow: 32768, isDefault: false },
			{ id: 'ollama:codellama', name: 'Code Llama', provider: 'ollama', contextWindow: 16384, isDefault: false },
			{ id: 'ollama:phi4', name: 'Phi-4', provider: 'ollama', contextWindow: 16384, isDefault: false },
		]
	}
];

export function getAllModels(): ModelInfo[] {
	return MODEL_CATALOG.flatMap((p) => p.models);
}

export function getModelsForProviders(providerIds: Set<string>): ProviderModels[] {
	return MODEL_CATALOG.filter((p) => providerIds.has(p.provider));
}

export function getDefaultModel(providerId: string): ModelInfo | undefined {
	const provider = MODEL_CATALOG.find((p) => p.provider === providerId);
	return provider?.models.find((m) => m.isDefault);
}

export function formatContextWindow(tokens: number): string {
	if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
	if (tokens >= 1000) return `${Math.round(tokens / 1000)}K`;
	return String(tokens);
}
