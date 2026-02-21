<script lang="ts">
	import { MODEL_CATALOG, formatContextWindow, type ModelInfo, type ProviderModels } from '$lib/data/models';
	import { configuredProviders } from '$lib/stores/settings';
	import ChevronDown from 'lucide-svelte/icons/chevron-down';
	import Search from 'lucide-svelte/icons/search';

	let {
		value = $bindable(''),
		placeholder = 'Select or type a model...',
		showAllProviders = false
	} = $props();

	let open = $state(false);
	let query = $state('');
	let inputRef = $state<HTMLInputElement | null>(null);
	let wrapperRef = $state<HTMLDivElement | null>(null);
	let dropdownStyle = $state('');

	let displayProviders = $derived.by(() => {
		const configured = $configuredProviders;
		let providers: ProviderModels[];
		if (showAllProviders || configured.size === 0) {
			providers = MODEL_CATALOG;
		} else {
			const primary = MODEL_CATALOG.filter((p) => configured.has(p.provider));
			const secondary = MODEL_CATALOG.filter((p) => !configured.has(p.provider));
			providers = [...primary, ...secondary];
		}

		if (!query.trim()) return providers;

		const q = query.toLowerCase();
		return providers
			.map((p) => ({
				...p,
				models: p.models.filter(
					(m) =>
						m.name.toLowerCase().includes(q) ||
						m.id.toLowerCase().includes(q) ||
						p.label.toLowerCase().includes(q)
				)
			}))
			.filter((p) => p.models.length > 0);
	});

	function selectModel(model: ModelInfo) {
		value = model.id;
		query = '';
		open = false;
	}

	function positionDropdown() {
		if (!wrapperRef) return;
		const rect = wrapperRef.getBoundingClientRect();
		const maxH = Math.min(300, window.innerHeight - rect.bottom - 8);
		dropdownStyle = `position:fixed; top:${rect.bottom + 4}px; left:${rect.left}px; width:${rect.width}px; max-height:${maxH}px;`;
	}

	function handleInputFocus() {
		open = true;
		query = '';
		requestAnimationFrame(positionDropdown);
	}

	function handleInputChange(e: Event) {
		const input = e.target as HTMLInputElement;
		query = input.value;
		value = input.value;
		open = true;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			open = false;
			inputRef?.blur();
		}
	}

	function handleBackdropClick() {
		open = false;
	}

	function getDisplayName(modelId: string): string {
		for (const p of MODEL_CATALOG) {
			const m = p.models.find((m) => m.id === modelId);
			if (m) return m.name;
		}
		return modelId;
	}
</script>

<div class="model-selector" bind:this={wrapperRef}>
	<div class="selector-input-wrapper">
		<input
			bind:this={inputRef}
			type="text"
			class="selector-input"
			value={open ? query : (value ? getDisplayName(value) : '')}
			{placeholder}
			onfocus={handleInputFocus}
			oninput={handleInputChange}
			onkeydown={handleKeydown}
			autocomplete="off"
			spellcheck="false"
		/>
		<button class="selector-chevron" onclick={() => { open = !open; if (open) inputRef?.focus(); }} tabindex={-1}>
			<ChevronDown size={14} />
		</button>
	</div>

	{#if value && !open}
		<div class="selected-model-id">{value}</div>
	{/if}

	{#if open}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="dropdown-backdrop" onclick={handleBackdropClick} onkeydown={() => {}}></div>
		<div class="dropdown" style={dropdownStyle}>
			{#if displayProviders.length === 0}
				<div class="dropdown-empty">No matching models</div>
			{:else}
				{#each displayProviders as provider}
					<div class="dropdown-group">
						<div class="dropdown-group-label">
							{provider.label}
							{#if !$configuredProviders.has(provider.provider) && $configuredProviders.size > 0}
								<span class="unconfigured-badge">Not configured</span>
							{/if}
						</div>
						{#each provider.models as model}
							<button
								class="dropdown-item"
								class:selected={value === model.id}
								onclick={() => selectModel(model)}
							>
								<span class="model-name">{model.name}</span>
								<span class="model-meta">{formatContextWindow(model.contextWindow)} ctx</span>
							</button>
						{/each}
					</div>
				{/each}
			{/if}
			<div class="dropdown-hint">
				<Search size={12} />
				<span>Type any model ID for unlisted models</span>
			</div>
		</div>
	{/if}
</div>

<style>
	.model-selector { position: relative; }

	.selector-input-wrapper {
		display: flex;
		align-items: center;
		background: var(--color-bg-primary);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		transition: border-color 0.15s;
	}

	.selector-input-wrapper:focus-within { border-color: var(--color-accent); }

	.selector-input {
		flex: 1;
		background: transparent;
		border: none;
		outline: none;
		padding: 8px 10px;
		font-family: var(--font-sans);
		font-size: 13px;
		color: var(--color-text-primary);
		min-width: 0;
	}

	.selector-input::placeholder { color: var(--color-text-secondary); opacity: 0.5; }

	.selector-chevron {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		background: none;
		border: none;
		color: var(--color-text-secondary);
		cursor: pointer;
		flex-shrink: 0;
	}

	.selected-model-id {
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--color-text-secondary);
		margin-top: 4px;
		padding-left: 2px;
	}

	.dropdown-backdrop {
		position: fixed;
		inset: 0;
		z-index: 10000;
	}

	.dropdown {
		z-index: 10001;
		background: var(--color-bg-secondary);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
		max-height: 300px;
		overflow-y: auto;
		padding: 4px;
		animation: dropdown-in 0.12s ease-out;
	}

	@keyframes dropdown-in {
		from { opacity: 0; transform: translateY(-4px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.dropdown-empty {
		padding: 16px;
		text-align: center;
		font-size: 12px;
		color: var(--color-text-secondary);
	}

	.dropdown-group { padding: 4px 0; }

	.dropdown-group-label {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 10px 4px;
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary);
	}

	.unconfigured-badge {
		font-size: 9px;
		font-weight: 500;
		text-transform: none;
		letter-spacing: normal;
		color: var(--color-warning);
		opacity: 0.7;
	}

	.dropdown-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: 7px 10px;
		background: transparent;
		border: none;
		border-radius: 6px;
		cursor: pointer;
		text-align: left;
		transition: background 0.1s;
	}

	.dropdown-item:hover { background: var(--color-bg-elevated); }
	.dropdown-item.selected { background: oklch(from var(--color-accent) l c h / 10%); }

	.model-name {
		font-size: 12px;
		font-weight: 500;
		color: var(--color-text-primary);
	}

	.model-meta {
		font-size: 10px;
		font-family: var(--font-mono);
		color: var(--color-text-secondary);
	}

	.dropdown-hint {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 10px;
		border-top: 1px solid var(--color-border);
		margin-top: 4px;
		font-size: 11px;
		color: var(--color-text-secondary);
		opacity: 0.6;
	}
</style>
