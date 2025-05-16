import axios from 'axios';
import React, { useEffect, useState } from 'react';
import './css/DiffModal.css';

export default function DiffModal({
  projectId,
  changeId,
  files,
  token,
  onApply,
  onCancel,
  onClose,
}) {
  const [beforeUrl, setBeforeUrl] = useState(null);
  const [afterUrl, setAfterUrl] = useState(null);
  const [loadingBefore, setLoadingBefore] = useState(true);
  const [loadingAfter, setLoadingAfter] = useState(true);
  const [error, setError] = useState(null);

  // Fetch the two preview URLs on mount
  useEffect(() => {
    const BACKEND = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000';
    const headers = { Authorization: `Bearer ${token}` };
    console.log('[DiffModal] Loading previews for change:', changeId);
    
    // Before preview
    setLoadingBefore(true);
    axios
      .post(
        `${BACKEND}/api/projects/${projectId}/preview/run/`,
        { mode: 'before' },
        { headers }
      )
      .then(res => {
        console.log('[DiffModal] Before preview URL:', res.data.url);
        setBeforeUrl(res.data.url);
        setLoadingBefore(false);
      })
      .catch(err => {
        console.error('[DiffModal] Error loading before preview:', err);
        setError(`Error loading before preview: ${err.message}`);
        setLoadingBefore(false);
      });

    // After preview  
    setLoadingAfter(true);
    axios
      .post(
        `${BACKEND}/api/projects/${projectId}/preview/run/`,
        { mode: 'after', change_id: changeId },
        { headers }
      )
      .then(res => {
        console.log('[DiffModal] After preview URL:', res.data.url);
        setAfterUrl(res.data.url);
        setLoadingAfter(false);
      })
      .catch(err => {
        console.error('[DiffModal] Error loading after preview:', err);
        setError(`Error loading after preview: ${err.message}`);
        setLoadingAfter(false);
      });
  }, [projectId, changeId, token]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="diff-modal modal-content xlarge-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Preview Changes</h3>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>

        <div className="modal-body preview-comparison">
          <div className="preview-pane">
            <h4>Before</h4>
            {error ? (
              <div className="preview-error">{error}</div>
            ) : loadingBefore ? (
              <div className="preview-loading">Loading before preview...</div>
            ) : beforeUrl ? (
              <iframe
                src={beforeUrl}
                className="preview-iframe"
                title="Before Preview"
                onError={() => setError('Error loading before preview')}
              />
            ) : (
              <div className="preview-error">Failed to load before preview</div>
            )}
          </div>

          <div className="preview-pane">
            <h4>After</h4>
            {error ? (
              <div className="preview-error">{error}</div>
            ) : loadingAfter ? (
              <div className="preview-loading">Loading after preview...</div>
            ) : afterUrl ? (
              <iframe
                src={afterUrl}
                className="preview-iframe"
                title="After Preview"
                onError={() => setError('Error loading after preview')}
              />
            ) : (
              <div className="preview-error">Failed to load after preview</div>
            )}
          </div>
        </div>

        <div className="modal-footer">
          <button className="primary-btn" onClick={onApply}>Apply Changes</button>
          <button className="secondary-btn" onClick={onCancel}>Discard Changes</button>
        </div>
      </div>
    </div>
  );
}
    