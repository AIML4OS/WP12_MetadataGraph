import { useState } from 'react';
import useGraphStore from '../store/graphStore';
import * as api from '../services/api';
import './ImpactReportPanel.css';

/**
 * ImpactReportPanel - Floating panel listing affected artefacts grouped by impact severity,
 * with an Export button that downloads a structured change-impact report (US-03).
 *
 * Self-hides when there is no active impact result.
 */
function ImpactReportPanel() {
  const { impactResult, clearImpact, setFocusNodeId } = useGraphStore();
  const [exporting, setExporting] = useState(false);

  if (!impactResult) return null;

  const changed = impactResult.changed_node || {};
  const summary = impactResult.summary || {};
  const groups = impactResult.groups || {};
  const breaking = groups.breaking || [];
  const annotation = groups['annotation-only'] || [];

  const handleExport = async () => {
    setExporting(true);
    try {
      const res = await api.getImpactReport(changed.id, impactResult.change_type);
      const report = res?.report || impactResult;
      const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `impact-report-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Error exporting impact report:', err);
    } finally {
      setExporting(false);
    }
  };

  const renderGroup = (title, items, severity) => {
    if (items.length === 0) return null;
    return (
      <div className="impact-panel-group">
        <div className={`impact-panel-group-title severity-${severity}`}>
          {title} ({items.length})
        </div>
        {items.map((item) => (
          <button
            key={item.id}
            className="impact-panel-item"
            title={item.path || ''}
            onClick={() => setFocusNodeId(item.id)}
          >
            <span className={`impact-panel-item-dot severity-${severity}`} />
            <span className="impact-panel-item-type">{item.type}</span>
            <span className="impact-panel-item-name">{item.name}</span>
          </button>
        ))}
      </div>
    );
  };

  return (
    <div className="impact-panel">
      <div className="impact-panel-header">
        <div className="impact-panel-title">Change impact</div>
        <button className="impact-panel-close" onClick={clearImpact} title="Clear impact view">
          &times;
        </button>
      </div>

      <div className="impact-panel-subhead">
        <div className="impact-panel-classification">{changed.name}</div>
        <div className="impact-panel-meta">
          {changed.version_before || changed.version_after ? (
            <span>
              {changed.version_before || '?'} → {changed.version_after || '?'} ·{' '}
            </span>
          ) : null}
          <span className={`impact-panel-change-type ct-${impactResult.change_type}`}>
            {impactResult.change_type}
          </span>
        </div>
        <div className="impact-panel-counts">
          {summary.total_affected || 0} affected · {summary.breaking || 0} breaking ·{' '}
          {summary['annotation-only'] || 0} annotation-only
        </div>
      </div>

      <div className="impact-panel-body">
        {renderGroup('Breaking', breaking, 'breaking')}
        {renderGroup('Annotation-only', annotation, 'annotation-only')}
        {breaking.length === 0 && annotation.length === 0 && (
          <div className="impact-panel-empty">No dependent artefacts found.</div>
        )}
      </div>

      <div className="impact-panel-actions">
        <button className="impact-panel-export" onClick={handleExport} disabled={exporting}>
          {exporting ? 'Exporting…' : 'Export report'}
        </button>
      </div>
    </div>
  );
}

export default ImpactReportPanel;
