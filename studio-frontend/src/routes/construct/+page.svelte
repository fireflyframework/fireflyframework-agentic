<script lang="ts">
	import Canvas from '$lib/components/canvas/Canvas.svelte';
	import ComponentPanel from '$lib/components/panels/ComponentPanel.svelte';
	import BottomPanel from '$lib/components/panels/BottomPanel.svelte';
</script>

<div class="construct-page">
	<div class="top-area">
		<Canvas />
		<ComponentPanel />
	</div>
	<BottomPanel />
</div>

<style>
	.construct-page {
		display: flex;
		flex-direction: column;
		height: 100%;
		width: 100%;
	}

	.top-area {
		display: flex;
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}
</style>
