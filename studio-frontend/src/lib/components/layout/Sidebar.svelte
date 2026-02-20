<script lang="ts">
	import { page } from '$app/stores';
	import Blocks from 'lucide-svelte/icons/blocks';
	import FlaskConical from 'lucide-svelte/icons/flask-conical';
	import GitBranch from 'lucide-svelte/icons/git-branch';
	import Rocket from 'lucide-svelte/icons/rocket';
	import Activity from 'lucide-svelte/icons/activity';
	import FolderOpen from 'lucide-svelte/icons/folder-open';

	const navItems = [
		{ label: 'Build', href: '/build', icon: Blocks },
		{ label: 'Evaluate', href: '/evaluate', icon: FlaskConical },
		{ label: 'Experiments', href: '/experiments', icon: GitBranch },
		{ label: 'Deploy', href: '/deploy', icon: Rocket },
		{ label: 'Monitor', href: '/monitor', icon: Activity },
		{ label: 'Files', href: '/files', icon: FolderOpen },
	];

	function isActive(pathname: string, href: string): boolean {
		return pathname === href || pathname.startsWith(href + '/');
	}
</script>

<nav class="sidebar">
	<div class="nav-items">
		{#each navItems as item}
			{@const active = isActive($page.url.pathname, item.href)}
			<a
				href={item.href}
				class="nav-item"
				class:active
				title={item.label}
			>
				<div class="nav-icon">
					<item.icon size={20} />
				</div>
				<span class="nav-label">{item.label}</span>
			</a>
		{/each}
	</div>
</nav>

<style>
	.sidebar {
		width: 56px;
		min-width: 56px;
		height: 100%;
		background: var(--color-bg-secondary);
		border-right: 1px solid var(--color-border);
		display: flex;
		flex-direction: column;
		user-select: none;
	}

	.nav-items {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 8px 0;
		gap: 2px;
	}

	.nav-item {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		width: 40px;
		height: 40px;
		border-radius: 8px;
		color: var(--color-text-secondary);
		text-decoration: none;
		transition: background 0.15s, color 0.15s;
		position: relative;
	}

	.nav-item:hover {
		background: var(--color-bg-elevated);
		color: var(--color-text-primary);
	}

	.nav-item.active {
		color: var(--color-accent);
		background: oklch(from var(--color-accent) l c h / 10%);
	}

	.nav-icon {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.nav-label {
		font-family: var(--font-sans);
		font-size: 9px;
		font-weight: 500;
		line-height: 1;
		margin-top: 1px;
	}
</style>
