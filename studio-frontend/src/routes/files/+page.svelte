<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { bottomPanelTab, bottomPanelOpen } from '$lib/stores/ui';

	onMount(() => {
		bottomPanelTab.set('files');
		bottomPanelOpen.set(true);
		goto('/construct');
	});
</script>
