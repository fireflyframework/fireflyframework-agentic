<script lang="ts">
	import { onMount } from 'svelte';
	import '../app.css';
	import '@xyflow/svelte/dist/style.css';
	import favicon from '$lib/assets/favicon.svg';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import { initProjects } from '$lib/stores/project';
	import { api } from '$lib/api/client';
	import { firstStartWizardOpen } from '$lib/stores/ui';
	import { loadSettings } from '$lib/stores/settings';

	let { children } = $props();

	onMount(async () => {
		initProjects();

		try {
			const status = await api.settings.status();
			if (status.first_start || !status.setup_complete) {
				firstStartWizardOpen.set(true);
			} else {
				loadSettings();
			}
		} catch {
			// Settings endpoint unavailable — skip first-start check
		}
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<AppShell>
	{@render children()}
</AppShell>
