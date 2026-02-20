export type NodeType =
	| 'agent'
	| 'tool'
	| 'reasoning'
	| 'pipeline_step'
	| 'fan_out'
	| 'fan_in'
	| 'condition'
	| 'memory'
	| 'validator'
	| 'custom_code';

export interface GraphNodeData {
	model?: string;
	instructions?: string;
	description?: string;
	label?: string;
	[key: string]: unknown;
}

export interface AgentInfo {
	name: string;
	version: string;
	description: string;
	tags: string[];
}

export interface ToolInfo {
	name: string;
	description: string;
	tags: string[];
	parameter_count: number;
}

export interface PatternInfo {
	name: string;
}

export interface ProjectInfo {
	name: string;
	description: string;
	created_at: string;
}

export interface FileEntry {
	path: string;
	name: string;
	is_dir: boolean;
	size: number;
}

export interface FileContent {
	path: string;
	content: string;
	size: number;
}

export interface DatasetInfo {
	filename: string;
	test_cases: number;
	size: number;
}

export interface EvalTestResult {
	input: string;
	expected_output: string;
	actual_output: string;
	passed: boolean;
	error: string;
}

export interface EvalRunResult {
	dataset: string;
	total: number;
	passed: number;
	failed: number;
	error_count: number;
	pass_rate: number;
	results: EvalTestResult[];
}

export interface ExperimentVariant {
	name: string;
	pipeline: string;
	traffic: number;
}

export interface Experiment {
	id: string;
	name: string;
	status: 'draft' | 'running' | 'completed';
	created_at: string;
	variants: ExperimentVariant[];
}

export interface ExecutionEvent {
	type: 'node_start' | 'node_complete' | 'node_error' | 'node_skip' | 'pipeline_complete';
	node_id?: string;
	pipeline_name?: string;
	latency_ms?: number;
	error?: string;
	success?: boolean;
	duration_ms?: number;
	timestamp: string;
}

export interface Checkpoint {
	index: number;
	node_id: string;
	state: Record<string, unknown>;
	inputs: Record<string, unknown>;
	timestamp: string;
	branch_id?: string;
	parent_index?: number;
}

export interface UsageBreakdown {
	input_tokens: number;
	output_tokens: number;
	total_tokens: number;
	cost_usd: number;
	requests: number;
}

export interface UsageSummary {
	total_input_tokens: number;
	total_output_tokens: number;
	total_tokens: number;
	total_cost_usd: number;
	total_requests: number;
	total_latency_ms: number;
	record_count: number;
	by_agent: Record<string, UsageBreakdown>;
	by_model: Record<string, UsageBreakdown>;
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export interface ProviderCredentials {
	openai_api_key: string | null;
	anthropic_api_key: string | null;
	google_api_key: string | null;
	groq_api_key: string | null;
	mistral_api_key: string | null;
	deepseek_api_key: string | null;
	cohere_api_key: string | null;
	azure_openai_api_key: string | null;
	azure_openai_endpoint: string | null;
	aws_access_key_id: string | null;
	aws_secret_access_key: string | null;
	aws_default_region: string | null;
	ollama_base_url: string | null;
}

export interface ModelDefaults {
	default_model: string;
	temperature: number;
	retries: number;
}

export interface StudioSettingsResponse {
	credentials: ProviderCredentials;
	model_defaults: ModelDefaults;
	setup_complete: boolean;
}

export interface SaveSettingsPayload {
	credentials?: Partial<ProviderCredentials> | null;
	model_defaults?: Partial<ModelDefaults> | null;
	setup_complete?: boolean | null;
}

export interface SettingsStatus {
	first_start: boolean;
	setup_complete: boolean;
}
