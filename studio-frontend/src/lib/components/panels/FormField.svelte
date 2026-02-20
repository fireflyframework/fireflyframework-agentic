<script lang="ts">
	let {
		label,
		type = 'text',
		value = $bindable(''),
		placeholder = '',
		options = [] as string[]
	} = $props();

	const uid = Math.random().toString(36).slice(2, 8);
	let fieldId = $derived(`field-${(label ?? 'input').replace(/\s+/g, '-').toLowerCase()}-${uid}`);
	let listId = $derived(`dl-${(label ?? 'input').replace(/\s+/g, '-').toLowerCase()}-${uid}`);

	function autoResize(event: Event) {
		const el = event.target as HTMLTextAreaElement;
		el.style.height = 'auto';
		el.style.height = el.scrollHeight + 'px';
	}
</script>

<div class="form-field">
	<label class="field-label" for={fieldId}>{label}</label>

	{#if type === 'textarea'}
		<textarea
			id={fieldId}
			class="field-input field-textarea"
			{placeholder}
			bind:value
			oninput={autoResize}
			rows="3"
		></textarea>
	{:else if type === 'number'}
		<input id={fieldId} class="field-input" type="number" {placeholder} bind:value />
	{:else if type === 'select'}
		<select id={fieldId} class="field-input field-select" bind:value>
			{#each options as opt}
				<option value={opt}>{opt}</option>
			{/each}
		</select>
	{:else if type === 'datalist'}
		<input id={fieldId} class="field-input" type="text" {placeholder} bind:value list={listId} />
		<datalist id={listId}>
			{#each options as opt}
				<option value={opt}></option>
			{/each}
		</datalist>
	{:else}
		<input id={fieldId} class="field-input" type="text" {placeholder} bind:value />
	{/if}
</div>

<style>
	.form-field {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.field-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary, #8888a0);
	}

	.field-input {
		background: var(--bg-elevated, #1a1a26);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
		padding: 8px 10px;
		font-size: 12px;
		color: var(--color-text-primary, #e8e8ed);
		font-family: inherit;
		outline: none;
		transition:
			border-color 0.15s ease,
			box-shadow 0.15s ease;
		width: 100%;
		box-sizing: border-box;
	}

	.field-input:focus {
		border-color: var(--color-accent, #ff6b35);
		box-shadow: 0 0 0 2px rgba(255, 107, 53, 0.15);
	}

	.field-input::placeholder {
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.5;
	}

	.field-textarea {
		resize: none;
		min-height: 60px;
		line-height: 1.5;
	}

	.field-select {
		appearance: none;
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238888a0' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: right 10px center;
		padding-right: 28px;
		cursor: pointer;
	}

	.field-select option {
		background: var(--bg-elevated, #1a1a26);
		color: var(--color-text-primary, #e8e8ed);
	}
</style>
