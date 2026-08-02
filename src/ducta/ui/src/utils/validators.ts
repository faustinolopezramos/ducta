import { z } from 'zod';

/**
 * Validation schemas using Zod
 * Provides runtime type-checking for all forms and API responses
 */

// ═══════════════════════════════════════════════════════════════════════════
// PIPELINE SCHEMAS
// ═══════════════════════════════════════════════════════════════════════════

export const NodeSchema = z.object({
  id: z.string().min(1, 'Node ID required'),
  name: z.string()
    .min(1, 'Node name required')
    .regex(/^[A-Za-z0-9_\-.]+$/, 'Only alphanumeric characters, underscores, hyphens and dots are allowed'),
  type: z.enum(['source', 'transform', 'sink', 'custom']),
  module: z.string().min(1, 'Module required'),
  description: z.string().optional(),
  config: z.record(z.string(), z.any()).optional(),
  code: z.string().optional(),
  inputs: z.array(z.object({
    id: z.string(),
    name: z.string(),
    format: z.string(),
    filepath: z.string(),
    mode: z.literal('read')
  })).optional(),
  outputs: z.array(z.object({
    id: z.string(),
    name: z.string(),
    format: z.string(),
    filepath: z.string(),
    mode: z.literal('write')
  })).optional(),
  active: z.boolean().default(true),
});

export const EdgeSchema = z.object({
  id: z.string().min(1),
  source: z.string().min(1),
  target: z.string().min(1),
  sourceHandle: z.string().optional(),
  targetHandle: z.string().optional(),
  animated: z.boolean().optional(),
});

export const PipelineSchema = z.object({
  id: z.string().min(1),
  name: z.string()
    .min(1, 'Pipeline name required')
    .regex(/^[A-Za-z0-9_-]+$/, 'Only alphanumeric characters, underscores and hyphens are allowed'),
  description: z.string().optional(),
  nodes: z.array(NodeSchema).min(1, 'At least one node required'),
  edges: z.array(EdgeSchema),
  active: z.boolean().default(true),
  purpose: z.enum(['etl', 'ml', 'dq', 'reporting', 'custom']).optional(),
  temporal: z.boolean().optional(),
  createdAt: z.number(),
  updatedAt: z.number(),
});

export const ProjectSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1, 'Project name required'),
  description: z.string().optional(),
  pipelines: z.array(PipelineSchema),
  workspace_path: z.string().optional(),
});

// ═══════════════════════════════════════════════════════════════════════════
// FORM SCHEMAS
// ═══════════════════════════════════════════════════════════════════════════

export const LoginFormSchema = z.object({
  username: z.string().min(1, 'Username required'),
  password: z.string().min(1, 'Password required'),
});

export const PipelineFormSchema = z.object({
  name: z.string()
    .min(1, 'Pipeline name required')
    .max(50, 'Name too long')
    .regex(/^[A-Za-z0-9_-]+$/, 'Only alphanumeric characters, underscores and hyphens are allowed'),
  description: z.string().optional(),
  purpose: z.enum(['etl', 'ml', 'dq', 'reporting', 'custom']).optional(),
});

export const NodeFormSchema = z.object({
  name: z.string()
    .min(1, 'Node name required')
    .regex(/^[A-Za-z0-9_\-.]+$/, 'Only alphanumeric characters, underscores, hyphens and dots are allowed'),
  type: z.enum(['source', 'transform', 'sink', 'custom']),
  module: z.string().min(1, 'Module required'),
  description: z.string().optional(),
});

export const ExecutionFormSchema = z.object({
  environment: z.string().min(1, 'Environment required'),
  dryRun: z.boolean().default(false),
  startDate: z.string().optional(),
  endDate: z.string().optional(),
});

// ═══════════════════════════════════════════════════════════════════════════
// TYPE EXPORTS
// ═══════════════════════════════════════════════════════════════════════════

export type Node = z.infer<typeof NodeSchema>;
export type Edge = z.infer<typeof EdgeSchema>;
export type Pipeline = z.infer<typeof PipelineSchema>;
export type ExecutionForm = z.infer<typeof ExecutionFormSchema>;

/**
 * Validation helper functions
 */

function validate<T>(schema: z.ZodSchema<T>, data: unknown): { valid: boolean; errors?: Record<string, string[]> } {
  const result = schema.safeParse(data);
  if (result.success) {
    return { valid: true };
  }
  const flattened = z.flattenError(result.error);
  const errors: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(flattened.fieldErrors)) {
    if (value && Array.isArray(value)) {
      errors[key] = value;
    }
  }
  return { valid: false, errors };
}

export function validatePipeline(data: unknown) {
  return validate(PipelineSchema, data);
}

export function validateNode(data: unknown) {
  return validate(NodeSchema, data);
}

const IOSchema = z.object({
  name: z.string().min(1, "Name required"),
  format: z.string().min(1, "Format required"),
  path: z.string().optional(),
  filepath: z.string().optional(),
});

export function validateInputOutput(io: unknown) {
  return validate(IOSchema, io);
}

const GlobalSettingsSchema = z.object({
  environment: z.string().optional(),
  workspace_root: z.string().optional(),
  log_level: z.enum(["DEBUG", "INFO", "WARNING", "ERROR"]).optional(),
});

export function validateGlobalSettings(settings: unknown) {
  return validate(GlobalSettingsSchema, settings);
}

export function isValidPythonIdentifier(name: string): boolean {
  return /^[a-z_][a-z0-9_]*$/i.test(name);
}

export function isValidPythonModule(path: string): boolean {
  return /^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$/i.test(path);
}

export function isValidFilePath(path: string): boolean {
  return !/[<>:"|?*]/.test(path);
}

export function isValidColumnName(name: string): boolean {
  return /^[a-z0-9_]+$/i.test(name);
}

export function isValidFriendlyName(name: string): boolean {
  return name.length >= 3 && name.length <= 50;
}

export function getErrorMessage(error: any): string {
  if (typeof error === 'string') return error;
  if (error?.message) return error.message;
  return 'Unknown error';
}
