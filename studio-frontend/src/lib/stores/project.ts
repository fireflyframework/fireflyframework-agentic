import { writable, get } from 'svelte/store';
import type { ProjectInfo } from '$lib/types/graph';
import { api } from '$lib/api/client';
import { nodes, edges, resetNodeCounter, suppressAutoSave, isDirty } from '$lib/stores/pipeline';
import { PIPELINE_TEMPLATES } from '$lib/data/templates';
import { connectOracle, disconnectOracle, loadInsights } from '$lib/stores/oracle';

const STORAGE_KEY = 'fireflyStudio:selectedProject';

export const currentProject = writable<ProjectInfo | null>(null);
export const projects = writable<ProjectInfo[]>([]);

/**
 * Select a project and persist the choice to localStorage.
 */
export async function selectProject(project: ProjectInfo): Promise<void> {
	currentProject.set(project);
	try {
		localStorage.setItem(STORAGE_KEY, project.name);
	} catch {
		// localStorage may be unavailable (e.g. private browsing quota exceeded)
	}

	// Load saved pipeline for this project (suppress auto-save during load)
	const resume = suppressAutoSave();
	try {
		const graph = await api.projects.loadPipeline(project.name, 'main');
		if (graph && typeof graph === 'object') {
			const g = graph as { nodes?: any[]; edges?: any[] };
			if (g.nodes) nodes.set(g.nodes);
			if (g.edges) edges.set(g.edges);
			resetNodeCounter();
		}
	} catch {
		// No saved pipeline — start with empty canvas
		nodes.set([]);
		edges.set([]);
		resetNodeCounter();
	}
	isDirty.set(false);
	resume();

	// Connect Oracle WebSocket for the new project
	disconnectOracle();
	connectOracle(project.name);
	loadInsights(project.name).catch(() => {});
}

export async function renameProject(oldName: string, newName: string): Promise<void> {
	await api.projects.rename(oldName, newName);
	const current = get(currentProject);
	await initProjects();
	if (current?.name === oldName) {
		const list = get(projects);
		const found = list.find(p => p.name === newName);
		if (found) selectProject(found);
	}
}

export async function updateProjectDescription(name: string, description: string): Promise<void> {
	await api.projects.updateDescription(name, description);
	await initProjects();
}

export async function deleteProject(name: string): Promise<void> {
	await api.projects.delete(name);
	const current = get(currentProject);
	if (current?.name === name) {
		currentProject.set(null);
		nodes.set([]);
		edges.set([]);
		resetNodeCounter();
	}
	await initProjects();
}

export async function deleteAllProjects(): Promise<number> {
	const result = await api.projects.deleteAll();
	currentProject.set(null);
	nodes.set([]);
	edges.set([]);
	resetNodeCounter();
	projects.set([]);
	return result.count;
}

export async function createAndSelectProject(name: string): Promise<ProjectInfo> {
	const created = await api.projects.create(name);
	await initProjects();
	const list = get(projects);
	const found = list.find(p => p.name === name);
	if (found) selectProject(found);
	return created;
}

/**
 * Fetch all projects from the API, select a previously-used or first project,
 * and create a default project when none exist.
 */
export async function initProjects(): Promise<void> {
	try {
		let projectList = await api.projects.list();

		if (projectList.length === 0) {
			projects.set([]);
			return;
		}

		projects.set(projectList);

		// Restore previously-selected project if it still exists
		let selected: ProjectInfo | undefined;
		try {
			const savedName = localStorage.getItem(STORAGE_KEY);
			if (savedName) {
				selected = projectList.find((p) => p.name === savedName);
			}
		} catch {
			// localStorage unavailable — fall through to default selection
		}

		selectProject(selected ?? projectList[0]);
	} catch (err) {
		console.warn('[studio] Failed to initialise projects:', err);
	}
}

export function loadTemplate(templateId: string, defaultModel?: string): void {
	const template = PIPELINE_TEMPLATES.find((t) => t.id === templateId);
	if (!template) return;

	// Apply the user's default model to all agent nodes in the template
	const templateNodes = defaultModel
		? template.nodes.map((n) =>
				n.type === 'agent' ? { ...n, data: { ...n.data, model: defaultModel } } : n
			)
		: template.nodes;

	const resume = suppressAutoSave();
	nodes.set(templateNodes);
	edges.set(template.edges);
	resetNodeCounter(); // Must run AFTER nodes.set so it can scan existing IDs
	isDirty.set(true);
	resume();
}
