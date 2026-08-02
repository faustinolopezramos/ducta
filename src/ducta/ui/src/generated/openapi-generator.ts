/**
 * OpenAPI Type Generation Setup
 * Sprint 3 M-2: OpenAPI Type Generation
 * Automatic TypeScript type generation from FastAPI OpenAPI spec
 */

import { exec } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

/**
 * OpenAPI Configuration
 */
export interface OpenAPIConfig {
  /** Backend API base URL */
  apiUrl: string;

  /** OpenAPI spec location (local path or remote URL) */
  specLocation: string;

  /** Output directory for generated types */
  outputDir: string;

  /** Package name for generated client */
  packageName: string;

  /** Enable TypeScript strict mode */
  strictMode?: boolean;

  /** API models to generate */
  generatorName?: string;
}

/**
 * Default configuration
 */
export const DEFAULT_CONFIG: OpenAPIConfig = {
  apiUrl: process.env.REACT_APP_API_URL || 'http://localhost:8000',
  // Prefer the versioned spec (offline, deterministic codegen). Generate it with
  // `python scripts/dump_openapi.py`. Override with OPENAPI_SPEC to fetch live.
  specLocation: process.env.OPENAPI_SPEC || './openapi.json',
  outputDir: './src/generated/api',
  packageName: '@ducta/api-client',
  strictMode: true,
  generatorName: 'typescript-fetch',
};

/**
 * OpenAPI Type Generator
 */
export class OpenAPITypeGenerator {
  private config: OpenAPIConfig;

