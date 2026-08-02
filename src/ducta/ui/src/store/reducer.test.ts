import { describe, it, expect } from 'vitest';
import { reducer, initialState, selectPresent } from './reducer'; // Adjusted import based on your reducer structure

// Assuming reducer returns { past, present, future }
// If reducer matches the new immer version, it handles undo/redo wrapper logic + core reducer logic

describe('Reducer Logic', () => {
    it('should handle ADD_PROJECT', () => {
        const action = {
            type: 'ADD_PROJECT' as const,
            payload: { id: 'p1', name: 'Project 1', pipelines: [] }
        };
        const nextState = reducer(initialState, action);

        const present = selectPresent(nextState);

        expect(present.projects).toHaveLength(initialState.present.projects.length + 1);
        expect(present.selectedProjectId).toBe('p1');
        // Should update history (undo stack)
        expect(nextState.past).toHaveLength(1);
    });

    it('should handle UNDO after ADD_PROJECT', () => {
        const action = {
            type: 'ADD_PROJECT' as const,
            payload: { id: 'p1', name: 'Project 1', pipelines: [] }
        };
        const statedAfterAdd = reducer(initialState, action);

        const undoAction = { type: 'UNDO' as const };
        const statedAfterUndo = reducer(statedAfterAdd, undoAction);

        const present = selectPresent(statedAfterUndo);
        expect(present.projects).toHaveLength(initialState.present.projects.length);
        expect(statedAfterUndo.future).toHaveLength(1);
    });

    it('should ignore unknown actions', () => {
        const action = { type: 'UNKNOWN' } as any;
        const nextState = reducer(initialState, action);
        expect(nextState).toBe(initialState);
    });
});
