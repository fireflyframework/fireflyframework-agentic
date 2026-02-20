import { writable } from 'svelte/store';
import type { ProjectInfo } from '$lib/types/graph';
import { api } from '$lib/api/client';

const STORAGE_KEY = 'fireflyStudio:selectedProject';

export const currentProject = writable<ProjectInfo | null>(null);
export const projects = writable<ProjectInfo[]>([]);

/**
 * Select a project and persist the choice to localStorage.
 */
export function selectProject(project: ProjectInfo): void {
	currentProject.set(project);
	try {
		localStorage.setItem(STORAGE_KEY, project.name);
	} catch {
		// localStorage may be unavailable (e.g. private browsing quota exceeded)
	}
}

/**
 * Fetch all projects from the API, select a previously-used or first project,
 * and create a default project when none exist.
 */
export async function initProjects(): Promise<void> {
	try {
		let projectList = await api.projects.list();

		if (projectList.length === 0) {
			const created = await api.projects.create('default');
			projectList = [created];
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
