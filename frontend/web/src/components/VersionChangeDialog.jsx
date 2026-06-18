import { useState, useEffect, useRef } from 'react';
import './ConfirmDialog.css';

/**
 * VersionChangeDialog - Pick the type of classification version change to simulate (US-03).
 *
 * Lets a data steward choose a breaking vs annotation-only change (and optionally a new
 * version label) before running the downstream impact assessment.
 */
function VersionChangeDialog({ classificationName, currentVersion, onConfirm, onCancel }) {
  const [changeType, setChangeType] = useState('breaking');
  const [newVersion, setNewVersion] = useState('');
  const dialogRef = useRef(null);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') onCancel();
  };

  return (
    <div className="confirm-dialog-overlay" onClick={onCancel}>
      <div
        ref={dialogRef}
        className="confirm-dialog"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
        tabIndex={-1}
      >
        <div className="confirm-dialog-header">
          <h3>Trigger version change</h3>
        </div>

        <div className="confirm-dialog-content">
          <p style={{ whiteSpace: 'pre-line', marginBottom: '0.75rem' }}>
            Simulate a version change on <strong>{classificationName}</strong>
            {currentVersion ? ` (current version: ${currentVersion})` : ''} and assess which
            downstream metadata artefacts are affected.
          </p>

          <label style={{ display: 'block', marginBottom: '0.4rem', fontWeight: 600 }}>
            Change type
          </label>
          <label style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start', marginBottom: '0.4rem' }}>
            <input
              type="radio"
              name="changeType"
              value="breaking"
              checked={changeType === 'breaking'}
              onChange={() => setChangeType('breaking')}
            />
            <span>
              <strong>Breaking change</strong> — codes are added/removed/remapped; dependent
              coded variables and tables must be reviewed.
            </span>
          </label>
          <label style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start', marginBottom: '0.8rem' }}>
            <input
              type="radio"
              name="changeType"
              value="annotation"
              checked={changeType === 'annotation'}
              onChange={() => setChangeType('annotation')}
            />
            <span>
              <strong>Annotation-only change</strong> — labels/descriptions only; no structural
              impact.
            </span>
          </label>

          <label style={{ display: 'block', marginBottom: '0.3rem', fontWeight: 600 }}>
            New version label (optional)
          </label>
          <input
            type="text"
            value={newVersion}
            onChange={(e) => setNewVersion(e.target.value)}
            placeholder="e.g. Rev. 2.1"
            style={{
              width: '100%',
              padding: '0.45rem 0.6rem',
              borderRadius: '6px',
              border: '1px solid #555',
              background: 'transparent',
              color: 'inherit',
            }}
          />
        </div>

        <div className="confirm-dialog-actions">
          <button className="confirm-dialog-button cancel" onClick={onCancel}>
            Cancel
          </button>
          <button
            className={`confirm-dialog-button ${changeType === 'breaking' ? 'danger' : 'primary'}`}
            onClick={() => onConfirm(changeType, newVersion.trim() || null)}
          >
            Assess impact
          </button>
        </div>
      </div>
    </div>
  );
}

export default VersionChangeDialog;
