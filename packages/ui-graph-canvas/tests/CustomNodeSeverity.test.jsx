import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('reactflow', () => ({
  Handle: ({ type }) => <div data-testid={`handle-${type}`} />,
  Position: { Top: 'top', Bottom: 'bottom' },
}));

import CustomNode from '../src/components/CustomNode';

describe('CustomNode change-impact severity (US-03)', () => {
  it('applies the breaking severity class and badge', () => {
    render(
      <CustomNode
        id="n1"
        selected={false}
        data={{ label: 'economic_activity', nodeType: 'InstanceVariable', color: '#14B8A6', severity: 'breaking' }}
      />
    );
    const node = screen.getByText('economic_activity').closest('.graph-custom-node');
    expect(node.classList.contains('severity-breaking')).toBe(true);
    expect(screen.getByText('Breaking change')).toBeInTheDocument();
  });

  it('applies the annotation-only severity class and badge', () => {
    render(
      <CustomNode
        id="n2"
        selected={false}
        data={{ label: 'Output table', nodeType: 'DataSet', color: '#06B6D4', severity: 'annotation-only' }}
      />
    );
    const node = screen.getByText('Output table').closest('.graph-custom-node');
    expect(node.classList.contains('severity-annotation-only')).toBe(true);
    expect(screen.getByText('Annotation only')).toBeInTheDocument();
  });

  it('marks the changed classification as source without a severity badge', () => {
    render(
      <CustomNode
        id="n3"
        selected={false}
        data={{ label: 'NACE Rev. 2', nodeType: 'CodeList', color: '#FBBF24', severity: 'source' }}
      />
    );
    const node = screen.getByText('NACE Rev. 2').closest('.graph-custom-node');
    expect(node.classList.contains('severity-source')).toBe(true);
    expect(screen.queryByText('Breaking change')).toBeNull();
    expect(screen.queryByText('Annotation only')).toBeNull();
  });

  it('adds no severity class when no severity is present', () => {
    render(
      <CustomNode
        id="n4"
        selected={false}
        data={{ label: 'Plain', nodeType: 'Actor', color: '#3B82F6' }}
      />
    );
    const node = screen.getByText('Plain').closest('.graph-custom-node');
    expect([...node.classList].some((c) => c.startsWith('severity-'))).toBe(false);
  });
});
