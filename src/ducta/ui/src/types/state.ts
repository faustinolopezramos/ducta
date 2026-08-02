import type { Project } from './domain';

export interface AppState {
  projects: Project[];
  selectedProjectId: string | null;
}

export interface ReducerAction {
  type: string;
  payload?: unknown;
}

export interface FormState<T> {
  values: T;
  errors: Partial<Record<keyof T, string>>;
  touched: Partial<Record<keyof T, boolean>>;
  isSubmitting: boolean;
  isValid: boolean;
}

export interface PersistenceConfig {
  enabled: boolean;
  strategy: 'localStorage' | 'indexedDB' | 'hybrid';
  version: number;
  encryption?: boolean;
  keys: string[];
}
