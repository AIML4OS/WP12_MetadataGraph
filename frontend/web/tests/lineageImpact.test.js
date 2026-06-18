import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock the API module the store calls (US-03 lineage/impact actions).
vi.mock('../src/services/api', () => ({
  getLineage: vi.fn(),
  assessImpact: vi.fn(),
  getImpactReport: vi.fn(),
  explainNode: vi.fn(),
}));

import useGraphStore from '../src/store/graphStore';
import * as api from '../src/services/api';

describe('graphStore lineage & impact (US-03)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useGraphStore.setState({
      nodes: [],
      edges: [],
      highlightedNodeIds: [],
      lineageMode: false,
      affectedSeverity: {},
      impactResult: null,
      explanationCache: {},
    });
  });

  it('loadLineage renders the subgraph and enters lineage mode', async () => {
    api.getLineage.mockResolvedValue({
      success: true,
      nodes: [
        { id: 'ds', type: 'DataSet', name: 'Out' },
        { id: 'step', type: 'ProcessStep', name: 'Agg' },
      ],
      edges: [{ id: 'e', source: 'step', target: 'ds', type: 'PRODUCES_OUTPUT' }],
    });

    await useGraphStore.getState().loadLineage('ds');

    const s = useGraphStore.getState();
    expect(api.getLineage).toHaveBeenCalledWith('ds');
    expect(s.lineageMode).toBe(true);
    expect(s.nodes.map((n) => n.id)).toEqual(expect.arrayContaining(['ds', 'step']));
    expect(s.impactResult).toBeNull();
  });

  it('runImpact builds the severity map and merges the impact subgraph', async () => {
    useGraphStore.setState({ nodes: [{ id: 'nace', type: 'CodeList', name: 'NACE' }], edges: [] });
    api.assessImpact.mockResolvedValue({
      success: true,
      change_type: 'breaking',
      summary: { total_affected: 2, breaking: 1, 'annotation-only': 1 },
      affected: [
        { id: 'var', severity: 'breaking' },
        { id: 'ds', severity: 'annotation-only' },
      ],
      nodes: [
        { id: 'var', type: 'InstanceVariable', name: 'v' },
        { id: 'ds', type: 'DataSet', name: 'd' },
      ],
      edges: [],
      changed_node: { id: 'nace', name: 'NACE' },
    });

    await useGraphStore.getState().runImpact('nace', 'breaking', 'Rev. 2.1');

    const s = useGraphStore.getState();
    expect(api.assessImpact).toHaveBeenCalledWith('nace', 'breaking', 'Rev. 2.1');
    // changed classification is tagged 'source'; affected nodes get their severity
    expect(s.affectedSeverity).toMatchObject({ var: 'breaking', ds: 'annotation-only', nace: 'source' });
    expect(s.impactResult.summary.breaking).toBe(1);
    expect(s.lineageMode).toBe(true);
    expect(s.nodes.map((n) => n.id)).toEqual(expect.arrayContaining(['nace', 'var', 'ds']));
  });

  it('clearImpact resets impact state', () => {
    useGraphStore.setState({
      impactResult: { x: 1 },
      affectedSeverity: { a: 'breaking' },
      lineageMode: true,
    });

    useGraphStore.getState().clearImpact();

    const s = useGraphStore.getState();
    expect(s.impactResult).toBeNull();
    expect(s.affectedSeverity).toEqual({});
    expect(s.lineageMode).toBe(false);
  });

  it('setNodeExplanation caches an explanation by node id', () => {
    useGraphStore.getState().setNodeExplanation('n1', 'because the classification changed');
    expect(useGraphStore.getState().explanationCache.n1).toBe('because the classification changed');
  });
});
