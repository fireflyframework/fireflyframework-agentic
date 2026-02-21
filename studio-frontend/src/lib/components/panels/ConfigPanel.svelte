<script lang="ts">
	import { untrack } from 'svelte';
	import { X, Bot, Wrench, Brain, CircleDot, Database, Shield, Code, GitFork, GitMerge, Trash2, Link, ArrowRight, Info, Antenna, Download } from 'lucide-svelte';
	import { selectedNode, selectedNodeId, updateNodeData, nodes, edges } from '$lib/stores/pipeline';
	import FormField from './FormField.svelte';
	import ModelSelector from '$lib/components/shared/ModelSelector.svelte';
	import { TOOL_CATALOG, getToolById } from '$lib/data/tools';
	import { PATTERN_CATALOG, getPatternById } from '$lib/data/patterns';
	import { get } from 'svelte/store';

	const iconMap: Record<string, typeof Bot> = {
		input: Antenna,
		output: Download,
		agent: Bot,
		tool: Wrench,
		reasoning: Brain,
		condition: CircleDot,
		memory: Database,
		validator: Shield,
		custom_code: Code,
		fan_out: GitFork,
		fan_in: GitMerge
	};

	const nodeColorMap: Record<string, string> = {
		input: '#10b981',
		output: '#3b82f6',
		agent: '#6366f1',
		tool: '#8b5cf6',
		reasoning: '#ec4899',
		condition: '#06b6d4',
		memory: '#06b6d4',
		validator: '#f59e0b',
		custom_code: '#3b82f6',
		fan_out: '#8888a0',
		fan_in: '#8888a0'
	};

	const typeLabels: Record<string, string> = {
		input: 'Input',
		output: 'Output',
		agent: 'Agent',
		tool: 'Tool',
		reasoning: 'Reasoning',
		condition: 'Condition',
		memory: 'Memory',
		validator: 'Validator',
		custom_code: 'Custom Code',
		fan_out: 'Fan Out',
		fan_in: 'Fan In'
	};

	const patternOptions = PATTERN_CATALOG.map((p) => p.id);
	const toolOptions = ['custom', ...TOOL_CATALOG.map((t) => t.id)];

	// Derived info panels
	let selectedPattern = $derived(getPatternById(patternVal));
	let selectedTool = $derived(getToolById(toolNameVal));

	// Local field state bound to inputs
	let nameVal = $state('');
	let modelVal = $state('');
	let instructionsVal = $state('');
	let descriptionVal = $state('');
	let timeoutVal = $state('');
	let patternVal = $state('');
	let maxStepsVal = $state('');
	let conditionVal = $state('');
	let backendVal = $state('');
	let connectionStringVal = $state('');
	let namespaceVal = $state('');
	let schemaTypeVal = $state('');
	let validationRulesVal = $state('');
	let failActionVal = $state('');
	let codeVal = $state('');
	let strategyVal = $state('');
	let maxConcurrentVal = $state('');
	let mergeStrategyVal = $state('');
	let mergeTimeoutVal = $state('');
	let temperatureVal = $state('');
	let maxTokensVal = $state('');
	let toolNameVal = $state('');
	let memoryActionVal = $state('');
	let validationRuleVal = $state('');
	let splitExpressionVal = $state('');
	let mergeExpressionVal = $state('');

	// IO node fields
	let triggerTypeVal = $state('manual');
	let destinationTypeVal = $state('response');
	let queueBrokerVal = $state('kafka');
	let queueTopicVal = $state('');
	let queueGroupIdVal = $state('');
	let cronExpressionVal = $state('');
	let cronTimezoneVal = $state('UTC');
	let httpMethodVal = $state('POST');
	let httpAuthVal = $state(false);
	let fileTypesVal = $state('*/*');
	let fileSizeVal = $state('50');
	let webhookUrlVal = $state('');
	let storeTypeVal = $state('file');
	let storePathVal = $state('');
	let schemaJsonVal = $state('');

	// Multimodal config (agent nodes only)
	let visionEnabled = $state(false);
	let mmFileImages = $state(true);
	let mmFilePdfs = $state(false);
	let mmFileDocs = $state(false);
	let mmMaxFileSize = $state(10);
	let mmImageDetail = $state<'auto' | 'low' | 'high'>('auto');

	// Track which node we're showing to re-sync when selection changes
	let lastNodeId = $state<string | null>(null);

	// Flag to prevent syncing back while we're loading from store
	let syncing = false;

	// Derived: connections for this node
	let incomingEdges = $derived(
		$selectedNode ? $edges.filter((e) => e.target === $selectedNode!.id) : []
	);
	let outgoingEdges = $derived(
		$selectedNode ? $edges.filter((e) => e.source === $selectedNode!.id) : []
	);

	function getNodeLabel(nodeId: string): string {
		const node = $nodes.find((n) => n.id === nodeId);
		return (node?.data?.label as string) || node?.id || nodeId;
	}

	// Sync local state from store when selected node changes.
	// We read $selectedNode reactively (so this effect re-runs on selection change),
	// but batch-set all field values inside untrack so the individual field
	// $effect watchers don't fire during the sync.
	$effect(() => {
		const node = $selectedNode;
		if (node && node.id !== lastNodeId) {
			syncing = true;
			lastNodeId = node.id;
			untrack(() => {
				nameVal = (node.data.label as string) ?? '';
				modelVal = (node.data.model as string) ?? '';
				instructionsVal = (node.data.instructions as string) ?? '';
				descriptionVal = (node.data.description as string) ?? '';
				timeoutVal = node.data.timeout != null ? String(node.data.timeout) : '';
				patternVal = (node.data.pattern as string) ?? '';
				maxStepsVal = node.data.maxSteps != null ? String(node.data.maxSteps) : '';
				conditionVal = (node.data.condition as string) ?? '';
				backendVal = (node.data.backend as string) ?? '';
				connectionStringVal = (node.data.connection_string as string) ?? '';
				namespaceVal = (node.data.namespace as string) ?? '';
				schemaTypeVal = (node.data.schema_type as string) ?? '';
				validationRulesVal = (node.data.validation_rules as string) ?? '';
				failActionVal = (node.data.fail_action as string) ?? '';
				codeVal = (node.data.code as string) ?? '';
				strategyVal = (node.data.strategy as string) ?? '';
				maxConcurrentVal = node.data.max_concurrent != null ? String(node.data.max_concurrent) : '';
				mergeStrategyVal = (node.data.merge_strategy as string) ?? '';
				mergeTimeoutVal = node.data.merge_timeout != null ? String(node.data.merge_timeout) : '';
				temperatureVal = node.data.temperature != null ? String(node.data.temperature) : '';
				maxTokensVal = node.data.max_tokens != null ? String(node.data.max_tokens) : '';
				toolNameVal = (node.data.tool_name as string) ?? '';
				memoryActionVal = (node.data.memory_action as string) ?? '';
				validationRuleVal = (node.data.validation_rule as string) ?? '';
				splitExpressionVal = (node.data.split_expression as string) ?? '';
				mergeExpressionVal = (node.data.merge_expression as string) ?? '';

				// IO node fields
				triggerTypeVal = (node.data.trigger_type as string) ?? 'manual';
				destinationTypeVal = (node.data.destination_type as string) ?? 'response';
				queueBrokerVal = (node.data.queue_broker as string) ?? 'kafka';
				queueTopicVal = (node.data.queue_topic as string) ?? '';
				queueGroupIdVal = (node.data.queue_group_id as string) ?? '';
				cronExpressionVal = (node.data.cron_expression as string) ?? '';
				cronTimezoneVal = (node.data.cron_timezone as string) ?? 'UTC';
				httpMethodVal = (node.data.http_method as string) ?? 'POST';
				httpAuthVal = (node.data.http_auth_required as boolean) ?? false;
				fileTypesVal = (node.data.file_types as string) ?? '*/*';
				fileSizeVal = node.data.file_max_size_mb != null ? String(node.data.file_max_size_mb) : '50';
				webhookUrlVal = (node.data.webhook_url as string) ?? '';
				storeTypeVal = (node.data.store_type as string) ?? 'file';
				storePathVal = (node.data.store_path as string) ?? '';
				schemaJsonVal = (node.data.schema_json as string) ?? '';

				// Multimodal config
				const mm = node.data.multimodal as Record<string, unknown> | undefined;
				visionEnabled = (mm?.vision_enabled as boolean) ?? false;
				const fileTypes = (mm?.supported_file_types as string[]) ?? ['image/png', 'image/jpeg'];
				mmFileImages = fileTypes.some(t => t.startsWith('image/'));
				mmFilePdfs = fileTypes.includes('application/pdf');
				mmFileDocs = fileTypes.some(t => t.includes('document') || t.includes('msword'));
				mmMaxFileSize = (mm?.max_file_size_mb as number) ?? 10;
				mmImageDetail = (mm?.image_detail as 'auto' | 'low' | 'high') ?? 'auto';
			});
			syncing = false;
		}
		if (!node) {
			lastNodeId = null;
		}
	});

	// Push individual field changes to the store.
	// IMPORTANT: use untrack so $effect callers don't subscribe to stores
	// that pushField reads — otherwise updating nodes re-triggers every
	// field effect, creating an infinite reactive loop.
	function pushField(key: string, val: string) {
		if (syncing) return;
		untrack(() => {
			const nodeId = $selectedNodeId;
			if (!nodeId) return;
			const numericFields = ['timeout', 'maxSteps', 'max_concurrent', 'merge_timeout', 'temperature', 'max_tokens'];
			if (numericFields.includes(key)) {
				updateNodeData(nodeId, key, val === '' ? undefined : Number(val));
			} else {
				updateNodeData(nodeId, key, val);
			}
		});
	}

	// Watch each field value and push to store
	$effect(() => { pushField('label', nameVal); });
	$effect(() => { pushField('model', modelVal); });
	$effect(() => { pushField('instructions', instructionsVal); });
	$effect(() => { pushField('description', descriptionVal); });
	$effect(() => { pushField('timeout', timeoutVal); });
	$effect(() => { pushField('pattern', patternVal); });
	$effect(() => { pushField('maxSteps', maxStepsVal); });
	$effect(() => { pushField('condition', conditionVal); });
	$effect(() => { pushField('backend', backendVal); });
	$effect(() => { pushField('connection_string', connectionStringVal); });
	$effect(() => { pushField('namespace', namespaceVal); });
	$effect(() => { pushField('schema_type', schemaTypeVal); });
	$effect(() => { pushField('validation_rules', validationRulesVal); });
	$effect(() => { pushField('fail_action', failActionVal); });
	$effect(() => { pushField('code', codeVal); });
	$effect(() => { pushField('strategy', strategyVal); });
	$effect(() => { pushField('max_concurrent', maxConcurrentVal); });
	$effect(() => { pushField('merge_strategy', mergeStrategyVal); });
	$effect(() => { pushField('merge_timeout', mergeTimeoutVal); });
	$effect(() => { pushField('temperature', temperatureVal); });
	$effect(() => { pushField('max_tokens', maxTokensVal); });
	$effect(() => { pushField('tool_name', toolNameVal); });
	$effect(() => { pushField('memory_action', memoryActionVal); });
	$effect(() => { pushField('validation_rule', validationRuleVal); });
	$effect(() => { pushField('split_expression', splitExpressionVal); });
	$effect(() => { pushField('merge_expression', mergeExpressionVal); });
	$effect(() => { pushField('trigger_type', triggerTypeVal); });
	$effect(() => { pushField('destination_type', destinationTypeVal); });
	$effect(() => { pushField('queue_broker', queueBrokerVal); });
	$effect(() => { pushField('queue_topic', queueTopicVal); });
	$effect(() => { pushField('queue_group_id', queueGroupIdVal); });
	$effect(() => { pushField('cron_expression', cronExpressionVal); });
	$effect(() => { pushField('cron_timezone', cronTimezoneVal); });
	$effect(() => { pushField('http_method', httpMethodVal); });
	$effect(() => { pushField('file_types', fileTypesVal); });
	$effect(() => { pushField('file_max_size_mb', fileSizeVal); });
	$effect(() => { pushField('webhook_url', webhookUrlVal); });
	$effect(() => { pushField('store_type', storeTypeVal); });
	$effect(() => { pushField('store_path', storePathVal); });
	$effect(() => { pushField('schema_json', schemaJsonVal); });

	// Push multimodal config as a single object whenever any sub-field changes
	$effect(() => {
		// Read all multimodal fields to subscribe
		const enabled = visionEnabled;
		const images = mmFileImages;
		const pdfs = mmFilePdfs;
		const docs = mmFileDocs;
		const maxSize = mmMaxFileSize;
		const detail = mmImageDetail;

		if (syncing) return;
		untrack(() => {
			const nodeId = $selectedNodeId;
			if (!nodeId) return;
			const node = $nodes.find(n => n.id === nodeId);
			if (!node || node.type !== 'agent') return;

			const fileTypes: string[] = [];
			if (images) fileTypes.push('image/png', 'image/jpeg');
			if (pdfs) fileTypes.push('application/pdf');
			if (docs) fileTypes.push('application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');

			updateNodeData(nodeId, 'multimodal', {
				vision_enabled: enabled,
				supported_file_types: fileTypes,
				max_file_size_mb: maxSize,
				image_detail: detail,
			});
		});
	});

	function close() {
		selectedNodeId.set(null);
	}

	function deleteNode() {
		const node = $selectedNode;
		if (!node) return;
		const id = node.id;
		nodes.update((ns) => ns.filter((n) => n.id !== id));
		edges.update((es) => es.filter((e) => e.source !== id && e.target !== id));
		selectedNodeId.set(null);
	}

	function selectNode(nodeId: string) {
		selectedNodeId.set(nodeId);
	}
