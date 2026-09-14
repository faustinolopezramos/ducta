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

describe('HYDRATE_PROJECTS', () => {
    const server = (id: string, over: Record<string, unknown> = {}) => ({
        id, name: id, pipelines: [], pipelineCount: 3, ...over,
    });

    it('adds projects the store does not have', () => {
        const next = reducer(initialState, {
            type: 'HYDRATE_PROJECTS' as const,
            projects: [server('p1'), server('p2')],
        });
        expect(selectPresent(next).projects.map((p) => p.id)).toEqual(['p1', 'p2']);
    });

    it('refreshes the pipeline count on a project it already has', () => {
        // The hydrator used to skip existing projects entirely, so a card's
        // count went stale the moment a pipeline was created.
        const added = reducer(initialState, {
            type: 'ADD_PROJECT' as const,
            payload: server('p1', { pipelineCount: 3 }),
        });
        const next = reducer(added, {
            type: 'HYDRATE_PROJECTS' as const,
            projects: [server('p1', { pipelineCount: 4 })],
        });
        const present = selectPresent(next);
        expect(present.projects).toHaveLength(1);
        expect(present.projects[0].pipelineCount).toBe(4);
    });

    it('leaves locally loaded pipelines alone', () => {
        // The server list reports a count, never the graph; a project already
        // opened must not have its loaded pipelines wiped by a refresh.
        const added = reducer(initialState, {
            type: 'ADD_PROJECT' as const,
            payload: server('p1', { pipelines: [{ id: 'pl1' }] as never }),
        });
        const next = reducer(added, {
            type: 'HYDRATE_PROJECTS' as const,
            projects: [server('p1')],
        });
        expect(selectPresent(next).projects[0].pipelines).toHaveLength(1);
    });

    it('does not push undo history', () => {
        const next = reducer(initialState, {
            type: 'HYDRATE_PROJECTS' as const,
            projects: [server('p1')],
        });
        expect(next.past).toHaveLength(0);
    });
});

describe('HYDRATE_PIPELINES', () => {
    const pipeline = (id: string, over: Record<string, unknown> = {}) => ({
        id, name: id, nodes: [], active: true,
        createdAt: 0, updatedAt: 0, ...over,
    });

    function withProject(pipelines: ReturnType<typeof pipeline>[]) {
        return reducer(initialState, {
            type: 'ADD_PROJECT' as const,
            payload: { id: 'p1', name: 'p1', pipelines: pipelines as never },
        });
    }

    it('adds pipelines the project does not have, marked persisted', () => {
        const base = withProject([]);
        const next = reducer(base, {
            type: 'HYDRATE_PIPELINES' as const,
            projectId: 'p1',
            pipelines: [pipeline('pl1', { persisted: true })] as never,
        });
        const pipelines = selectPresent(next).projects[0].pipelines;
        expect(pipelines).toHaveLength(1);
        expect((pipelines[0] as any).persisted).toBe(true);
    });

    it('leaves a never-persisted local pipeline alone when the server does not list it', () => {
        // Created locally, create request still in flight — must not vanish
        // just because this hydration's list doesn't include it yet.
        const base = withProject([pipeline('draft1')]);
        const next = reducer(base, {
            type: 'HYDRATE_PIPELINES' as const,
            projectId: 'p1',
            pipelines: [] as never,
        });
        expect(selectPresent(next).projects[0].pipelines.map((p) => p.id)).toEqual(['draft1']);
    });

    it('removes a previously-persisted pipeline the server no longer lists', () => {
        // Confirmed by an earlier hydration, then deleted elsewhere (another
        // tab/client) — must disappear here too, not stay stuck forever.
        const base = withProject([pipeline('pl1', { persisted: true })]);
        const next = reducer(base, {
            type: 'HYDRATE_PIPELINES' as const,
            projectId: 'p1',
            pipelines: [] as never,
        });
        expect(selectPresent(next).projects[0].pipelines).toHaveLength(0);
    });

    it('removes a persisted pipeline even when other pipelines are still listed', () => {
        const base = withProject([
            pipeline('pl1', { persisted: true }),
            pipeline('pl2', { persisted: true }),
        ]);
        const next = reducer(base, {
            type: 'HYDRATE_PIPELINES' as const,
            projectId: 'p1',
            pipelines: [pipeline('pl2', { persisted: true })] as never,
        });
        expect(selectPresent(next).projects[0].pipelines.map((p) => p.id)).toEqual(['pl2']);
    });

    it('keeps client-only run bookkeeping when updating an existing pipeline', () => {
        const base = withProject([
            pipeline('pl1', { persisted: true, lastRun: 'yesterday', runStatus: 'success' }),
        ]);
        const next = reducer(base, {
            type: 'HYDRATE_PIPELINES' as const,
            projectId: 'p1',
            pipelines: [pipeline('pl1', { persisted: true, description: 'updated' })] as never,
        });
        const pl = selectPresent(next).projects[0].pipelines[0];
        expect(pl.description).toBe('updated');
        expect(pl.lastRun).toBe('yesterday');
        expect(pl.runStatus).toBe('success');
    });
});
