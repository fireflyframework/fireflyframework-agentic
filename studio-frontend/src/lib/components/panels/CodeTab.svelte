<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { Copy, RefreshCw, Check } from 'lucide-svelte';
	import { nodes, edges } from '$lib/stores/pipeline';
	import { api } from '$lib/api/client';
	import { get } from 'svelte/store';

	let code = $state('');
	let loading = $state(false);
	let error = $state('');
	let copied = $state(false);
	let autoSync = $state(true);
	let debouncing = $state(false);
	let copyTimer: ReturnType<typeof setTimeout> | null = null;
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	let previousGraphKey = $state('');

	/**
	 * Serialize graph for change detection.
	 * Excludes volatile fields like position and _executionState.
	 */
	function serializeGraphForComparison(): string {
		const currentNodes = get(nodes);
		const currentEdges = get(edges);
		const stableNodes = currentNodes.map((n) => ({
			id: n.id,
			type: n.type,
			label: (n.data?.label as string) ?? '',
			model: (n.data?.model as string) ?? '',
			instructions: (n.data?.instructions as string) ?? ''
		}));
		const stableEdges = currentEdges.map((e) => ({
			id: e.id,
			source: e.source,
			target: e.target
		}));
		return JSON.stringify({ nodes: stableNodes, edges: stableEdges });
	}

	/**
	 * Serialize graph for the API call (full data).
	 */
	function serializeGraph() {
		const currentNodes = get(nodes);
		const currentEdges = get(edges);
		const serializedNodes = currentNodes.map((n) => ({
			id: n.id,
			type: n.type,
			label: (n.data?.label as string) ?? '',
			position: n.position,
			data: n.data
		}));
		const serializedEdges = currentEdges.map((e) => ({
			id: e.id,
			source: e.source,
			target: e.target
		}));
		return { nodes: serializedNodes, edges: serializedEdges };
	}

	async function generateCode() {
		loading = true;
		error = '';
		debouncing = false;
		try {
			const graph = serializeGraph();
			const result = await api.codegen.toCode(graph);
			code = result.code;
		} catch (err) {
			error = err instanceof Error ? err.message : 'Code generation failed';
			code = '';
		} finally {
			loading = false;
		}
	}

	async function copyToClipboard() {
		if (!code) return;
		try {
			await navigator.clipboard.writeText(code);
			copied = true;
			if (copyTimer) clearTimeout(copyTimer);
			copyTimer = setTimeout(() => {
				copied = false;
				copyTimer = null;
			}, 2000);
		} catch {
			// Clipboard API not available
		}
	}

	function toggleAutoSync() {
		autoSync = !autoSync;
		if (!autoSync) {
			clearDebounce();
		}
	}

	function clearDebounce() {
		if (debounceTimer) {
			clearTimeout(debounceTimer);
			debounceTimer = null;
		}
		debouncing = false;
	}

	// ── HTML escaping for XSS prevention ──

	function escapeHtml(text: string): string {
		return text
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;');
	}

	// ── Python syntax highlighting ──

	function highlightPython(source: string): string {
		const escaped = escapeHtml(source);

		const result: string[] = [];
		let pos = 0;

		// Combined regex for single-pass tokenization on HTML-escaped text.
		// escapeHtml only produces &amp; &lt; &gt; — quotes remain literal " and '.
		// Group order determines token priority (earlier groups win).
		const combinedRe = new RegExp(
			[
				// 1: Triple double-quoted strings
				'("""[\\s\\S]*?""")',
				// 2: Triple single-quoted strings
				"('''[\\s\\S]*?''')",
				// 3: Comments (# to end of line)
				'(#[^\\n]*)',
				// 4: Double-quoted strings
				'("(?:[^"\\\\\\n]|\\\\.)*")',
				// 5: Single-quoted strings
				"('(?:[^'\\\\\\n]|\\\\.)*')",
				// 6,7,8: def + whitespace + function name
				'\\b(def)(\\s+)(\\w+)',
				// 9,10,11: class + whitespace + class name
				'\\b(class)(\\s+)(\\w+)',
				// 12: Decorators
				'(@\\w+(?:\\.\\w+)*)',
				// 13: Keywords
				'\\b(from|import|return|if|else|elif|for|while|try|except|finally|with|as|async|await|yield|raise|pass|break|continue|and|or|not|in|is|None|True|False)\\b',
				// 14: Built-in functions (followed by open paren)
				'\\b(print|len|range|type|str|int|float|list|dict|set|tuple|isinstance|super)(?=\\s*\\()',
				// 15: Numbers
				'\\b(\\d+\\.?\\d*(?:e[+-]?\\d+)?)\\b',
			].join('|'),
			'g'
		);

		let m: RegExpExecArray | null;
		combinedRe.lastIndex = 0;

		while ((m = combinedRe.exec(escaped)) !== null) {
			// Push text before this match
			if (m.index > pos) {
				result.push(escaped.slice(pos, m.index));
			}

			if (m[1] !== undefined) {
				// Triple double-quoted string
				result.push(`<span class="hl-string">${m[1]}</span>`);
			} else if (m[2] !== undefined) {
				// Triple single-quoted string
				result.push(`<span class="hl-string">${m[2]}</span>`);
			} else if (m[3] !== undefined) {
				// Comment
				result.push(`<span class="hl-comment">${m[3]}</span>`);
			} else if (m[4] !== undefined) {
				// Double-quoted string
				result.push(`<span class="hl-string">${m[4]}</span>`);
			} else if (m[5] !== undefined) {
				// Single-quoted string
				result.push(`<span class="hl-string">${m[5]}</span>`);
			} else if (m[6] !== undefined) {
				// def keyword + space + function name
				result.push(`<span class="hl-keyword">${m[6]}</span>${m[7]}<span class="hl-funcname">${m[8]}</span>`);
			} else if (m[9] !== undefined) {
				// class keyword + space + class name
				result.push(`<span class="hl-keyword">${m[9]}</span>${m[10]}<span class="hl-funcname">${m[11]}</span>`);
			} else if (m[12] !== undefined) {
				// Decorator
				result.push(`<span class="hl-decorator">${m[12]}</span>`);
			} else if (m[13] !== undefined) {
				// Keyword
				result.push(`<span class="hl-keyword">${m[13]}</span>`);
			} else if (m[14] !== undefined) {
				// Built-in function
				result.push(`<span class="hl-builtin">${m[14]}</span>`);
			} else if (m[15] !== undefined) {
				// Number
				result.push(`<span class="hl-number">${m[15]}</span>`);
			} else {
				result.push(m[0]);
			}

			pos = m.index + m[0].length;
		}

		// Push remaining text
		if (pos < escaped.length) {
			result.push(escaped.slice(pos));
		}

		return result.join('');
	}

	// ── Derived highlighted code ──

	let highlightedCode = $derived(code ? highlightPython(code) : '');

	let codeLines = $derived(
		highlightedCode ? highlightedCode.split('\n') : []
	);

	// ── Reactive auto-regeneration via store subscriptions ──

	let unsubNodes: (() => void) | null = null;
	let unsubEdges: (() => void) | null = null;

	function onGraphChange() {
		if (!autoSync) return;

		const currentKey = serializeGraphForComparison();
		if (currentKey === previousGraphKey) return;
		previousGraphKey = currentKey;

		const currentNodes = get(nodes);
		if (currentNodes.length === 0) return;
		if (loading) return;

		clearDebounce();
		debouncing = true;
		debounceTimer = setTimeout(() => {
			debouncing = false;
			debounceTimer = null;
			generateCode();
		}, 800);
	}

	// Generate code on mount if there are nodes in the graph
	onMount(() => {
		previousGraphKey = serializeGraphForComparison();

		if (get(nodes).length > 0) {
			generateCode();
		}

		// Subscribe to store changes for auto-regeneration
		unsubNodes = nodes.subscribe(() => {
			onGraphChange();
		});
		unsubEdges = edges.subscribe(() => {
			onGraphChange();
		});
	});

	onDestroy(() => {
		if (copyTimer) clearTimeout(copyTimer);
		clearDebounce();
		if (unsubNodes) unsubNodes();
		if (unsubEdges) unsubEdges();
	});
