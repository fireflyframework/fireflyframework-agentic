<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import '../app.css';
	import '@xyflow/svelte/dist/style.css';
	import favicon from '$lib/assets/favicon.svg';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import { initProjects } from '$lib/stores/project';
	import { api } from '$lib/api/client';
	import { firstStartWizardOpen } from '$lib/stores/ui';
	import { loadSettings } from '$lib/stores/settings';
	import { enableAutoSave } from '$lib/stores/pipeline';
	import { initTheme } from '$lib/stores/theme';
	import { connectExecution, disconnectExecution } from '$lib/execution/bridge';

	let { children } = $props();

	onMount(async () => {
		initTheme();
		await initProjects();
		enableAutoSave();
		connectExecution();

		try {
			const status = await api.settings.status();
			if (status.first_start || !status.setup_complete) {
				firstStartWizardOpen.set(true);
			}
			// Always load settings — even if wizard shows, there may be env-based defaults
			await loadSettings();
		} catch {
			// Settings endpoint unavailable — skip first-start check
		}
	});

	onDestroy(() => disconnectExecution());
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<AppShell>
	{@render children()}
</AppShell>
