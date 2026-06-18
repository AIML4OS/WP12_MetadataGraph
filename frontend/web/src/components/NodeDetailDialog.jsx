import { useEffect, useState } from 'react';
import useGraphStore from '../store/graphStore';
import { useI18n } from '../i18n';
import * as api from '../services/api';
import './NodeDetailDialog.css';

const BASE_FIELDS = new Set(['name', 'description', 'summary', 'tags', 'subtypes', 'metadata', 'identifier']);

const FIELD_LABELS = {
  identifier: 'Resource link (URL)',
  repo: 'Repository URL',
  start_date: 'Start date',
  end_date: 'End date',
  effective_date: 'Effective date',
  target_date: 'Target date',
};

function formatFieldLabel(field) {
  return FIELD_LABELS[field] || field.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function asUrl(value) {
  if (typeof value !== 'string') return null;
  if (value.startsWith('http://') || value.startsWith('https://')) return value;
  if (value.startsWith('www.')) return `https://${value}`;
  return null;
}

function NodeDetailDialog({ node, onClose, onEdit }) {
  const {
    getNodeColor, schema,
    impactResult, affectedSeverity, explanationCache, setNodeExplanation,
  } = useGraphStore();
  const { t } = useI18n();

  const data = node?.data || {};
  const nodeType = data.type || data.nodeType || '';
  const color = getNodeColor(nodeType);

  // ===== Inline LLM explanation (US-03) =====
  const nodeId = node?.id || data.id;
  const severity = affectedSeverity?.[nodeId];
  const cachedExplanation = explanationCache?.[nodeId];
  const [explLoading, setExplLoading] = useState(false);
  const [explError, setExplError] = useState(null);

  const buildImpactContext = () => {
    if (!impactResult || !severity || severity === 'source') return null;
    const affected = (impactResult.affected || []).find(a => a.id === nodeId);
    const changed = impactResult.changed_node || {};
    return {
      classification_name: changed.name,
      changed_name: changed.name,
      version_before: changed.version_before,
      version_after: changed.version_after,
      change_type: impactResult.change_type,
      relationship_path: affected?.path,
      severity,
    };
  };

  const handleExplain = async () => {
    if (!nodeId) return;
    setExplLoading(true);
    setExplError(null);
    try {
      const res = await api.explainNode(nodeId, buildImpactContext());
      setNodeExplanation(nodeId, res.explanation || '');
    } catch (err) {
      console.error('Error generating explanation:', err);
      setExplError('Could not generate explanation');
    } finally {
      setExplLoading(false);
    }
  };

  // Schema-defined extra fields for this node type (stored in metadata by backend)
  const schemaFields = schema?.node_types?.[nodeType]?.fields || [];
  const extraFieldNames = schemaFields.filter(f => !BASE_FIELDS.has(f));
  const extraFields = extraFieldNames
    .map(f => ({ key: f, value: data.metadata?.[f] ?? data[f] ?? null }))
    .filter(({ value }) => value !== null && value !== '');

  // Keys from metadata that are NOT schema extra fields (raw system metadata)
  const extraFieldSet = new Set(extraFieldNames);
  const rawMetadataEntries = Object.entries(data.metadata || {})
    .filter(([k]) => !extraFieldSet.has(k) &&
      !['identifier', 'node_ids', 'positions', 'edge_ids', 'edges', 'groups'].includes(k));

  // Collect links from metadata or identifier field
  const identifier = data.identifier || data.metadata?.identifier || '';
  const hasLink = identifier && (
    identifier.startsWith('http://') ||
    identifier.startsWith('https://') ||
    identifier.startsWith('www.')
  );
  const linkUrl = hasLink
    ? (identifier.startsWith('www.') ? `https://${identifier}` : identifier)
    : null;

  useEffect(() => {
    const handleEsc = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleEsc);
    return () => document.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  return (
    <div className="node-detail-overlay" onClick={onClose}>
      <div className="node-detail-dialog" onClick={e => e.stopPropagation()}>
        <header className="node-detail-header">
          <div className="node-detail-header-title">
            <span
              className="node-detail-type-dot"
              style={{ backgroundColor: color }}
            />
            <div>
              <span className="node-detail-type-label" style={{ color }}>
                {nodeType}
              </span>
              <h2>{data.name || data.label || t('detail.unknown_node')}</h2>
            </div>
          </div>
          <button className="close-button" onClick={onClose}>&times;</button>
        </header>

        <div className="node-detail-body">
          {data.summary && (
            <div className="node-detail-section">
              <label>{t('detail.summary')}</label>
              <p className="node-detail-summary">{data.summary}</p>
            </div>
          )}

          {data.description && (
            <div className="node-detail-section">
              <label>{t('detail.description')}</label>
              <p className="node-detail-description">{data.description}</p>
            </div>
          )}

          {data.tags && data.tags.length > 0 && (
            <div className="node-detail-section">
              <label>{t('detail.tags')}</label>
              <div className="node-detail-tags">
                {data.tags.map((tag, i) => (
                  <span key={i} className="node-detail-tag">{tag}</span>
                ))}
              </div>
            </div>
          )}

          {linkUrl && (
            <div className="node-detail-section">
              <label>{t('node_fields.identifier')}</label>
              <a
                href={linkUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="node-detail-link"
              >
                {identifier}
              </a>
            </div>
          )}

          {identifier && !hasLink && (
            <div className="node-detail-section">
              <label>{t('node_fields.identifier')}</label>
              <p className="node-detail-text">{identifier}</p>
            </div>
          )}

          {extraFields.map(({ key, value }) => {
            const url = asUrl(value);
            return (
              <div key={key} className="node-detail-section">
                <label>{formatFieldLabel(key)}</label>
                {url ? (
                  <a href={url} target="_blank" rel="noopener noreferrer" className="node-detail-link">
                    {value}
                  </a>
                ) : (
                  <p className="node-detail-text">{String(value)}</p>
                )}
              </div>
            );
          })}

          {rawMetadataEntries.length > 0 && (
            <div className="node-detail-section">
              <label>{t('detail.metadata')}</label>
              <div className="node-detail-metadata">
                {rawMetadataEntries.map(([key, value]) => (
                  <div key={key} className="node-detail-meta-item">
                    <span className="node-detail-meta-key">{key}:</span>
                    <span className="node-detail-meta-value">
                      {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="node-detail-section node-detail-explanation">
            <div className="node-detail-explanation-head">
              <label>Explanation</label>
              {severity && severity !== 'source' && (
                <span className={`node-detail-severity-pill severity-${severity}`}>
                  {severity === 'breaking' ? 'Breaking change' : 'Annotation only'}
                </span>
              )}
            </div>
            {cachedExplanation ? (
              <p className="node-detail-explanation-text">{cachedExplanation}</p>
            ) : (
              <p className="node-detail-explanation-hint">
                {severity && severity !== 'source'
                  ? 'Generate an LLM explanation of what must be reviewed for this affected artefact.'
                  : 'Generate an LLM plain-language explanation of this entity.'}
              </p>
            )}
            {explError && <p className="node-detail-explanation-error">{explError}</p>}
            <button
              className="node-detail-explanation-button"
              onClick={handleExplain}
              disabled={explLoading}
            >
              {explLoading
                ? 'Generating…'
                : cachedExplanation ? 'Regenerate explanation' : 'Generate explanation'}
            </button>
          </div>
        </div>

        <div className="node-detail-actions">
          <button className="secondary" onClick={onClose}>
            {t('detail.close')}
          </button>
          {onEdit && (
            <button
              className="primary"
              onClick={() => onEdit(node.id, data)}
            >
              {t('detail.edit')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default NodeDetailDialog;