  constructor(config: Partial<OpenAPIConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * Generate types from OpenAPI spec
   */
  async generate(): Promise<void> {
    console.log('[OpenAPI] Generating types from spec...');
    console.log(`  Spec: ${this.config.specLocation}`);
    console.log(`  Output: ${this.config.outputDir}`);

    // Ensure output directory exists
    if (!fs.existsSync(this.config.outputDir)) {
      fs.mkdirSync(this.config.outputDir, { recursive: true });
    }

    try {
      // Fetch OpenAPI spec
      const spec = await this.fetchSpec();

      // Validate spec
      this.validateSpec(spec);

      // Generate API client code
      await this.generateClient(spec);

      // Post-process generated files
      this.postProcess();

      console.log('[OpenAPI] ✅ Types generated successfully');
    } catch (error) {
      console.error('[OpenAPI] ❌ Generation failed:', error);
      throw error;
    }
  }

  /**
   * Fetch OpenAPI specification
   */
  private async fetchSpec(): Promise<any> {
    const fs = await import('fs/promises');

    // Local file (preferred): the versioned, offline spec.
    if (!this.config.specLocation.startsWith('http')) {
      try {
        const content = await fs.readFile(this.config.specLocation, 'utf-8');
        return JSON.parse(content);
      } catch {
        // Spec not generated yet — fall back to a live API if reachable.
        console.warn(
          `[OpenAPI] Local spec '${this.config.specLocation}' not found; ` +
            `falling back to ${this.config.apiUrl}/openapi.json. ` +
            `Generate the spec with: python scripts/dump_openapi.py`
        );
        const liveResponse = await fetch(`${this.config.apiUrl}/openapi.json`);
        if (!liveResponse.ok) {
          throw new Error(
            `Failed to load OpenAPI spec: no local file and live fetch ` +
              `returned ${liveResponse.statusText}`
          );
        }
        return liveResponse.json();
      }
    }

    // Explicit remote URL (OPENAPI_SPEC override).
    const response = await fetch(this.config.specLocation);

    if (!response.ok) {
      throw new Error(`Failed to fetch OpenAPI spec: ${response.statusText}`);
    }

    return response.json();
  }

  /**
   * Validate OpenAPI specification
   */
  private validateSpec(spec: any): void {
    const requiredFields = ['openapi', 'info', 'paths'];

    for (const field of requiredFields) {
      if (!spec[field]) {
        throw new Error(`Invalid OpenAPI spec: missing '${field}' field`);
      }
    }

    console.log(`[OpenAPI] ✅ Spec validated (v${spec.openapi})`);
    console.log(`  Title: ${spec.info.title}`);
    console.log(`  Version: ${spec.info.version}`);
    console.log(`  Paths: ${Object.keys(spec.paths).length}`);
  }

  /**
   * Generate API client from spec
   */
  private async generateClient(spec: any): Promise<void> {
    // Write spec to temporary file for generator
    const specPath = path.join(this.config.outputDir, '_openapi-spec.json');
    fs.writeFileSync(specPath, JSON.stringify(spec, null, 2));

    // Generate using openapi-generator-cli
    const command = `
      openapi-generator-cli generate \\
        -i ${specPath} \\
        -g ${this.config.generatorName} \\
        -o ${this.config.outputDir} \\
        -c openapi-generator-config.json \\
        --skip-validate-spec
    `;

    return new Promise((resolve, reject) => {
      exec(command, (error, _stdout, stderr) => {
        if (error) {
          reject(new Error(`Generator failed: ${stderr}`));
          return;
        }

        // Clean up spec file
        fs.unlinkSync(specPath);

        resolve();
      });
    });
  }

  /**
   * Post-process generated files
   */
  private postProcess(): void {
    // Generate index.ts for exports
    this.generateIndexFile();

    // Generate types-only file
    this.generateTypesFile();

    // Create API client wrapper
    this.generateClientWrapper();

    console.log('[OpenAPI] 📦 Post-processing complete');
  }

  /**
   * Generate index.ts for convenient imports
   */
  private generateIndexFile(): void {
    const indexPath = path.join(this.config.outputDir, 'index.ts');

    const content = `/**
 * Auto-generated API client from OpenAPI spec
 * This file is regenerated on each 'npm run generate-api' call
 * DO NOT EDIT - changes will be overwritten
 */

// Export all models and APIs
export * from './models/index';
export * from './apis/index';

// Export configuration
export { Configuration } from './configuration';

// Export types
export type { RequestArgs } from './base';

// Default client instance
import { Configuration } from './configuration';
import { DefaultApi } from './apis';

const config = new Configuration({
  basePath: '${this.config.apiUrl}',
  apiKey: (name: string, scopes?: string[]): string | Promise<string> => {
    const token = localStorage.getItem('auth_token');
    return token || '';
  },
});

export const apiClient = new DefaultApi(config);
`;

    fs.writeFileSync(indexPath, content);
    console.log(`  ✓ Generated ${indexPath}`);
  }

  /**
   * Generate types-only export file
   */
  private generateTypesFile(): void {
    const typesPath = path.join(this.config.outputDir, 'types.ts');

    const content = `/**
 * TypeScript type definitions from OpenAPI spec
 * Use these for type-safe API interactions
 */

export * from './models/index';
`;

    fs.writeFileSync(typesPath, content);
    console.log(`  ✓ Generated ${typesPath}`);
  }

  /**
   * Generate wrapper for type-safe API calls
   */
  private generateClientWrapper(): void {
    const wrapperPath = path.join(this.config.outputDir, 'client.ts');

    const content = `/**
 * Type-safe API client wrapper
 * Provides better TypeScript support and error handling
 */

import axios, { AxiosError, AxiosInstance } from 'axios';
import { apiClient } from './index';

export interface ApiError {
  status: number;
  message: string;
  details?: any;
}

export class DuctaAPIClient {
  private client: AxiosInstance;

  constructor(baseURL: string = '${this.config.apiUrl}') {
    this.client = axios.create({
      baseURL,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Add auth token to requests
    this.client.interceptors.request.use((config) => {
      const token = localStorage.getItem('auth_token');
      if (token) {
        config.headers.Authorization = \`Bearer \${token}\`;
      }
      return config;
    });
  }

  /**
   * Make API call with error handling
   */
  async call<T>(fn: () => Promise<T>): Promise<T> {
    try {
      return await fn();
    } catch (error) {
      throw this.handleError(error);
    }
  }

  /**
   * Handle API errors
   */
  private handleError(error: any): ApiError {
    if (axios.isAxiosError(error)) {
      return {
        status: error.response?.status || 500,
        message: error.response?.data?.detail || error.message,
        details: error.response?.data,
      };
    }

    return {
      status: 500,
      message: 'Unknown error',
    };
  }
}

export const api = new DuctaAPIClient();
`;

    fs.writeFileSync(wrapperPath, content);
    console.log(`  ✓ Generated ${wrapperPath}`);
  }
}

/**
 * CLI Command: Generate API types
 *
 * Usage:
 * ```
 * npm run generate-api
 * ```
 */
export async function generateAPITypes(): Promise<void> {
  const generator = new OpenAPITypeGenerator();
  await generator.generate();
}

/**
 * Watch for spec changes and regenerate
 */
export function watchOpenAPISpec(specPath: string, onUpdate: () => void): void {
  fs.watch(specPath, (eventType, _filename) => {
    if (eventType === 'change') {
      console.log(`[OpenAPI] Spec changed, regenerating...`);
      generateAPITypes().then(() => {
        onUpdate();
      });
    }
  });
}