</script>

<div class="code-tab">
	<div class="code-toolbar">
		<span class="toolbar-label">
			Generated Python
			{#if debouncing}
				<span class="auto-sync-indicator">Auto-syncing...</span>
			{/if}
		</span>
		<div class="toolbar-actions">
			<button
				class="auto-toggle"
				class:active={autoSync}
				onclick={toggleAutoSync}
				title={autoSync ? 'Disable auto-sync' : 'Enable auto-sync'}
			>
				<span class="auto-toggle-label">Auto</span>
				<span class="auto-toggle-track">
					<span class="auto-toggle-thumb"></span>
				</span>
			</button>
			<button class="toolbar-btn" onclick={copyToClipboard} title="Copy to clipboard" disabled={!code}>
				{#if copied}
					<Check size={13} />
				{:else}
					<Copy size={13} />
				{/if}
			</button>
			<button class="toolbar-btn" class:spinning={loading} onclick={generateCode} title="Regenerate code" disabled={loading}>
				<RefreshCw size={13} />
			</button>
		</div>
	</div>

	<div class="code-content">
		{#if loading}
			<div class="code-state spinning-indicator">
				<span>Generating code...</span>
			</div>
		{:else if error}
			<div class="code-state code-error">
				<span>{error}</span>
			</div>
		{:else if code}
			<div class="code-block-wrapper">
				<table class="code-table" role="presentation">
					<tbody>
						{#each codeLines as line, i}
							<tr class="code-line">
								<td class="line-number">{i + 1}</td>
								<!-- SAFETY: line is HTML-escaped by escapeHtml() before highlightPython() adds trusted <span> tags -->
								<td class="line-content">{@html line}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else}
			<div class="code-state">
				<span>Add nodes to your pipeline to generate code.</span>
			</div>
		{/if}
	</div>
</div>

<style>
	.code-tab {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	.code-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 12px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
		flex-shrink: 0;
	}

	.toolbar-label {
		font-size: 11px;
		color: var(--color-text-secondary, #8888a0);
		font-weight: 500;
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.auto-sync-indicator {
		font-size: 10px;
		color: var(--color-info, #3b82f6);
		font-weight: 400;
		animation: pulse-opacity 1.2s ease-in-out infinite;
	}

	@keyframes pulse-opacity {
		0%, 100% { opacity: 0.6; }
		50% { opacity: 1; }
	}

	.toolbar-actions {
		display: flex;
		gap: 4px;
		align-items: center;
	}

	.toolbar-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 26px;
		height: 26px;
		border: none;
		background: transparent;
		border-radius: 4px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
	}

	.toolbar-btn:hover:not(:disabled) {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-text-primary, #e8e8ed);
	}

	.toolbar-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	/* ── Auto-sync toggle ── */

	.auto-toggle {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 2px 6px;
		border: none;
		background: transparent;
		border-radius: 4px;
		cursor: pointer;
		transition: background 0.15s ease;
	}

	.auto-toggle:hover {
		background: rgba(255, 255, 255, 0.05);
	}

	.auto-toggle-label {
		font-size: 10px;
		font-weight: 500;
		color: var(--color-text-secondary, #8888a0);
		transition: color 0.15s ease;
	}

	.auto-toggle.active .auto-toggle-label {
		color: var(--color-text-primary, #e8e8ed);
	}

	.auto-toggle-track {
		position: relative;
		width: 22px;
		height: 12px;
		background: rgba(255, 255, 255, 0.1);
		border-radius: 6px;
		transition: background 0.2s ease;
	}

	.auto-toggle.active .auto-toggle-track {
		background: var(--color-accent, #ff6b35);
	}

	.auto-toggle-thumb {
		position: absolute;
		top: 2px;
		left: 2px;
		width: 8px;
		height: 8px;
		background: var(--color-text-secondary, #8888a0);
		border-radius: 50%;
		transition: transform 0.2s ease, background 0.2s ease;
	}

	.auto-toggle.active .auto-toggle-thumb {
		transform: translateX(10px);
		background: #fff;
	}

	/* ── Code content ── */

	.code-content {
		flex: 1;
		overflow-y: auto;
		font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
		font-size: 12px;
		line-height: 1.6;
	}

	.code-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100%;
		gap: 8px;
		color: var(--color-text-secondary, #8888a0);
		font-size: 12px;
	}

	.code-error {
		color: var(--color-error, #ef4444);
	}

	.code-block-wrapper {
		padding: 12px 0;
	}

	.code-table {
		border-collapse: collapse;
		width: 100%;
	}

	.code-line {
		line-height: 1.6;
	}

	.line-number {
		user-select: none;
		text-align: right;
		padding: 0 12px 0 12px;
		color: rgba(136, 136, 160, 0.4);
		font-size: 11px;
		min-width: 36px;
		vertical-align: top;
		white-space: nowrap;
	}

	.line-content {
		white-space: pre;
		color: var(--color-text-primary, #e8e8ed);
		tab-size: 4;
		padding-right: 12px;
	}

	/* ── Syntax highlighting colors (One Dark theme) ── */

	.code-content :global(.hl-keyword) {
		color: #c678dd;
	}

	.code-content :global(.hl-string) {
		color: #98c379;
	}

	.code-content :global(.hl-comment) {
		color: #5c6370;
		font-style: italic;
	}

	.code-content :global(.hl-number) {
		color: #d19a66;
	}

	.code-content :global(.hl-decorator) {
		color: #e5c07b;
	}

	.code-content :global(.hl-funcname) {
		color: #61afef;
	}

	.code-content :global(.hl-builtin) {
		color: #56b6c2;
	}

	/* ── Animations ── */

	.spinning :global(svg) {
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		from { transform: rotate(0deg); }
		to { transform: rotate(360deg); }
	}
</style>
