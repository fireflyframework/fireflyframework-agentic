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
	SettingsStatus,
	CustomToolDefinition,
	SaveCustomToolPayload
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
			request<{ status: string }>(`/projects/${encodeURIComponent(name)}`, { method: 'DELETE' }),
		rename: (name: string, newName: string) =>
			request<ProjectInfo>(`/projects/${encodeURIComponent(name)}`, {
				method: 'PATCH',
				body: JSON.stringify({ new_name: newName })
			}),
		updateDescription: (name: string, description: string) =>
			request<ProjectInfo>(`/projects/${encodeURIComponent(name)}`, {
				method: 'PATCH',
				body: JSON.stringify({ description })
			}),
		deleteAll: () =>
			request<{ status: string; count: number }>('/projects', { method: 'DELETE' }),
		savePipeline: (project: string, pipeline: string, graph: object) =>
			request<{ status: string }>(`/projects/${encodeURIComponent(project)}/pipelines/${encodeURIComponent(pipeline)}`, {
				method: 'POST',
				body: JSON.stringify({ graph })
			}),
		loadPipeline: (project: string, pipeline: string) =>
			request<object>(`/projects/${encodeURIComponent(project)}/pipelines/${encodeURIComponent(pipeline)}`),
		getHistory: (project: string) =>
			request<Array<{ sha: string; message: string; timestamp: string; bookmarked: boolean }>>(`/projects/${encodeURIComponent(project)}/history`),
		restoreVersion: (project: string, commitSha: string) =>
			request<{ status: string }>(`/projects/${encodeURIComponent(project)}/restore`, {
				method: 'POST',
				body: JSON.stringify({ commit_sha: commitSha })
			}),
		bookmarkVersion: (project: string, commitSha: string, label: string) =>
			request<{ status: string }>(`/projects/${encodeURIComponent(project)}/bookmark`, {
				method: 'POST',
				body: JSON.stringify({ commit_sha: commitSha, label })
			})
	},

	files: {
		list: (project: string) => request<FileEntry[]>(`/projects/${encodeURIComponent(project)}/files`),
		read: (project: string, path: string) => request<FileContent>(`/projects/${encodeURIComponent(project)}/files/${path}`)
	},

	evaluate: {
		uploadDataset: (project: string, file: File) => {
			const formData = new FormData();
			formData.append('file', file);
			return fetch(`${BASE_URL}/projects/${encodeURIComponent(project)}/datasets/upload`, {
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
			request<DatasetInfo[]>(`/projects/${encodeURIComponent(project)}/datasets`),
		run: (project: string, dataset: string, graph: object) =>
			request<EvalRunResult>('/evaluate/run', {
				method: 'POST',
				body: JSON.stringify({ project, dataset, graph })
			})
	},

	experiments: {
		list: (project: string) => request<Experiment[]>(`/projects/${encodeURIComponent(project)}/experiments`),
		create: (project: string, name: string, variants: Array<{ name: string; pipeline: string; traffic: number }>) =>
			request<Experiment>(`/projects/${encodeURIComponent(project)}/experiments`, {
				method: 'POST',
				body: JSON.stringify({ name, variants })
			}),
		get: (project: string, expId: string) =>
			request<Experiment>(`/projects/${encodeURIComponent(project)}/experiments/${expId}`),
		delete: (project: string, expId: string) =>
			request<{ status: string }>(`/projects/${encodeURIComponent(project)}/experiments/${expId}`, { method: 'DELETE' }),
		runVariant: (project: string, expId: string, variantName: string, graph: object, input?: string) =>
			request<{ experiment_id: string; variant_name: string; success: boolean; output: string }>(
				`/projects/${encodeURIComponent(project)}/experiments/${expId}/run`,
				{
					method: 'POST',
					body: JSON.stringify({ variant_name: variantName, graph, input: input ?? '' })
				}
			)
	},

	codegen: {
		smith: (graph: object) =>
			request<{ code: string; notes: string[] }>('/codegen/smith', {
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
		rewind: (index: number) =>
			request<{ status: string; index: number; node_id: string }>(`/checkpoints/${index}/rewind`, {
				method: 'POST'
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
		status: () => request<SettingsStatus>('/settings/status'),
		services: {
			list: () => request<Array<{ id: string; service_type: string; label: string; host: string; port: number | null; username: string; database: string; ssl_enabled: boolean }>>('/settings/services'),
			add: (service: Record<string, unknown>) =>
				request<{ status: string; id: string }>('/settings/services', {
					method: 'POST',
					body: JSON.stringify(service)
				}),
			delete: (id: string) =>
				request<{ status: string }>(`/settings/services/${id}`, { method: 'DELETE' }),
			test: (id: string) =>
				request<{ status: string; message: string }>(`/settings/services/${id}/test`, { method: 'POST' })
		}
	},

	assistant: {
		getHistory: (project: string) =>
			request<Array<{ role: string; content: string; timestamp: string; toolCalls?: unknown[] }>>(`/assistant/${encodeURIComponent(project)}/history`),
		saveHistory: (project: string, messages: Array<{ role: string; content: string; timestamp: string; toolCalls?: unknown[] }>) =>
			request<{ status: string }>(`/assistant/${encodeURIComponent(project)}/history`, {
				method: 'POST',
				body: JSON.stringify({ messages })
			}),
		inferProjectName: (message: string) =>
			request<{ name: string }>('/assistant/infer-project-name', {
				method: 'POST',
				body: JSON.stringify({ message })
			}),
	},

	oracle: {
		getInsights: (project: string) =>
			request<Array<{ id: string; title: string; description: string; severity: string; action_instruction: string | null; timestamp: string; status: string }>>(`/oracle/${encodeURIComponent(project)}/insights`),
		approveInsight: (project: string, insightId: string) =>
			request<{ status: string; action_instruction: string | null }>(`/oracle/${encodeURIComponent(project)}/insights/${insightId}/approve`, { method: 'POST' }),
		skipInsight: (project: string, insightId: string) =>
			request<{ status: string }>(`/oracle/${encodeURIComponent(project)}/insights/${insightId}/skip`, { method: 'POST' }),
	},

	tunnel: {
		status: () => request<{ active: boolean; url: string | null; port: number }>('/tunnel/status'),
		start: () => request<{ url: string; status: string }>('/tunnel/start', { method: 'POST' }),
		stop: () => request<{ status: string }>('/tunnel/stop', { method: 'POST' }),
	},

	runtime: {
		start: (project: string) => request<{ status: string }>(`/projects/${encodeURIComponent(project)}/runtime/start`, { method: 'POST' }),
		stop: (project: string) => request<{ status: string }>(`/projects/${encodeURIComponent(project)}/runtime/stop`, { method: 'POST' }),
		status: (project: string) => request<{ project: string; status: string; trigger_type: string | null; consumers: number; scheduler_active: boolean }>(`/projects/${encodeURIComponent(project)}/runtime/status`),
		executions: (project: string) => request<{ executions: Array<{ execution_id: string; status: string; duration_ms: number | null }> }>(`/projects/${encodeURIComponent(project)}/runtime/executions`),
	},

	customTools: {
		list: () => request<CustomToolDefinition[]>('/custom-tools'),
		get: (name: string) => request<CustomToolDefinition>(`/custom-tools/${name}`),
		save: (tool: SaveCustomToolPayload) =>
			request<CustomToolDefinition>('/custom-tools', {
				method: 'POST',
				body: JSON.stringify(tool)
			}),
		delete: (name: string) =>
			request<{ status: string }>(`/custom-tools/${name}`, { method: 'DELETE' }),
		register: (name: string) =>
			request<{ status: string; tool_name: string }>(`/custom-tools/${name}/register`, {
				method: 'POST'
			}),
		test: (name: string) =>
			request<{ status: string; tool_name: string; response_time?: number; result?: string; error?: string }>(
				`/custom-tools/${name}/test`,
				{ method: 'POST' }
			),
		catalog: () =>
			request<
				Array<{
					id: string;
					name: string;
					category: string;
					description: string;
					icon: string;
					requires_credential: string | null;
					installed: boolean;
					tool_name: string;
					setup_guide: string;
				}>
			>('/custom-tools/catalog'),
		installConnector: (connectorId: string, overrides?: Record<string, string>) =>
			request<{ status: string; tool_name: string }>(`/custom-tools/catalog/${connectorId}/install`, {
				method: 'POST',
				body: JSON.stringify(overrides ?? {})
			}),
		verifyConnector: (connectorId: string) =>
			request<{ status: string; message: string }>(`/custom-tools/catalog/${connectorId}/verify`, {
				method: 'POST'
			})
	}
};
