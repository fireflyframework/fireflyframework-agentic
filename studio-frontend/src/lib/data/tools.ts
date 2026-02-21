export interface ToolParameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default?: string;
  options?: string[]; // for enum/select types
}

export interface ToolDefinition {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  parameters: ToolParameter[];
}

export const TOOL_CATALOG: ToolDefinition[] = [
  {
    id: 'calculator',
    name: 'Calculator',
    description:
      'Safe mathematical expression evaluator. Supports arithmetic, functions (sqrt, sin, cos, log, etc.), and constants (pi, e).',
    category: 'Utility',
    tags: ['math', 'calculator', 'utility'],
    parameters: [
      {
        name: 'expression',
        type: 'string',
        description: 'Math expression to evaluate',
        required: true
      }
    ]
  },
  {
    id: 'datetime',
    name: 'Date & Time',
    description: 'Current date/time information with timezone support.',
    category: 'Utility',
    tags: ['datetime', 'utility'],
    parameters: [
      {
        name: 'action',
        type: 'select',
        description: 'What to retrieve',
        required: true,
        options: ['now', 'date', 'time', 'timestamp', 'timezones']
      },
      {
        name: 'timezone',
        type: 'string',
        description: 'IANA timezone (e.g. America/New_York)',
        required: false,
        default: 'UTC'
      },
      {
        name: 'format',
        type: 'string',
        description: 'strftime format string',
        required: false
      }
    ]
  },
  {
    id: 'filesystem',
    name: 'File System',
    description:
      'Read, write, and list files. Sandboxed to a base directory with path-traversal protection.',
    category: 'I/O',
    tags: ['filesystem', 'io'],
    parameters: [
      {
        name: 'action',
        type: 'select',
        description: 'File operation',
        required: true,
        options: ['read', 'write', 'list']
      },
      {
        name: 'path',
        type: 'string',
        description: 'File or directory path',
        required: true
      },
      {
        name: 'content',
        type: 'string',
        description: 'Content to write (for write action)',
        required: false
      }
    ]
  },
  {
    id: 'http',
    name: 'HTTP Client',
    description: 'Make HTTP requests with connection pooling. Supports GET, POST, PUT, DELETE.',
    category: 'Web',
    tags: ['http', 'web'],
    parameters: [
      {
        name: 'url',
        type: 'string',
        description: 'Target URL',
        required: true
      },
      {
        name: 'method',
        type: 'select',
        description: 'HTTP method',
        required: false,
        default: 'GET',
        options: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']
      },
      {
        name: 'body',
        type: 'string',
        description: 'Request body (JSON)',
        required: false
      },
      {
        name: 'headers',
        type: 'string',
        description: 'Request headers (JSON)',
        required: false
      }
    ]
  },
  {
    id: 'json',
    name: 'JSON',
    description: 'Parse, validate, extract, and format JSON data. Supports dot-path extraction.',
    category: 'Utility',
    tags: ['json', 'utility'],
    parameters: [
      {
        name: 'action',
        type: 'select',
        description: 'JSON operation',
        required: true,
        options: ['parse', 'validate', 'extract', 'format', 'keys']
      },
      {
        name: 'data',
        type: 'string',
        description: 'JSON data to process',
        required: true
      },
      {
        name: 'path',
        type: 'string',
        description: 'Dot-path for extraction (e.g. address.city)',
        required: false
      }
    ]
  },
  {
    id: 'text',
    name: 'Text Processing',
    description: 'Count, extract, truncate, replace, and split text using regex patterns.',
    category: 'Utility',
    tags: ['text', 'utility'],
    parameters: [
      {
        name: 'action',
        type: 'select',
        description: 'Text operation',
        required: true,
        options: ['count', 'extract', 'truncate', 'replace', 'split']
      },
      {
        name: 'text',
        type: 'string',
        description: 'Input text',
        required: true
      },
      {
        name: 'pattern',
        type: 'string',
        description: 'Regex pattern (for extract/replace/split)',
        required: false
      },
      {
        name: 'replacement',
        type: 'string',
        description: 'Replacement string (for replace)',
        required: false
      }
    ]
  },
  {
    id: 'shell',
    name: 'Shell',
    description: 'Execute shell commands from an explicit allowlist. Sandboxed for safety.',
    category: 'System',
    tags: ['shell', 'system'],
    parameters: [
      {
        name: 'command',
        type: 'string',
        description: 'Command to execute (must be in allowlist)',
        required: true
      }
    ]
  },
  {
    id: 'search',
    name: 'Search',
    description: 'Web search tool (abstract -- requires implementation of _search method).',
    category: 'Web',
    tags: ['search', 'web'],
    parameters: [
      {
        name: 'query',
        type: 'string',
        description: 'Search query',
        required: true
      }
    ]
  },
  {
    id: 'database',
    name: 'Database',
    description:
      'Execute SQL queries (abstract -- requires implementation). Read-only by default with SQL injection detection.',
    category: 'I/O',
    tags: ['database', 'sql'],
    parameters: [
      {
        name: 'query',
        type: 'string',
        description: 'SQL query (SELECT/WITH only in read-only mode)',
        required: true
      },
      {
        name: 'params',
        type: 'string',
        description: 'Query parameters (JSON)',
        required: false
      }
    ]
  }
];

export function getToolById(id: string): ToolDefinition | undefined {
  return TOOL_CATALOG.find((t) => t.id === id);
}

export function getToolsByCategory(): Record<string, ToolDefinition[]> {
  const map: Record<string, ToolDefinition[]> = {};
  for (const tool of TOOL_CATALOG) {
    if (!map[tool.category]) map[tool.category] = [];
    map[tool.category].push(tool);
  }
  return map;
}
