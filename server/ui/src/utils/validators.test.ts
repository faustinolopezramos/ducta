import { describe, it, expect } from 'vitest';
import { NodeSchema, PipelineSchema } from './validators';

describe('Validation Schemas', () => {
  describe('NodeSchema', () => {
    it('should allow hyphens and uppercase in node names', () => {
      const validNode = {
        id: 'node-1',
        name: 'My-Node_1',
        type: 'transform',
        module: 'nodes.transform',
        active: true,
        inputs: [],
        outputs: []
      };
      const result = NodeSchema.safeParse(validNode);
      expect(result.success).toBe(true);
    });

    it('should allow complex IO structures', () => {
      const nodeWithIO = {
        id: 'node-2',
        name: 'io_node',
        type: 'source',
        module: 'nodes.source',
        active: true,
        inputs: [
          { id: 'in1', name: 'input1', format: 'parquet', filepath: 'path/to/data', mode: 'read' }
        ],
        outputs: [
          { id: 'out1', name: 'output1', format: 'csv', filepath: 'path/to/save', mode: 'write' }
        ]
      };
      const result = NodeSchema.safeParse(nodeWithIO);
      expect(result.success).toBe(true);
    });

    it('should reject invalid characters in names', () => {
      const invalidNode = {
        id: 'node-3',
        name: 'Invalid Name!',
        type: 'sink',
        module: 'nodes.sink'
      };
      const result = NodeSchema.safeParse(invalidNode);
      expect(result.success).toBe(false);
    });
  });

  describe('PipelineSchema', () => {
    it('should allow hyphens and uppercase in pipeline names', () => {
      const validPipeline = {
        id: 'pipe-1',
        name: 'Main-Pipeline',
        nodes: [
          { id: 'n1', name: 'node1', type: 'source', module: 'm', active: true }
        ],
        edges: [],
        active: true,
        createdAt: Date.now(),
        updatedAt: Date.now()
      };
      const result = PipelineSchema.safeParse(validPipeline);
      expect(result.success).toBe(true);
    });
  });
});
