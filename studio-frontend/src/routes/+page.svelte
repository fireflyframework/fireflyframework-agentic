<script lang="ts">
	import { goto } from '$app/navigation';
	import { Plus, Sparkles, ArrowRight, SendHorizonal, Blocks, Users, Database, Brain, Loader, X, FileText, Image, Folder, EllipsisVertical, Pencil, Trash2, Type, Check, Search } from 'lucide-svelte';
	import { loadTemplate, createAndSelectProject, selectProject, renameProject, updateProjectDescription, deleteProject, deleteAllProjects } from '$lib/stores/project';
	import { currentProject, projects } from '$lib/stores/project';
	import { PIPELINE_TEMPLATES, type PipelineTemplate } from '$lib/data/templates';
	import { api } from '$lib/api/client';
	import { architectSidebarOpen, pendingArchitectMessage } from '$lib/stores/ui';
	import { settingsData } from '$lib/stores/settings';

	let promptText = $state('');
	let sending = $state(false);
	let searchQuery = $state('');
	let fileInputEl: HTMLInputElement | undefined = $state(undefined);

	const userName = $derived($settingsData?.user_profile?.name || '');

	interface PromptAttachment {
		id: string;
		name: string;
		size: number;
		category: 'image' | 'document' | 'text' | 'other';
		file: File;
	}

	let attachments: PromptAttachment[] = $state([]);

	// Project management state
	let menuOpenFor: string | null = $state(null);
	let renamingProject: string | null = $state(null);
	let renameValue = $state('');
	let editingDescProject: string | null = $state(null);
	let descValue = $state('');
	let deletingProject: string | null = $state(null);
	let showDeleteAll = $state(false);

	function clearProjectActions() {
		menuOpenFor = null;
		renamingProject = null;
		editingDescProject = null;
		deletingProject = null;
		showDeleteAll = false;
	}

	function startRename(name: string, e: Event) {
		e.stopPropagation();
		menuOpenFor = null;
		renamingProject = name;
		renameValue = name;
	}

	let renameInFlight = false;
	async function confirmRename(oldName: string, e?: Event) {
		e?.stopPropagation();
		if (renameInFlight) return;
		if (renamingProject === null) return; // already handled (blur after Enter)
		const newName = renameValue.trim();
		if (!newName || newName === oldName) {
			renamingProject = null;
			return;
		}
		renameInFlight = true;
		try {
			await renameProject(oldName, newName);
		} catch (err) {
			console.error('[home] Rename failed:', err);
		}
		renamingProject = null;
		renameInFlight = false;
	}

	function startEditDesc(name: string, currentDesc: string, e: Event) {
		e.stopPropagation();
		menuOpenFor = null;
		editingDescProject = name;
		descValue = currentDesc || '';
	}

	let descInFlight = false;
	async function confirmDesc(name: string, e?: Event) {
		e?.stopPropagation();
		if (descInFlight) return;
		if (editingDescProject === null) return; // already handled (blur after Enter)
		descInFlight = true;
		try {
			await updateProjectDescription(name, descValue.trim());
		} catch (err) {
			console.error('[home] Update description failed:', err);
		}
		editingDescProject = null;
		descInFlight = false;
	}

	function startDelete(name: string, e: Event) {
		e.stopPropagation();
		menuOpenFor = null;
		deletingProject = name;
	}

	async function confirmDelete(name: string, e?: Event) {
		e?.stopPropagation();
		try {
			await deleteProject(name);
		} catch (err) {
			console.error('[home] Delete failed:', err);
		}
		deletingProject = null;
	}

	async function confirmDeleteAll() {
		try {
			await deleteAllProjects();
		} catch (err) {
			console.error('[home] Delete all failed:', err);
		}
		showDeleteAll = false;
	}

	function toggleMenu(name: string, e: Event) {
		e.stopPropagation();
		menuOpenFor = menuOpenFor === name ? null : name;
		// Clear other states
		renamingProject = null;
		editingDescProject = null;
		deletingProject = null;
	}

	function formatFileSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function detectCategory(file: File): PromptAttachment['category'] {
		if (file.type.startsWith('image/')) return 'image';
		if (file.type.includes('pdf') || file.type.includes('word') || file.type.includes('document')) return 'document';
		if (file.type.startsWith('text/') || file.type.includes('json') || file.type.includes('javascript') || file.type.includes('yaml') || file.type.includes('xml')) return 'text';
		const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
		if (['py','js','ts','jsx','tsx','json','md','txt','csv','yaml','yml','xml','html','css','sql','sh','go','rs','java','rb','r'].includes(ext)) return 'text';
		if (['png','jpg','jpeg','gif','webp','svg','bmp'].includes(ext)) return 'image';
		if (['pdf','doc','docx','odt','rtf'].includes(ext)) return 'document';
		return 'other';
	}

	function handleFileSelect(event: Event): void {
		const input = event.target as HTMLInputElement;
		if (input.files && input.files.length > 0) {
			for (const file of Array.from(input.files)) {
				if (file.size > 20 * 1024 * 1024) continue;
				attachments = [...attachments, {
					id: `att-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
					name: file.name,
					size: file.size,
					category: detectCategory(file),
					file,
				}];
			}
			input.value = '';
		}
	}

	function readFileAsBase64(file: File): Promise<string> {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => {
				const result = reader.result as string;
				const base64 = result.includes(',') ? result.split(',')[1] : result;
				resolve(base64);
			};
			reader.onerror = reject;
			reader.readAsDataURL(file);
		});
	}

	function removeAttachment(id: string): void {
		attachments = attachments.filter(a => a.id !== id);
	}

	function openFilePicker(): void {
		fileInputEl?.click();
	}

	const allProjects = $derived(
		($projects ?? [])
			.slice()
			.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
	);

	const filteredProjects = $derived(
		(() => {
			const q = searchQuery.trim().toLowerCase();
			if (!q) return allProjects;
			return allProjects.filter(p =>
				p.name.toLowerCase().includes(q) ||
				(p.description && p.description.toLowerCase().includes(q))
			);
		})()
	);

	const hasProjects = $derived(allProjects.length > 0);

	function formatDate(iso: string): string {
		try {
			const d = new Date(iso);
			return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
		} catch {
			return '';
		}
	}

	function getTemplateIcon(id: string) {
		switch (id) {
			case 'blank': return Plus;
			case 'simple-qa': return Blocks;
			case 'reasoning-pipeline': return Brain;
			case 'multi-agent': return Users;
			case 'rag-pipeline': return Database;
			case 'content-pipeline': return Sparkles;
			case 'data-processing': return Blocks;
			case 'parallel-analysis': return Users;
			default: return Sparkles;
		}
	}

	const templateCards = $derived(
		PIPELINE_TEMPLATES.map(t => ({
			id: t.id,
			name: t.name,
			description: t.description,
			icon: getTemplateIcon(t.id),
			architectPrompt: t.architectPrompt,
		}))
	);

	async function handleSend() {
		const message = promptText.trim();
		if (!message || sending) return;

		sending = true;
		try {
			const encodedAttachments = await Promise.all(
				attachments.map(async (a) => ({
					name: a.file.name,
					size: a.file.size,
					category: a.category,
					type: a.file.type || 'application/octet-stream',
					data: await readFileAsBase64(a.file),
					docType: 'auto',
				}))
			);

			pendingArchitectMessage.set({
				text: message,
				attachments: encodedAttachments.length > 0 ? encodedAttachments : undefined,
			});

			const { name } = await api.assistant.inferProjectName(message);
			await createAndSelectProject(name);
			architectSidebarOpen.set(true);
			goto('/construct');
		} catch (err) {
			console.error('[home] Failed to create project from prompt:', err);
			pendingArchitectMessage.set({ text: message });
			const fallbackName = `project-${Date.now()}`;
			await createAndSelectProject(fallbackName);
			architectSidebarOpen.set(true);
			goto('/construct');
		} finally {
			sending = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSend();
		}
	}

	async function handleTemplateClick(card: typeof templateCards[number]) {
		const projectName = card.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
		await createAndSelectProject(projectName || 'untitled');

		if (card.architectPrompt) {
			// Route through The Architect for dynamic generation
			pendingArchitectMessage.set({ text: card.architectPrompt });
			architectSidebarOpen.set(true);
		} else {
			// Static template (e.g. blank canvas)
			loadTemplate(card.id);
		}
		goto('/construct');
	}

	async function handleProjectClick(project: typeof $projects extends (infer T)[] ? T : never, e: Event) {
		// Don't navigate if any inline action (rename, description edit, menu) is active
		if (renamingProject || editingDescProject || menuOpenFor || deletingProject) {
			e.stopPropagation();
			return;
		}
		selectProject(project);
		goto('/construct');
	}
</script>

<div class="home-page">
	<!-- Background effects -->
	<div class="bg-effects" aria-hidden="true">
		<div class="bg-orb bg-orb-1"></div>
		<div class="bg-orb bg-orb-2"></div>
		<div class="bg-orb bg-orb-3"></div>
		<div class="bg-grid"></div>
		<div class="bg-vignette"></div>
	</div>

	<!-- Page content -->
	<div class="page-content">
		<!-- Hero -->
		<section class="hero-section">
			<h1 class="hero-title">
				{#if userName}
					What do you want to build, {userName}?
				{:else}
					What do you want to build?
				{/if}
			</h1>
			<p class="hero-subtitle">Describe your AI agent pipeline and The Architect will design it for you</p>
		</section>

		<!-- Prompt box — full width like Lovable -->
		<section class="prompt-section">
			<div class="prompt-box" class:disabled={sending}>
				<textarea
					class="prompt-input"
					placeholder="Describe the AI agent pipeline you want to create..."
					bind:value={promptText}
					onkeydown={handleKeydown}
					disabled={sending}
					rows="3"
				></textarea>
				{#if attachments.length > 0}
					<div class="attachment-chips">
						{#each attachments as att (att.id)}
							<div class="attachment-chip">
								<span class="chip-icon">
									{#if att.category === 'image'}
										<Image size={12} />
									{:else}
										<FileText size={12} />
									{/if}
								</span>
								<span class="chip-name" title={att.name}>{att.name}</span>
								<span class="chip-size">{formatFileSize(att.size)}</span>
								<button class="chip-remove" onclick={() => removeAttachment(att.id)} title="Remove">
									<X size={10} />
								</button>
							</div>
						{/each}
					</div>
				{/if}
				<div class="prompt-toolbar">
					<div class="toolbar-left">
						<button
							class="toolbar-btn"
							title="Attach files"
							disabled={sending}
							onclick={openFilePicker}
						>
							<Plus size={16} />
						</button>
						<input
							type="file"
							multiple
							accept=".py,.js,.ts,.jsx,.tsx,.json,.md,.txt,.csv,.yaml,.yml,.xml,.html,.css,.sql,.sh,.pdf,.doc,.docx,.png,.jpg,.jpeg,.gif,.webp,.svg"
							bind:this={fileInputEl}
							onchange={handleFileSelect}
							style="display:none"
						/>
					</div>
					<div class="toolbar-right">
						<button
							class="send-btn"
							onclick={handleSend}
							disabled={sending || !promptText.trim()}
							title="Send to The Architect"
						>
							{#if sending}
								<Loader size={16} class="spinner-icon" />
							{:else}
								<SendHorizonal size={16} />
							{/if}
						</button>
					</div>
				</div>
			</div>
			{#if sending}
				<p class="sending-hint">Creating your project...</p>
			{/if}
		</section>

		<!-- Templates -->
		<section class="templates-section">
			<div class="section-label">
				<Sparkles size={13} />
				<span>Or start from a template</span>
			</div>
			<div class="templates-row">
				{#each templateCards as card (card.id)}
					<button class="template-card" onclick={() => handleTemplateClick(card)}>
						<div class="template-icon">
							{#if card.icon === Plus}
								<Plus size={18} />
							{:else if card.icon === Blocks}
								<Blocks size={18} />
							{:else if card.icon === Brain}
								<Brain size={18} />
							{:else if card.icon === Users}
								<Users size={18} />
							{:else if card.icon === Database}
								<Database size={18} />
							{:else}
								<Sparkles size={18} />
							{/if}
						</div>
						<div class="template-info">
							<span class="template-name">{card.name}</span>
							<span class="template-desc">{card.description}</span>
						</div>
						<div class="template-arrow">
							<ArrowRight size={14} />
						</div>
					</button>
				{/each}
			</div>
		</section>

		<!-- Your projects -->
		{#if hasProjects}
			<section class="projects-section">
				<div class="section-header">
					<div class="section-label">
						<span>Your projects</span>
					</div>
					{#if allProjects.length > 1}
						{#if showDeleteAll}
							<div class="delete-all-confirm">
								<span class="delete-all-text">Delete all {allProjects.length} projects?</span>
								<button class="confirm-btn danger" onclick={() => confirmDeleteAll()}>Delete</button>
								<button class="confirm-btn cancel" onclick={() => showDeleteAll = false}>Cancel</button>
							</div>
						{:else}
							<button class="clear-all-btn" onclick={() => { showDeleteAll = true; menuOpenFor = null; }}>Clear all</button>
						{/if}
					{/if}
				</div>

				{#if allProjects.length > 3}
					<div class="search-bar">
						<Search size={14} />
						<input class="search-input" placeholder="Search projects..." bind:value={searchQuery} />
						{#if searchQuery}
							<button class="search-clear" onclick={() => searchQuery = ''}><X size={12} /></button>
						{/if}
					</div>
				{/if}

				<div class="projects-grid">
					{#each filteredProjects as project (project.name)}
						{#if deletingProject === project.name}
							<div class="project-card deleting">
								<div class="delete-confirm-content">
									<span class="delete-confirm-text">Delete "{project.name}"?</span>
									<div class="delete-confirm-actions">
										<button class="confirm-btn danger" onclick={(e) => confirmDelete(project.name, e)}>Delete</button>
										<button class="confirm-btn cancel" onclick={(e) => { e.stopPropagation(); deletingProject = null; }}>Cancel</button>
									</div>
								</div>
							</div>
						{:else}
							<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
							<div class="project-card" class:menu-active={menuOpenFor === project.name} onclick={(e) => handleProjectClick(project, e)}>
								<div class="project-icon">
									<Folder size={18} />
								</div>
								<div class="project-info">
									{#if renamingProject === project.name}
										<!-- svelte-ignore a11y_autofocus -->
										<input
											class="rename-input"
											type="text"
											bind:value={renameValue}
											autofocus
											onclick={(e) => e.stopPropagation()}
											onkeydown={(e) => {
												e.stopPropagation();
												if (e.key === 'Enter') { e.preventDefault(); confirmRename(project.name, e); }
												if (e.key === 'Escape') { renamingProject = null; }
											}}
											onblur={(e) => confirmRename(project.name, e)}
										/>
									{:else}
										<span class="project-name">{project.name}</span>
									{/if}
									{#if editingDescProject === project.name}
										<!-- svelte-ignore a11y_autofocus -->
										<input
											class="desc-input"
											type="text"
											placeholder="Add a description..."
											bind:value={descValue}
											autofocus
											onclick={(e) => e.stopPropagation()}
											onkeydown={(e) => {
												e.stopPropagation();
												if (e.key === 'Enter') { e.preventDefault(); confirmDesc(project.name, e); }
												if (e.key === 'Escape') { editingDescProject = null; }
											}}
											onblur={(e) => confirmDesc(project.name, e)}
										/>
									{:else if project.description}
										<span class="project-desc">{project.description}</span>
									{:else}
										<span class="project-date">{formatDate(project.created_at)}</span>
									{/if}
								</div>
								<div class="project-arrow">
									<ArrowRight size={14} />
								</div>

								<!-- 3-dot menu button -->
								<button
									class="card-menu-btn"
									title="Project actions"
									onclick={(e) => toggleMenu(project.name, e)}
								>
									<EllipsisVertical size={14} />
								</button>

								<!-- Dropdown menu -->
								{#if menuOpenFor === project.name}
									<div class="card-menu" onclick={(e) => e.stopPropagation()}>
										<button class="menu-item" onclick={(e) => startRename(project.name, e)}>
											<Pencil size={12} />
											<span>Rename</span>
										</button>
										<button class="menu-item" onclick={(e) => startEditDesc(project.name, project.description, e)}>
											<Type size={12} />
											<span>Description</span>
										</button>
										<div class="menu-divider"></div>
										<button class="menu-item danger" onclick={(e) => startDelete(project.name, e)}>
											<Trash2 size={12} />
											<span>Delete</span>
										</button>
									</div>
								{/if}
							</div>
						{/if}
					{/each}
				</div>

				{#if searchQuery && filteredProjects.length === 0}
					<p class="no-results">No projects matching "{searchQuery}"</p>
				{/if}
			</section>
		{/if}

		<!-- Click-outside to close dropdown menu (rename/desc use blur handlers) -->
		{#if menuOpenFor}
			<button class="backdrop" onclick={clearProjectActions} aria-label="Close menu"></button>
		{/if}
	</div>
</div>

<style>
	/* ===== Page container ===== */
	.home-page {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		min-height: 100%;
		overflow-x: hidden;
		overflow-y: auto;
		background: var(--color-bg-primary);
	}

	/* ===== Background effects ===== */
	.bg-effects {
		position: fixed;
		inset: 0;
		pointer-events: none;
		z-index: 0;
		overflow: hidden;
	}

	.bg-orb {
		position: absolute;
		border-radius: 50%;
		filter: blur(120px);
		will-change: transform, opacity;
	}

	.bg-orb-1 {
		width: 700px;
		height: 700px;
		top: -15%;
		left: -10%;
		background: radial-gradient(circle, var(--color-accent) 0%, transparent 60%);
		opacity: 0.14;
		animation: orb-drift-1 22s ease-in-out infinite;
	}

	.bg-orb-2 {
		width: 550px;
		height: 550px;
		bottom: -12%;
		right: -8%;
		background: radial-gradient(circle, oklch(from var(--color-accent) calc(l + 0.1) c h) 0%, transparent 60%);
		opacity: 0.10;
		animation: orb-drift-2 28s ease-in-out infinite;
	}

	.bg-orb-3 {
		width: 400px;
		height: 400px;
		top: 35%;
		right: 15%;
		background: radial-gradient(circle, var(--color-accent) 0%, transparent 60%);
		opacity: 0.06;
		animation: orb-drift-3 18s ease-in-out infinite;
	}

	@keyframes orb-drift-1 {
		0%, 100% { transform: translate(0, 0) scale(1); }
		33% { transform: translate(60px, 40px) scale(1.1); }
		66% { transform: translate(-30px, 20px) scale(0.95); }
	}

	@keyframes orb-drift-2 {
		0%, 100% { transform: translate(0, 0) scale(1); }
		33% { transform: translate(-50px, -30px) scale(1.05); }
		66% { transform: translate(40px, -50px) scale(0.9); }
	}

	@keyframes orb-drift-3 {
		0%, 100% { transform: translate(0, 0) scale(1); opacity: 0.04; }
		50% { transform: translate(-40px, 30px) scale(1.15); opacity: 0.08; }
	}

	.bg-grid {
		position: absolute;
		inset: 0;
		background-image:
			linear-gradient(to right, var(--color-grid-line) 1px, transparent 1px),
			linear-gradient(to bottom, var(--color-grid-line) 1px, transparent 1px);
		background-size: 48px 48px;
		mask-image: radial-gradient(ellipse 100% 90% at 50% 35%, black 10%, transparent 80%);
		-webkit-mask-image: radial-gradient(ellipse 100% 90% at 50% 35%, black 10%, transparent 80%);
		animation: grid-fade-in 1.2s ease-out;
	}

	@keyframes grid-fade-in {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	.bg-vignette {
		position: absolute;
		inset: 0;
		background: radial-gradient(ellipse 80% 80% at 50% 50%, transparent 30%, var(--color-vignette) 100%);
	}

	/* ===== Page content ===== */
	.page-content {
		position: relative;
		z-index: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		width: 100%;
		max-width: 860px;
		padding: 0 32px;
		padding-bottom: 48px;
	}

	/* ===== Hero section ===== */
	.hero-section {
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		gap: 12px;
		padding-top: clamp(56px, 12vh, 120px);
		padding-bottom: 8px;
	}

	.hero-title {
		font-size: 30px;
		font-weight: 700;
		color: var(--color-text-primary);
		margin: 0;
		letter-spacing: -0.02em;
		font-family: var(--font-sans);
		line-height: 1.2;
	}

	.hero-subtitle {
		font-size: 14px;
		color: var(--color-text-secondary);
		margin: 0;
		font-family: var(--font-sans);
		max-width: 420px;
		line-height: 1.5;
		opacity: 0.8;
	}

	/* ===== Prompt section ===== */
	.prompt-section {
		width: 100%;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		margin-top: 28px;
	}

	.prompt-box {
		display: flex;
		flex-direction: column;
		width: 100%;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 16px;
		overflow: hidden;
		transition: border-color 0.2s, box-shadow 0.2s;
	}

	.prompt-box:focus-within {
		border-color: oklch(from var(--color-accent) l c h / 50%);
		box-shadow:
			0 0 0 3px oklch(from var(--color-accent) l c h / 6%),
			0 8px 32px -8px oklch(from var(--color-accent) l c h / 10%);
	}

	.prompt-box.disabled {
		opacity: 0.55;
		pointer-events: none;
	}

	.prompt-input {
		width: 100%;
		background: none;
		border: none;
		outline: none;
		color: var(--color-text-primary);
		font-size: 15px;
		font-family: var(--font-sans);
		line-height: 1.55;
		padding: 18px 20px 8px;
		resize: none;
		min-height: 60px;
		max-height: 180px;
	}

	.prompt-input::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.5;
	}

	.prompt-input:disabled {
		opacity: 0.5;
	}

	/* Attachment chips */
	.attachment-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		padding: 4px 18px 0;
	}

	.attachment-chip {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 4px 10px;
		background: oklch(from var(--color-accent) l c h / 8%);
		border: 1px solid oklch(from var(--color-accent) l c h / 18%);
		border-radius: 8px;
		font-size: 11px;
		font-family: var(--font-sans);
		max-width: 220px;
	}

	.chip-icon {
		display: flex;
		color: var(--color-accent);
		flex-shrink: 0;
	}

	.chip-name {
		color: var(--color-text-primary);
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.chip-size {
		color: var(--color-text-secondary);
		opacity: 0.7;
		flex-shrink: 0;
	}

	.chip-remove {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		border-radius: 50%;
		border: none;
		background: transparent;
		color: var(--color-text-secondary);
		cursor: pointer;
		flex-shrink: 0;
		transition: background 0.15s, color 0.15s;
	}

	.chip-remove:hover {
		background: var(--color-overlay-medium);
		color: var(--color-text-primary);
	}

	/* Prompt toolbar */
	.prompt-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 12px;
	}

	.toolbar-left {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.toolbar-right {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.toolbar-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border-radius: 8px;
		border: none;
		background: transparent;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: all 0.15s;
	}

	.toolbar-btn:hover:not(:disabled) {
		background: var(--color-overlay-subtle);
		color: var(--color-text-primary);
	}

	.toolbar-btn:disabled {
		opacity: 0.35;
		cursor: default;
	}

	.send-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 34px;
		height: 34px;
		border-radius: 10px;
		border: none;
		background: var(--color-accent);
		color: #fff;
		cursor: pointer;
		transition: all 0.15s;
	}

	.send-btn:hover:not(:disabled) {
		filter: brightness(1.12);
		transform: scale(1.04);
	}

	.send-btn:disabled {
		opacity: 0.3;
		cursor: default;
	}

	:global(.spinner-icon) {
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	.sending-hint {
		font-size: 12px;
		color: var(--color-text-secondary);
		margin: 0;
		font-family: var(--font-sans);
		animation: pulse-text 1.5s ease-in-out infinite;
	}

	@keyframes pulse-text {
		0%, 100% { opacity: 0.5; }
		50% { opacity: 1; }
	}

	/* ===== Section label ===== */
	.section-label {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 11px;
		font-weight: 600;
		color: var(--color-text-secondary);
		font-family: var(--font-sans);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		padding-left: 4px;
	}

	/* ===== Templates section ===== */
	.templates-section {
		width: 100%;
		display: flex;
		flex-direction: column;
		gap: 14px;
		margin-top: 36px;
	}

	.templates-row {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
		gap: 10px;
	}

	.template-card {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 18px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 14px;
		cursor: pointer;
		text-align: left;
		position: relative;
		transition: border-color 0.2s, background 0.2s, transform 0.2s, box-shadow 0.2s;
	}

	.template-card:hover {
		border-color: oklch(from var(--color-accent) l c h / 45%);
		background: oklch(from var(--color-accent) l c h / 4%);
		transform: translateY(-2px);
		box-shadow: 0 8px 24px -8px oklch(from var(--color-accent) l c h / 10%);
	}

	.template-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 38px;
		height: 38px;
		border-radius: 10px;
		background: oklch(from var(--color-accent) l c h / 10%);
		color: var(--color-accent);
		transition: background 0.2s;
	}

	.template-card:hover .template-icon {
		background: oklch(from var(--color-accent) l c h / 16%);
	}

	.template-info {
		display: flex;
		flex-direction: column;
		gap: 4px;
		flex: 1;
	}

	.template-name {
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary);
		font-family: var(--font-sans);
		line-height: 1.3;
	}

	.template-desc {
		font-size: 11px;
		color: var(--color-text-secondary);
		font-family: var(--font-sans);
		line-height: 1.45;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.template-arrow {
		position: absolute;
		top: 16px;
		right: 16px;
		color: var(--color-text-secondary);
		opacity: 0;
		transition: opacity 0.2s, color 0.2s, transform 0.2s;
		display: flex;
	}

	.template-card:hover .template-arrow {
		opacity: 1;
		color: var(--color-accent);
		transform: translateX(2px);
	}

	/* ===== Projects section ===== */
	.projects-section {
		width: 100%;
		display: flex;
		flex-direction: column;
		gap: 14px;
		margin-top: 36px;
	}

	.section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.clear-all-btn {
		font-size: 11px;
		font-family: var(--font-sans);
		color: var(--color-text-secondary);
		background: none;
		border: none;
		cursor: pointer;
		padding: 2px 8px;
		border-radius: 4px;
		opacity: 0.6;
		transition: opacity 0.15s, color 0.15s;
	}

	.clear-all-btn:hover {
		opacity: 1;
		color: #f87171;
	}

	.delete-all-confirm {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.delete-all-text {
		font-size: 11px;
		font-family: var(--font-sans);
		color: #f87171;
		font-weight: 500;
	}

	.confirm-btn {
		font-size: 11px;
		font-family: var(--font-sans);
		font-weight: 500;
		padding: 3px 10px;
		border-radius: 6px;
		border: none;
		cursor: pointer;
		transition: all 0.15s;
	}

	.confirm-btn.danger {
		background: #f87171;
		color: #fff;
	}

	.confirm-btn.danger:hover {
		background: #ef4444;
	}

	.confirm-btn.cancel {
		background: var(--color-overlay-subtle);
		color: var(--color-text-secondary);
	}

	.confirm-btn.cancel:hover {
		background: var(--color-overlay-medium);
		color: var(--color-text-primary);
	}

	/* Search bar */
	.search-bar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 12px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		transition: border-color 0.2s, box-shadow 0.2s;
		color: var(--color-text-secondary);
	}

	.search-bar:focus-within {
		border-color: oklch(from var(--color-accent) l c h / 45%);
		box-shadow: 0 0 0 3px oklch(from var(--color-accent) l c h / 6%);
	}

	.search-input {
		flex: 1;
		background: none;
		border: none;
		outline: none;
		font-size: 13px;
		font-family: var(--font-sans);
		color: var(--color-text-primary);
	}

	.search-input::placeholder {
		color: var(--color-text-secondary);
		opacity: 0.5;
	}

	.search-clear {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		border: none;
		background: transparent;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.search-clear:hover {
		background: var(--color-overlay-light);
		color: var(--color-text-primary);
	}

	/* Projects grid — mirrors templates-row */
	.projects-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
		gap: 10px;
	}

	/* Project card — mirrors template-card */
	.project-card {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 18px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 14px;
		cursor: pointer;
		text-align: left;
		position: relative;
		transition: border-color 0.2s, background 0.2s, transform 0.2s, box-shadow 0.2s;
	}

	.project-card:hover {
		border-color: oklch(from var(--color-accent) l c h / 45%);
		background: oklch(from var(--color-accent) l c h / 4%);
		transform: translateY(-2px);
		box-shadow: 0 8px 24px -8px oklch(from var(--color-accent) l c h / 10%);
	}

	.project-card.menu-active {
		z-index: 20;
		transform: none;
	}

	.project-card.deleting {
		border-color: rgba(248, 113, 113, 0.3);
		background: rgba(248, 113, 113, 0.04);
		cursor: default;
		min-height: 140px;
		justify-content: center;
		align-items: center;
	}

	.project-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 38px;
		height: 38px;
		border-radius: 10px;
		background: oklch(from var(--color-accent) l c h / 10%);
		color: var(--color-accent);
		transition: background 0.2s;
	}

	.project-card:hover .project-icon {
		background: oklch(from var(--color-accent) l c h / 16%);
	}

	.project-info {
		display: flex;
		flex-direction: column;
		gap: 4px;
		flex: 1;
		min-width: 0;
	}

	.project-name {
		font-size: 13px;
		font-weight: 600;
		color: var(--color-text-primary);
		font-family: var(--font-sans);
		line-height: 1.3;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.project-desc {
		font-size: 11px;
		color: var(--color-text-secondary);
		font-family: var(--font-sans);
		line-height: 1.45;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.project-date {
		font-size: 11px;
		color: var(--color-text-secondary);
		font-family: var(--font-sans);
		opacity: 0.7;
	}

	.project-arrow {
		position: absolute;
		bottom: 16px;
		right: 16px;
		color: var(--color-text-secondary);
		opacity: 0;
		transition: opacity 0.2s, color 0.2s, transform 0.2s;
		display: flex;
	}

	.project-card:hover .project-arrow {
		opacity: 1;
		color: var(--color-accent);
		transform: translateX(2px);
	}

	.no-results {
		font-size: 13px;
		color: var(--color-text-secondary);
		font-family: var(--font-sans);
		text-align: center;
		padding: 20px 0;
		opacity: 0.7;
		margin: 0;
	}

	.delete-confirm-content {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		width: 100%;
		padding: 4px 0;
	}

	.delete-confirm-text {
		font-size: 12px;
		font-family: var(--font-sans);
		color: var(--color-text-primary);
		font-weight: 500;
		text-align: center;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
	}

	.delete-confirm-actions {
		display: flex;
		gap: 6px;
	}

	.rename-input,
	.desc-input {
		font-size: 13px;
		font-family: var(--font-sans);
		color: var(--color-text-primary);
		background: var(--color-bg-elevated);
		border: 1px solid oklch(from var(--color-accent) l c h / 40%);
		border-radius: 6px;
		padding: 2px 6px;
		outline: none;
		width: 100%;
	}

	.rename-input {
		font-weight: 600;
	}

	.desc-input {
		font-size: 11px;
		opacity: 0.9;
	}

	.rename-input:focus,
	.desc-input:focus {
		border-color: var(--color-accent);
		box-shadow: 0 0 0 2px oklch(from var(--color-accent) l c h / 12%);
	}

	/* 3-dot menu button */
	.card-menu-btn {
		position: absolute;
		top: 6px;
		right: 6px;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		border-radius: 6px;
		border: none;
		background: transparent;
		color: var(--color-text-secondary);
		cursor: pointer;
		opacity: 0;
		transition: opacity 0.15s, background 0.15s, color 0.15s;
		z-index: 2;
	}

	.project-card:hover .card-menu-btn {
		opacity: 0.6;
	}

	.card-menu-btn:hover {
		opacity: 1 !important;
		background: var(--color-overlay-light);
		color: var(--color-text-primary);
	}

	/* Dropdown menu */
	.card-menu {
		position: absolute;
		top: 32px;
		right: 6px;
		background: var(--color-bg-elevated);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		padding: 4px;
		min-width: 140px;
		box-shadow: var(--shadow-dropdown);
		z-index: 10;
		animation: menu-in 0.12s ease-out;
	}

	@keyframes menu-in {
		from { opacity: 0; transform: translateY(-4px) scale(0.96); }
		to { opacity: 1; transform: translateY(0) scale(1); }
	}

	.menu-item {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 7px 10px;
		background: none;
		border: none;
		border-radius: 7px;
		font-size: 12px;
		font-family: var(--font-sans);
		color: var(--color-text-primary);
		cursor: pointer;
		transition: background 0.12s;
	}

	.menu-item:hover {
		background: var(--color-overlay-subtle);
	}

	.menu-item.danger {
		color: #f87171;
	}

	.menu-item.danger:hover {
		background: rgba(248, 113, 113, 0.08);
	}

	.menu-divider {
		height: 1px;
		background: var(--color-border);
		margin: 3px 6px;
	}

	/* Backdrop for closing menus */
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 5;
		background: transparent;
		border: none;
		cursor: default;
	}

	/* ===== Responsive ===== */
	@media (max-width: 640px) {
		.hero-title {
			font-size: 24px;
		}

		.templates-row {
			grid-template-columns: repeat(2, 1fr);
		}

		.projects-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.page-content {
			padding: 0 16px;
			padding-bottom: 40px;
		}
	}
</style>