</script>

{#if $selectedNode}
	{@const node = $selectedNode}
	{@const NodeIcon = iconMap[node.type ?? ''] ?? Bot}
	{@const nodeColor = nodeColorMap[node.type ?? ''] ?? '#ff6b35'}

	<aside class="config-panel">
		<!-- Header -->
		<div class="panel-header">
			<div class="header-left">
				<div class="header-icon" style:--node-color={nodeColor}>
					<NodeIcon size={14} />
				</div>
				<div class="header-info">
					<span class="header-title">{typeLabels[node.type ?? ''] ?? 'Node'} Properties</span>
					<span class="header-id">{node.id}</span>
				</div>
			</div>
			<button class="close-btn" onclick={close} title="Close panel">
				<X size={14} />
			</button>
		</div>

		<div class="panel-body">
			<!-- Node type badge -->
			<div class="node-type-row">
				<span class="node-type-badge" style:--badge-color={nodeColor}>
					{typeLabels[node.type ?? ''] ?? node.type}
				</span>
			</div>

			<!-- Type-specific fields -->
			<div class="section">
				<div class="section-title">Configuration</div>
				<div class="field-group">
					{#if node.type === 'input'}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Input node name" />
						<FormField label="Trigger Type" type="select" bind:value={triggerTypeVal} options={['manual', 'http', 'queue', 'schedule', 'file_upload']} />

						{#if triggerTypeVal === 'http'}
							<FormField label="HTTP Method" type="select" bind:value={httpMethodVal} options={['GET', 'POST', 'PUT', 'PATCH']} />
							<div class="info-card info-card-muted">
								<p class="info-card-text">Exposes an HTTP endpoint that triggers this pipeline when called.</p>
							</div>
						{:else if triggerTypeVal === 'queue'}
							<FormField label="Broker" type="select" bind:value={queueBrokerVal} options={['kafka', 'rabbitmq', 'redis']} />
							<FormField label="Topic / Queue" type="text" bind:value={queueTopicVal} placeholder="pipeline-input" />
							<FormField label="Group ID" type="text" bind:value={queueGroupIdVal} placeholder="studio-group" />
						{:else if triggerTypeVal === 'schedule'}
							<FormField label="Cron Expression" type="text" bind:value={cronExpressionVal} placeholder="0 */6 * * *" />
							<FormField label="Timezone" type="text" bind:value={cronTimezoneVal} placeholder="UTC" />
							<div class="info-card info-card-muted">
								<p class="info-card-text">Runs the pipeline on a schedule using standard cron syntax.</p>
							</div>
						{:else if triggerTypeVal === 'file_upload'}
							<FormField label="Accepted Types" type="text" bind:value={fileTypesVal} placeholder="application/pdf, text/csv" />
							<FormField label="Max Size (MB)" type="number" bind:value={fileSizeVal} placeholder="50" />
						{:else}
							<div class="info-card info-card-muted">
								<p class="info-card-text">Manual trigger. Run the pipeline via the Run button or API call.</p>
							</div>
						{/if}

						<FormField label="Input Schema (JSON)" type="textarea" bind:value={schemaJsonVal} placeholder={'{"type": "object", "properties": {…}}'} />

					{:else if node.type === 'output'}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Output node name" />
						<FormField label="Destination" type="select" bind:value={destinationTypeVal} options={['response', 'queue', 'webhook', 'store']} />

						{#if destinationTypeVal === 'queue'}
							<FormField label="Broker" type="select" bind:value={queueBrokerVal} options={['kafka', 'rabbitmq', 'redis']} />
							<FormField label="Topic / Queue" type="text" bind:value={queueTopicVal} placeholder="pipeline-output" />
						{:else if destinationTypeVal === 'webhook'}
							<FormField label="Webhook URL" type="text" bind:value={webhookUrlVal} placeholder="https://example.com/callback" />
						{:else if destinationTypeVal === 'store'}
							<FormField label="Storage Type" type="select" bind:value={storeTypeVal} options={['file', 'database']} />
							<FormField label="Path / Table" type="text" bind:value={storePathVal} placeholder="/tmp/results.json" />
						{:else}
							<div class="info-card info-card-muted">
								<p class="info-card-text">Returns the pipeline output as an API response.</p>
							</div>
						{/if}

						<FormField label="Response Schema (JSON)" type="textarea" bind:value={schemaJsonVal} placeholder={'{"type": "object", "properties": {…}}'} />

					{:else if node.type === 'agent'}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Agent name" />
						<div class="form-field">
							<!-- svelte-ignore a11y_label_has_associated_control -->
							<label class="field-label">MODEL</label>
							<ModelSelector bind:value={modelVal} placeholder="Select model..." />
						</div>
						<FormField label="Instructions" type="textarea" bind:value={instructionsVal} placeholder="System instructions for this agent..." />
						<FormField label="Description" type="text" bind:value={descriptionVal} placeholder="Agent description" />
						<FormField label="Temperature" type="number" bind:value={temperatureVal} placeholder="0.7" />
						<FormField label="Max Tokens" type="number" bind:value={maxTokensVal} placeholder="4096" />

						<!-- Multimodal section -->
						<div class="mm-section">
							<button class="mm-toggle" onclick={() => visionEnabled = !visionEnabled}>
								<span class="mm-toggle-label">Multimodal</span>
								<span class="mm-toggle-switch" class:mm-on={visionEnabled}>
									<span class="mm-toggle-thumb"></span>
								</span>
							</button>
							{#if visionEnabled}
								<div class="mm-options">
									<div class="mm-group">
										<span class="mm-group-label">Accepted file types</span>
										<label class="mm-check"><input type="checkbox" bind:checked={mmFileImages} /><span>Images</span></label>
										<label class="mm-check"><input type="checkbox" bind:checked={mmFilePdfs} /><span>PDFs</span></label>
										<label class="mm-check"><input type="checkbox" bind:checked={mmFileDocs} /><span>Documents</span></label>
									</div>
									<div class="mm-group">
										<span class="mm-group-label">Max file size</span>
										<div class="mm-range-row">
											<input type="range" class="mm-range" min="1" max="50" step="1" bind:value={mmMaxFileSize} />
											<span class="mm-range-val">{mmMaxFileSize} MB</span>
										</div>
									</div>
									<div class="mm-group">
										<span class="mm-group-label">Image detail</span>
										<div class="mm-radio-row">
											<label class="mm-radio"><input type="radio" name="mm-detail" value="auto" bind:group={mmImageDetail} /><span>Auto</span></label>
											<label class="mm-radio"><input type="radio" name="mm-detail" value="low" bind:group={mmImageDetail} /><span>Low</span></label>
											<label class="mm-radio"><input type="radio" name="mm-detail" value="high" bind:group={mmImageDetail} /><span>High</span></label>
										</div>
									</div>
								</div>
							{/if}
						</div>

					{:else if node.type === 'tool'}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Tool label on canvas" />
						<FormField label="Tool Type" type="select" bind:value={toolNameVal} options={toolOptions} />
						{#if selectedTool}
							<div class="info-card">
								<div class="info-card-header">
									<Info size={11} />
									<span>{selectedTool.name}</span>
								</div>
								<p class="info-card-text">{selectedTool.description}</p>
								{#if selectedTool.parameters.length > 0}
									<div class="info-params">
										{#each selectedTool.parameters as param}
											<div class="info-param-row">
												<span class="info-param-name">{param.name}</span>
												<span class="info-param-type">{param.type}{param.required ? '' : '?'}</span>
											</div>
										{/each}
									</div>
								{/if}
							</div>
						{:else if toolNameVal === 'custom'}
							<div class="info-card info-card-muted">
								<p class="info-card-text">Custom tool. Define the tool name as registered in the framework tool registry.</p>
							</div>
						{/if}
						<FormField label="Description" type="textarea" bind:value={descriptionVal} placeholder="What this tool does" />
						<FormField label="Timeout (seconds)" type="number" bind:value={timeoutVal} placeholder="30" />

					{:else if node.type === 'reasoning'}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Reasoning name" />
						<FormField label="Pattern" type="select" bind:value={patternVal} options={patternOptions} />
						{#if selectedPattern}
							<div class="info-card">
								<div class="info-card-header">
									<Brain size={11} />
									<span>{selectedPattern.name}</span>
								</div>
								<p class="info-card-text">{selectedPattern.description}</p>
								<p class="info-card-hint">Best for: {selectedPattern.bestFor}</p>
							</div>
						{/if}
						<FormField label="Max Steps" type="number" bind:value={maxStepsVal} placeholder={selectedPattern ? String(selectedPattern.defaultMaxSteps) : '10'} />
						<FormField label="Description" type="text" bind:value={descriptionVal} placeholder="Reasoning strategy description" />

					{:else if node.type === 'condition'}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Condition name" />
						<FormField label="Condition Key" type="text" bind:value={conditionVal} placeholder="e.g. document_type, status" />
						<div class="info-card info-card-muted">
							<p class="info-card-text">Routes flow based on a key in the pipeline context. Connect the True and False handles to different downstream nodes. Use configure_node to set branches as a JSON dict mapping values to paths.</p>
						</div>

					{:else if node.type === 'memory'}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Memory name" />
						<FormField label="Action" type="select" bind:value={memoryActionVal} options={['store', 'retrieve', 'clear']} />
						<div class="info-card info-card-muted">
							{#if memoryActionVal === 'store'}
								<p class="info-card-text">Saves the current pipeline state/output to memory for later retrieval.</p>
							{:else if memoryActionVal === 'retrieve'}
								<p class="info-card-text">Loads previously saved state from memory and injects it into the pipeline context.</p>
							{:else if memoryActionVal === 'clear'}
								<p class="info-card-text">Wipes all stored memory. Use with caution.</p>
							{:else}
								<p class="info-card-text">Select an action: store saves data, retrieve loads it, clear wipes memory.</p>
							{/if}
						</div>
						<FormField label="Namespace" type="text" bind:value={namespaceVal} placeholder="default" />

					{:else if node.type === 'validator'}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Validator name" />
						<FormField label="Validation Rule" type="select" bind:value={validationRuleVal} options={['not_empty', 'is_string', 'is_list', 'is_dict', 'custom']} />
						<div class="info-card info-card-muted">
							{#if validationRuleVal === 'not_empty'}
								<p class="info-card-text">Ensures the output is not empty, null, or blank.</p>
							{:else if validationRuleVal === 'is_string'}
								<p class="info-card-text">Validates that the output is a string type.</p>
							{:else if validationRuleVal === 'is_list'}
								<p class="info-card-text">Validates that the output is a list/array.</p>
							{:else if validationRuleVal === 'is_dict'}
								<p class="info-card-text">Validates that the output is a dictionary/object.</p>
							{:else if validationRuleVal === 'custom'}
								<p class="info-card-text">Custom validation rule. Define the rule key as registered in the framework.</p>
							{:else}
								<p class="info-card-text">Select a validation rule to apply to the pipeline output before passing downstream.</p>
							{/if}
						</div>
						<FormField label="On Failure" type="select" bind:value={failActionVal} options={['reject', 'retry', 'fallback', 'log']} />

					{:else if node.type === 'custom_code'}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Code block name" />
						<FormField label="Description" type="text" bind:value={descriptionVal} placeholder="What this code does" />
						<FormField label="Python Code" type="textarea" bind:value={codeVal} placeholder="async def execute(context, inputs):&#10;    return inputs" />
						<div class="info-card info-card-muted">
							<p class="info-card-text">Must define: <code>async def execute(context, inputs) -> Any</code></p>
						</div>

					{:else if node.type === 'fan_out'}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Fan Out name" />
						<FormField label="Split Expression" type="text" bind:value={splitExpressionVal} placeholder="How to split input for parallel branches" />
						<FormField label="Max Concurrent" type="number" bind:value={maxConcurrentVal} placeholder="10" />
						<div class="info-card info-card-muted">
							<p class="info-card-text">Splits a single input into multiple items for parallel processing across downstream branches.</p>
						</div>

					{:else if node.type === 'fan_in'}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Fan In name" />
						<FormField label="Merge Expression" type="select" bind:value={mergeExpressionVal} options={['concat', 'collect']} />
						<FormField label="Timeout (seconds)" type="number" bind:value={mergeTimeoutVal} placeholder="30" />
						<div class="info-card info-card-muted">
							{#if mergeExpressionVal === 'concat'}
								<p class="info-card-text">Concatenates all branch results into a single string.</p>
							{:else if mergeExpressionVal === 'collect'}
								<p class="info-card-text">Collects all branch results into a list.</p>
							{:else}
								<p class="info-card-text">Merges results from parallel branches back into a single output.</p>
							{/if}
						</div>

					{:else}
						<FormField label="Name" type="text" bind:value={nameVal} placeholder="Node name" />
					{/if}
				</div>
			</div>

			<!-- Connections section -->
			{#if incomingEdges.length > 0 || outgoingEdges.length > 0}
				<div class="section">
					<div class="section-title">
						<Link size={12} />
						Connections
					</div>
					<div class="connections-list">
						{#if incomingEdges.length > 0}
							<div class="connection-group">
								<span class="connection-label">Inputs</span>
								{#each incomingEdges as edge}
									<button class="connection-item" onclick={() => selectNode(edge.source)} title="Select {getNodeLabel(edge.source)}">
										<span class="connection-node-name">{getNodeLabel(edge.source)}</span>
										<ArrowRight size={10} />
										<span class="connection-this">this</span>
									</button>
								{/each}
							</div>
						{/if}
						{#if outgoingEdges.length > 0}
							<div class="connection-group">
								<span class="connection-label">Outputs</span>
								{#each outgoingEdges as edge}
									<button class="connection-item" onclick={() => selectNode(edge.target)} title="Select {getNodeLabel(edge.target)}">
										<span class="connection-this">this</span>
										<ArrowRight size={10} />
										<span class="connection-node-name">{getNodeLabel(edge.target)}</span>
									</button>
								{/each}
							</div>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Position info -->
			<div class="section">
				<div class="section-title">Position</div>
				<div class="position-row">
					<span class="position-value">X: {Math.round(node.position.x)}</span>
					<span class="position-value">Y: {Math.round(node.position.y)}</span>
				</div>
			</div>

			<!-- Danger zone -->
			<div class="section danger-section">
				<button class="delete-btn" onclick={deleteNode} title="Delete this node">
					<Trash2 size={13} />
					<span>Delete Node</span>
				</button>
			</div>
		</div>
	</aside>
{/if}

<style>
	.config-panel {
		width: 100%;
		background: var(--color-bg-secondary, #12121a);
		display: flex;
		flex-direction: column;
		overflow-y: auto;
	}

	.panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 16px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
	}

	.header-icon {
		width: 28px;
		height: 28px;
		border-radius: 8px;
		background: oklch(from var(--node-color, #ff6b35) l c h / 15%);
		color: var(--node-color, #ff6b35);
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.header-info {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.header-title {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-primary, #e8e8ed);
	}

	.header-id {
		font-size: 10px;
		font-family: var(--font-mono, 'JetBrains Mono', monospace);
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.7;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.close-btn {
		width: 28px;
		height: 28px;
		border: none;
		background: transparent;
		border-radius: 6px;
		color: var(--color-text-secondary, #8888a0);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		transition: background 0.15s ease, color 0.15s ease;
	}

	.close-btn:hover {
		background: rgba(255, 255, 255, 0.05);
		color: var(--color-text-primary, #e8e8ed);
	}

	.panel-body {
		padding: 16px;
		display: flex;
		flex-direction: column;
		gap: 20px;
	}

	.node-type-row {
		display: flex;
		align-items: center;
	}

	.node-type-badge {
		display: inline-flex;
		padding: 3px 10px;
		border-radius: 10px;
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		background: oklch(from var(--badge-color, #ff6b35) l c h / 12%);
		color: var(--badge-color, #ff6b35);
		border: 1px solid oklch(from var(--badge-color, #ff6b35) l c h / 20%);
	}

	.section {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.section-title {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary, #8888a0);
		padding-bottom: 4px;
		border-bottom: 1px solid var(--color-border, #2a2a3a);
	}

	.field-group {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

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

	/* Info cards */
	.info-card {
		background: rgba(99, 102, 241, 0.06);
		border: 1px solid rgba(99, 102, 241, 0.15);
		border-radius: 6px;
		padding: 8px 10px;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.info-card-muted {
		background: rgba(255, 255, 255, 0.02);
		border-color: var(--color-border, #2a2a3a);
	}

	.info-card-header {
		display: flex;
		align-items: center;
		gap: 5px;
		color: var(--color-accent, #ff6b35);
		font-size: 11px;
		font-weight: 600;
	}

	.info-card-text {
		font-size: 10px;
		line-height: 1.5;
		color: var(--color-text-secondary, #8888a0);
		margin: 0;
	}

	.info-card-text :global(code) {
		font-family: var(--font-mono, 'JetBrains Mono', monospace);
		font-size: 10px;
		background: rgba(255, 255, 255, 0.06);
		padding: 1px 4px;
		border-radius: 3px;
		color: var(--color-text-primary, #e8e8ed);
	}

	.info-card-hint {
		font-size: 10px;
		line-height: 1.4;
		color: var(--color-accent, #ff6b35);
		margin: 2px 0 0;
		font-style: italic;
	}

	.info-params {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin-top: 4px;
		padding-top: 4px;
		border-top: 1px solid rgba(255, 255, 255, 0.05);
	}

	.info-param-row {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 10px;
	}

	.info-param-name {
		font-family: var(--font-mono, 'JetBrains Mono', monospace);
		color: var(--color-text-primary, #e8e8ed);
		font-weight: 500;
	}

	.info-param-type {
		font-family: var(--font-mono, 'JetBrains Mono', monospace);
		color: var(--color-text-secondary, #8888a0);
		font-size: 9px;
	}

	/* Connections */
	.connections-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.connection-group {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.connection-label {
		font-size: 10px;
		font-weight: 500;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.7;
	}

	.connection-item {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 5px 8px;
		background: rgba(255, 255, 255, 0.03);
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
		cursor: pointer;
		font-size: 11px;
		color: var(--color-text-primary, #e8e8ed);
		transition: background 0.15s, border-color 0.15s;
	}

	.connection-item:hover {
		background: rgba(255, 255, 255, 0.06);
		border-color: var(--color-accent, #ff6b35);
	}

	.connection-node-name {
		font-weight: 500;
	}

	.connection-this {
		font-size: 10px;
		color: var(--color-text-secondary, #8888a0);
		font-style: italic;
	}

	/* Position */
	.position-row {
		display: flex;
		gap: 16px;
	}

	.position-value {
		font-size: 11px;
		font-family: var(--font-mono, 'JetBrains Mono', monospace);
		color: var(--color-text-secondary, #8888a0);
	}

	/* Danger zone */
	.danger-section {
		padding-top: 8px;
		border-top: 1px solid rgba(239, 68, 68, 0.15);
	}

	.delete-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		width: 100%;
		padding: 8px 12px;
		background: rgba(239, 68, 68, 0.08);
		border: 1px solid rgba(239, 68, 68, 0.2);
		border-radius: 6px;
		color: var(--color-error, #ef4444);
		font-size: 12px;
		font-weight: 500;
		cursor: pointer;
		transition: background 0.15s, border-color 0.15s;
	}

	.delete-btn:hover {
		background: rgba(239, 68, 68, 0.15);
		border-color: rgba(239, 68, 68, 0.35);
	}

	/* Multimodal section */
	.mm-section {
		border: 1px solid var(--color-border, #2a2a3a);
		border-radius: 6px;
		overflow: hidden;
	}

	.mm-toggle {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: 8px 10px;
		background: rgba(255, 255, 255, 0.02);
		border: none;
		cursor: pointer;
		color: var(--color-text-primary, #e8e8ed);
	}

	.mm-toggle:hover { background: rgba(255, 255, 255, 0.04); }

	.mm-toggle-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary, #8888a0);
	}

	.mm-toggle-switch {
		width: 28px;
		height: 16px;
		border-radius: 8px;
		background: var(--color-border, #2a2a3a);
		position: relative;
		transition: background 0.15s;
	}

	.mm-toggle-switch.mm-on { background: var(--color-accent, #ff6b35); }

	.mm-toggle-thumb {
		position: absolute;
		top: 2px;
		left: 2px;
		width: 12px;
		height: 12px;
		border-radius: 50%;
		background: white;
		transition: transform 0.15s;
	}

	.mm-on .mm-toggle-thumb { transform: translateX(12px); }

	.mm-options {
		padding: 8px 10px;
		display: flex;
		flex-direction: column;
		gap: 10px;
		border-top: 1px solid var(--color-border, #2a2a3a);
	}

	.mm-group {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.mm-group-label {
		font-size: 9px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-secondary, #8888a0);
		opacity: 0.7;
	}

	.mm-check, .mm-radio {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 11px;
		color: var(--color-text-primary, #e8e8ed);
		cursor: pointer;
	}

	.mm-check input, .mm-radio input { accent-color: var(--color-accent, #ff6b35); }

	.mm-range-row {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.mm-range {
		flex: 1;
		accent-color: var(--color-accent, #ff6b35);
	}

	.mm-range-val {
		font-size: 10px;
		font-family: var(--font-mono, 'JetBrains Mono', monospace);
		color: var(--color-accent, #ff6b35);
		min-width: 40px;
		text-align: right;
	}

	.mm-radio-row {
		display: flex;
		gap: 12px;
	}
</style>
