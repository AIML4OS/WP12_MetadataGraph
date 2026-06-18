import { useState, memo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Handle, Position } from 'reactflow';
import './CustomNode.css';

/**
 * CustomNode - A graph node component for displaying entities
 *
 * Props passed via data:
 * - label: Node display name
 * - summary: Short description (optional)
 * - nodeType: Type of node (Actor, Initiative, etc.)
 * - color: Node color
 * - isHighlighted: Whether node is highlighted
 * - severity: Change-impact severity ('breaking' | 'annotation-only' | 'source'), drives styling
 * - description: Full description for tooltip
 * - communities: Array of community names
 * - onExpand: Callback when expand button clicked
 * - onEdit: Callback when edit button clicked
 */
function CustomNode({ data, id, selected }) {
  const [showButtons, setShowButtons] = useState(false);
  const [showTooltip, setShowTooltip] = useState(false);
  const [tooltipPos, setTooltipPos] = useState(null);
  const nodeRef = useRef(null);

  const handleExpand = (e) => {
    e.stopPropagation();
    if (data.onExpand) {
      data.onExpand(id, data);
    }
  };

  const handleEdit = (e) => {
    e.stopPropagation();
    if (data.onEdit) {
      data.onEdit(id, data);
    }
  };

  const severityClass = data.severity ? `severity-${data.severity}` : '';

  return (
    <div
      ref={nodeRef}
      className={`graph-custom-node ${data.isHighlighted ? 'highlighted' : ''} ${selected ? 'selected' : ''} ${severityClass}`}
      style={{ borderColor: data.color }}
      onMouseEnter={() => {
        setShowButtons(true);
        if (nodeRef.current) {
          const rect = nodeRef.current.getBoundingClientRect();
          setTooltipPos({
            top: rect.bottom + 8,
            left: rect.left + (rect.width / 2),
          });
        }
        setShowTooltip(true);
      }}
      onMouseLeave={() => {
        setShowButtons(false);
        setShowTooltip(false);
        setTooltipPos(null);
      }}
    >
      <Handle type="target" position={Position.Top} />

      <div className="graph-node-header" style={{ backgroundColor: data.color }}>
        <span className="graph-node-type">{data.nodeType}</span>
      </div>

      <div className="graph-node-content">
        <div className="graph-node-label">{data.label}</div>
        {data.summary && (
          <div className="graph-node-summary">{data.summary}</div>
        )}
        {data.severity && data.severity !== 'source' && (
          <div className={`graph-node-severity-badge severity-badge-${data.severity}`}>
            {data.severity === 'breaking' ? 'Breaking change' : 'Annotation only'}
          </div>
        )}
      </div>

      {showButtons && (
        <>
          {data.onExpand && (
            <button
              className="graph-expand-button"
              onClick={handleExpand}
              title="Show related nodes"
            >
              +
            </button>
          )}
          {data.onEdit && (
            <button
              className="graph-edit-button"
              onClick={handleEdit}
              title="Edit node"
            >
              ✏️
            </button>
          )}
        </>
      )}

      {showTooltip && tooltipPos && (data.description || data.communities?.length > 0) && createPortal(
        <div
          className="graph-node-tooltip"
          style={{ top: `${tooltipPos.top}px`, left: `${tooltipPos.left}px`, zIndex: 99999 }}
        >
          <div className="tooltip-header">
            <strong>{data.nodeType}:</strong> {data.label}
          </div>
          {data.description && (
            <div className="tooltip-description">
              {data.description}
            </div>
          )}
          {data.communities && data.communities.length > 0 && (
            <div className="tooltip-communities">
              <strong>Communities:</strong> {data.communities.join(', ')}
            </div>
          )}
        </div>,
        document.body
      )}

      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

export default memo(CustomNode);
