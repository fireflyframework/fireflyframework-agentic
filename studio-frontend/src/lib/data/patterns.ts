export interface PatternDefinition {
  id: string;
  name: string;
  description: string;
  defaultMaxSteps: number;
  bestFor: string;
  configKeys: string[];
}

export const PATTERN_CATALOG: PatternDefinition[] = [
  {
    id: 'react',
    name: 'ReAct',
    description:
      'Reason-Act-Observe loop. The agent thinks, takes an action (tool call), observes the result, and repeats until done.',
    defaultMaxSteps: 10,
    bestFor: 'Tasks requiring tool interaction and iterative problem-solving',
    configKeys: ['max_steps']
  },
  {
    id: 'chain_of_thought',
    name: 'Chain of Thought',
    description:
      'Step-by-step reasoning without actions. The agent breaks down the problem into logical steps and thinks through each one.',
    defaultMaxSteps: 10,
    bestFor: 'Pure logic, analysis, and reasoning tasks without tool needs',
    configKeys: ['max_steps']
  },
  {
    id: 'plan_and_execute',
    name: 'Plan & Execute',
    description:
      'Generates a multi-step plan first, then executes each step sequentially. Can replan on failure.',
    defaultMaxSteps: 15,
    bestFor: 'Complex multi-step tasks that benefit from upfront planning',
    configKeys: ['max_steps', 'allow_replan']
  },
  {
    id: 'reflexion',
    name: 'Reflexion',
    description:
      'Execute-Critique-Retry loop. Generates output, critiques it for quality, and retries with feedback if unsatisfactory.',
    defaultMaxSteps: 5,
    bestFor: 'Quality-sensitive outputs that benefit from self-review',
    configKeys: ['max_steps']
  },
  {
    id: 'tree_of_thoughts',
    name: 'Tree of Thoughts',
    description:
      'Generates multiple solution branches, evaluates each with a score, and selects the best. Explores the solution space broadly.',
    defaultMaxSteps: 3,
    bestFor: 'Creative and exploratory problems with multiple valid approaches',
    configKeys: ['branching_factor', 'max_depth']
  },
  {
    id: 'goal_decomposition',
    name: 'Goal Decomposition',
    description:
      'Breaks a large goal into phases and tasks, then executes each task. Can delegate sub-tasks to other patterns.',
    defaultMaxSteps: 20,
    bestFor: 'Large ambiguous goals that need structured decomposition',
    configKeys: ['max_steps', 'task_pattern']
  }
];

export function getPatternById(id: string): PatternDefinition | undefined {
  return PATTERN_CATALOG.find((p) => p.id === id);
}
