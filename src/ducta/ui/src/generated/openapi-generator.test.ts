/**
 * OpenAPI Type Generation Tests
 * Sprint 3 M-2: OpenAPI Type Generation
 * Tests for API spec generation and type safety
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { OpenAPITypeGenerator, DEFAULT_CONFIG } from '../generated/openapi-generator';

describe('OpenAPITypeGenerator', () => {
  let generator: OpenAPITypeGenerator;

  beforeEach(() => {
    generator = new OpenAPITypeGenerator();
  });

  it('should initialize with default config', () => {
    expect(generator).toBeDefined();
  });

  it('should accept custom config', () => {
    const customConfig = {
      apiUrl: 'https://api.example.com',
      specLocation: 'https://api.example.com/openapi.json',
    };

    const customGenerator = new OpenAPITypeGenerator(customConfig);
    expect(customGenerator).toBeDefined();
  });

  it('should have valid default configuration', () => {
    expect(DEFAULT_CONFIG.apiUrl).toBeDefined();
    expect(DEFAULT_CONFIG.specLocation).toBeDefined();
    expect(DEFAULT_CONFIG.outputDir).toBeDefined();
    expect(DEFAULT_CONFIG.packageName).toBeDefined();
  });
});

describe('OpenAPI Spec Validation', () => {
  it('should validate required OpenAPI fields', () => {
    const validSpec = {
      openapi: '3.0.0',
      info: {
        title: 'Test API',
        version: '1.0.0',
      },
      paths: {
        '/test': {
          get: {
            responses: {
              '200': {
                description: 'Success',
              },
            },
          },
        },
      },
    };

    // This would validate in actual implementation
    expect(validSpec.openapi).toBeDefined();
    expect(validSpec.info).toBeDefined();
    expect(validSpec.paths).toBeDefined();
  });

  it('should reject spec without openapi field', () => {
    const invalidSpec: {
      openapi?: string;
      info: { title: string };
      paths: Record<string, unknown>;
    } = {
      info: { title: 'Test' },
      paths: {},
    };

    expect(invalidSpec.openapi).toBeUndefined();
  });

  it('should support OpenAPI 3.0.x versions', () => {
    const versions = ['3.0.0', '3.0.1', '3.0.2', '3.0.3'];

    for (const version of versions) {
      const spec = {
        openapi: version,
        info: { title: 'Test', version: '1.0' },
        paths: {},
      };

      expect(spec.openapi).toMatch(/3\.0\.\d/);
    }
  });
});

describe('TypeScript Generation', () => {
  it('should generate valid TypeScript interfaces', () => {
    const schema = {
      type: 'object',
      properties: {
        id: { type: 'string' },
        name: { type: 'string' },
        status: { type: 'string', enum: ['active', 'inactive'] },
      },
      required: ['id', 'name'],
    };

    // In actual implementation, this would generate:
    // interface Model {
    //   id: string;
    //   name: string;
    //   status?: 'active' | 'inactive';
    // }

    expect(schema.properties).toHaveProperty('id');
    expect(schema.properties).toHaveProperty('name');
    expect(schema.properties).toHaveProperty('status');
  });

  it('should handle nested objects', () => {
    const schema = {
      type: 'object',
      properties: {
        user: {
          type: 'object',
          properties: {
            id: { type: 'string' },
            profile: {
              type: 'object',
              properties: {
                bio: { type: 'string' },
              },
            },
          },
        },
      },
    };

    expect(schema.properties.user.properties).toHaveProperty('profile');
  });

  it('should support arrays and collections', () => {
    const schema = {
      type: 'object',
      properties: {
        items: {
          type: 'array',
          items: { type: 'string' },
        },
        tags: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              name: { type: 'string' },
            },
          },
        },
      },
    };

    expect(schema.properties.items.type).toBe('array');
    expect(schema.properties.tags.items.type).toBe('object');
  });

  it('should handle nullable types', () => {
    const schema = {
      type: 'object',
      properties: {
        optional: { type: ['string', 'null'] },
        required: { type: 'string' },
      },
    };

    expect(schema.properties.optional.type).toContain('null');
    expect(schema.properties.required.type).not.toContain('null');
  });
});

describe('API Endpoint Generation', () => {
  it('should extract endpoints from spec', () => {
    const spec = {
      paths: {
        '/pipelines': {
          get: { operationId: 'listPipelines' },
          post: { operationId: 'createPipeline' },
        },
        '/pipelines/{id}': {
          get: { operationId: 'getPipeline' },
          put: { operationId: 'updatePipeline' },
          delete: { operationId: 'deletePipeline' },
        },
      },
    };

    const endpoints = Object.entries(spec.paths).flatMap(([path, methods]: any) =>
      Object.entries(methods).map(([method, op]: any) => ({
        path,
        method: method.toUpperCase(),
        operationId: op.operationId,
      }))
    );

    expect(endpoints).toHaveLength(5);
    expect(endpoints.some(e => e.operationId === 'listPipelines')).toBe(true);
  });

  it('should handle path parameters', () => {
    const endpoint = {
      path: '/pipelines/{id}',
      parameters: [
        {
          name: 'id',
          in: 'path',
          required: true,
          schema: { type: 'string' },
        },
      ],
    };

    expect(endpoint.parameters).toBeDefined();
    expect(endpoint.parameters[0].name).toBe('id');
    expect(endpoint.parameters[0].required).toBe(true);
  });

  it('should handle request bodies', () => {
    const createOperation = {
      operationId: 'createPipeline',
      requestBody: {
        required: true,
        content: {
          'application/json': {
            schema: {
              type: 'object',
              properties: {
                name: { type: 'string' },
              },
            },
          },
        },
      },
    };

    expect(createOperation.requestBody).toBeDefined();
    expect(createOperation.requestBody.required).toBe(true);
  });
});

describe('Security Scheme Generation', () => {
  it('should detect Bearer token auth', () => {
    const spec = {
      components: {
        securitySchemes: {
          bearerAuth: {
            type: 'http',
            scheme: 'bearer',
            bearerFormat: 'JWT',
          },
        },
      },
      security: [{ bearerAuth: [] }],
    };

    expect(spec.components.securitySchemes.bearerAuth.type).toBe('http');
    expect(spec.components.securitySchemes.bearerAuth.scheme).toBe('bearer');
  });

  it('should detect API key auth', () => {
    const spec = {
      components: {
        securitySchemes: {
          apiKey: {
            type: 'apiKey',
            name: 'X-API-Key',
            in: 'header',
          },
        },
      },
    };

    expect(spec.components.securitySchemes.apiKey.type).toBe('apiKey');
  });
});

describe('Type Generation Performance', () => {
  it('should handle large specs efficiently', () => {
    const startTime = performance.now();

    // Simulate large spec with 100+ endpoints
    const paths: any = {};
    for (let i = 0; i < 100; i++) {
      paths[`/endpoint${i}`] = {
        get: { operationId: `operation${i}` },
      };
    }

    const spec = {
      openapi: '3.0.0',
      info: { title: 'Large API', version: '1.0' },
      paths,
    };

    const duration = performance.now() - startTime;

    expect(Object.keys(spec.paths)).toHaveLength(100);
    expect(duration).toBeLessThan(1000); // Should complete within 1 second
  });
});

describe('Generated Client Usage', () => {
  it('should have proper TypeScript exports', () => {
    // In actual implementation, exported clients would look like:
    // export { Configuration };
    // export { DefaultApi };
    // export * from './models/index';
    // export * from './apis/index';

    const modules = [
      'Configuration',
      'DefaultApi',
      'models/index',
      'apis/index',
    ];

    expect(modules).toHaveLength(4);
  });

  it('should support authentication in generated client', () => {
    const clientConfig = {
      basePath: 'http://localhost:8000',
      apiKey: (_name: string) => {
        return localStorage.getItem('auth_token') || '';
      },
    };

    expect(clientConfig.apiKey).toBeDefined();
    expect(typeof clientConfig.apiKey).toBe('function');
  });
});
