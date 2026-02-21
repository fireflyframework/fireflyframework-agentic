<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { bottomPanelTab, bottomPanelOpen } from '$lib/stores/ui';

	onMount(() => {
		bottomPanelTab.set('evaluate');
		bottomPanelOpen.set(true);
		goto('/construct');
	});
</script>
