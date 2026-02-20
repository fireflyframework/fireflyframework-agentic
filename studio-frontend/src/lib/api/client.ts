import type {
	AgentInfo,
	ToolInfo,
	PatternInfo,
	ProjectInfo,
	FileEntry,
	FileContent,
	DatasetInfo,
	EvalRunResult,
	Experiment,
	UsageSummary,
	Checkpoint,
	StudioSettingsResponse,
	SaveSettingsPayload,
	SettingsStatus
} from '$lib/types/graph';

const BASE_URL = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
	const resp = await fetch(`${BASE_URL}${path}`, {
		headers: { 'Content-Type': 'application/json' },
		...options
	});
	if (!resp.ok) {
		const error = await resp.json().catch(() => ({ detail: resp.statusText }));
		throw new Error(error.detail || resp.statusText);
	}
	return resp.json();
}

export const api = {
	health: () => request<{ status: string; version: string }>('/health'),

	registry: {
		agents: () => request<AgentInfo[]>('/registry/agents'),
		tools: () => request<ToolInfo[]>('/registry/tools'),
		patterns: () => request<PatternInfo[]>('/registry/patterns')
	},

	projects: {
		list: () => request<ProjectInfo[]>('/projects'),
		create: (name: string, description?: string) =>
			request<ProjectInfo>('/projects', {
				method: 'POST',
				body: JSON.stringify({ name, description })
			}),
		delete: (name: string) =>
			request<{ status: string }>(`/projects/${name}`, { method: 'DELETE' }),
		savePipeline: (project: string, pipeline: string, graph: object) =>
			request<{ status: string }>(`/projects/${project}/pipelines/${pipeline}`, {
				method: 'POST',
				body: JSON.stringify({ graph })
			}),
		loadPipeline: (project: string, pipeline: string) =>
			request<object>(`/projects/${project}/pipelines/${pipeline}`)
	},

	files: {
		list: (project: string) => request<FileEntry[]>(`/projects/${project}/files`),
		read: (project: string, path: string) => request<FileContent>(`/projects/${project}/files/${path}`)
	},

	evaluate: {
		uploadDataset: (project: string, file: File) => {
			const formData = new FormData();
			formData.append('file', file);
			return fetch(`${BASE_URL}/projects/${project}/datasets/upload`, {
				method: 'POST',
				body: formData
			}).then(async (resp) => {
				if (!resp.ok) {
					const error = await resp.json().catch(() => ({ detail: resp.statusText }));
					throw new Error(error.detail || resp.statusText);
				}
				return resp.json() as Promise<{ filename: string; test_cases: number; status: string }>;
			});
		},
		listDatasets: (project: string) =>
			request<DatasetInfo[]>(`/projects/${project}/datasets`),
		run: (project: string, dataset: string, graph: object) =>
			request<EvalRunResult>('/evaluate/run', {
				method: 'POST',
				body: JSON.stringify({ project, dataset, graph })
			})
	},

	experiments: {
		list: (project: string) => request<Experiment[]>(`/projects/${project}/experiments`),
		create: (project: string, name: string, variants: Array<{ name: string; pipeline: string; traffic: number }>) =>
			request<Experiment>(`/projects/${project}/experiments`, {
				method: 'POST',
				body: JSON.stringify({ name, variants })
			}),
		get: (project: string, expId: string) =>
			request<Experiment>(`/projects/${project}/experiments/${expId}`),
		delete: (project: string, expId: string) =>
			request<{ status: string }>(`/projects/${project}/experiments/${expId}`, { method: 'DELETE' }),
		runVariant: (project: string, expId: string, variantName: string, graph: object, input?: string) =>
			request<{ experiment_id: string; variant_name: string; success: boolean; output: string }>(
				`/projects/${project}/experiments/${expId}/run`,
				{
					method: 'POST',
					body: JSON.stringify({ variant_name: variantName, graph, input: input ?? '' })
				}
			)
	},

	codegen: {
		toCode: (graph: object) =>
			request<{ code: string }>('/codegen/to-code', {
				method: 'POST',
				body: JSON.stringify({ graph })
			})
	},

	monitoring: {
		usage: () => request<UsageSummary>('/monitoring/usage')
	},

	checkpoints: {
		list: () => request<Checkpoint[]>('/checkpoints'),
		get: (index: number) => request<Checkpoint>(`/checkpoints/${index}`),
		fork: (fromIndex: number, modifiedState: Record<string, unknown>) =>
			request<Checkpoint>('/checkpoints/fork', {
				method: 'POST',
				body: JSON.stringify({ from_index: fromIndex, modified_state: modifiedState })
			}),
		diff: (indexA: number, indexB: number) =>
			request<{ added: string[]; removed: string[]; changed: string[] }>('/checkpoints/diff', {
				method: 'POST',
				body: JSON.stringify({ index_a: indexA, index_b: indexB })
			}),
		clear: () =>
			request<{ status: string }>('/checkpoints', { method: 'DELETE' })
	},

	settings: {
		get: () => request<StudioSettingsResponse>('/settings'),
		save: (payload: SaveSettingsPayload) =>
			request<StudioSettingsResponse>('/settings', {
				method: 'POST',
				body: JSON.stringify(payload)
			}),
		status: () => request<SettingsStatus>('/settings/status')
	}
};
