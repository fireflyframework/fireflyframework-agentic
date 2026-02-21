<script lang="ts">
	import { page } from '$app/stores';
	import LayoutDashboard from 'lucide-svelte/icons/layout-dashboard';
	import Blocks from 'lucide-svelte/icons/blocks';
	import FlaskConical from 'lucide-svelte/icons/flask-conical';
	import GitBranch from 'lucide-svelte/icons/git-branch';
	import Rocket from 'lucide-svelte/icons/rocket';
	import Activity from 'lucide-svelte/icons/activity';
	import FolderOpen from 'lucide-svelte/icons/folder-open';
	import Plug from 'lucide-svelte/icons/plug';
	import Tooltip from '$lib/components/shared/Tooltip.svelte';

	const navItems = [
		{ label: 'Home', href: '/', icon: LayoutDashboard, desc: 'Dashboard and project overview' },
		{ label: 'Construct', href: '/construct', icon: Blocks, desc: 'Build and design your AI pipeline on the canvas' },
		{ label: 'Integrate', href: '/integrations', icon: Plug, desc: 'Connect external services and create custom tools' },
		{ label: 'Evaluate', href: '/evaluate', icon: FlaskConical, desc: 'Test and evaluate pipeline outputs' },
		{ label: 'Experiments', href: '/experiments', icon: GitBranch, desc: 'Compare pipeline variants and run A/B tests' },
		{ label: 'Deploy', href: '/deploy', icon: Rocket, desc: 'Generate deployment code and deploy your pipeline' },
		{ label: 'Monitor', href: '/monitor', icon: Activity, desc: 'Monitor pipeline executions and performance' },
		{ label: 'Files', href: '/files', icon: FolderOpen, desc: 'Browse and manage project files' },
	];

	function isActive(pathname: string, href: string): boolean {
		if (href === '/') return pathname === '/';
		return pathname === href || pathname.startsWith(href + '/');
	}
</script>

<nav class="sidebar">
	<div class="nav-items">
		{#each navItems as item}
			{@const active = isActive($page.url.pathname, item.href)}
			<Tooltip text={item.label} description={item.desc} position="right">
				<a
					href={item.href}
					class="nav-item"
					class:active
				>
					<div class="nav-icon">
						<item.icon size={20} />
					</div>
					<span class="nav-label">{item.label}</span>
				</a>
			</Tooltip>
		{/each}
	</div>
</nav>

<style>
	.sidebar {
		width: 56px;
		min-width: 56px;
		height: 100%;
		background: oklch(from var(--color-bg-secondary) calc(l - 0.01) c h);
		border-right: 1px solid oklch(from var(--color-border) l c h / 60%);
		display: flex;
		flex-direction: column;
		user-select: none;
	}

	.nav-items {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 8px 0;
		gap: 1px;
	}

	.nav-item {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		width: 42px;
		height: 42px;
		border-radius: 10px;
		color: var(--color-text-secondary);
		text-decoration: none;
		transition: background 0.2s, color 0.2s;
		position: relative;
		opacity: 0.65;
	}

	.nav-item:hover {
		background: rgba(255,255,255,0.05);
		color: var(--color-text-primary);
		opacity: 1;
	}

	.nav-item.active {
		color: var(--color-accent);
		background: oklch(from var(--color-accent) l c h / 10%);
		opacity: 1;
	}

	.nav-item.active::before {
		content: '';
		position: absolute;
		left: -7px;
		top: 50%;
		transform: translateY(-50%);
		width: 3px;
		height: 18px;
		border-radius: 0 3px 3px 0;
		background: var(--color-accent);
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
		margin-top: 2px;
	}
</style>
