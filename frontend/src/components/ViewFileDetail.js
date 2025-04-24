import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import './css/ViewFileDetail.css';

const ViewFileDetail = () => {
  const { projectId, fileId } = useParams();
  const [viewFile, setViewFile] = useState(null);
  const [content, setContent] = useState('');
  const [viewSummaries, setViewSummaries] = useState({});
  const [appDetails, setAppDetails] = useState(null);
  const [projectDetails, setProjectDetails] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();
  const token = localStorage.getItem('access_token');

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`/api/viewfile/${fileId}/`, {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`Status ${res.status}`);
        const data = await res.json();
        setViewFile(data);
        setContent(data.content || '');
        setViewSummaries(data.view_summaries || {});
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [fileId, token]);

  useEffect(() => {
    if (viewFile?.app && !appDetails) {
      (async () => {
        try {
          const res = await fetch(
            `/api/apps/?project_id=${localStorage.getItem('project_id')}`,
            { headers: { 'Authorization': `Bearer ${token}` } }
          );
          const apps = await res.json();
          setAppDetails(apps.find(a => a.id === Number(viewFile.app)));
        } catch {}
      })();
    }
  }, [viewFile, appDetails, token]);

  useEffect(() => {
    if (!projectDetails) {
      (async () => {
        try {
          const res = await fetch(`/api/projects/${projectId}/`, {
            headers: { 'Authorization': `Bearer ${token}` },
          });
          if (res.ok) setProjectDetails(await res.json());
        } catch {}
      })();
    }
  }, [projectId, projectDetails, token]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await fetch(`/api/save-code-only/${fileId}/`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          content,
          view_summaries: viewSummaries,
        }),
      });
      if (!res.ok) throw new Error(`Save failed: ${res.status}`);
      const updated = await res.json();
      setViewFile(updated);
      alert('View file saved!');
     
    } catch (err) {
      alert(`Save error: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  if (loading)  return <p className="loading">Loading view file…</p>;
  if (error)    return <p className="error">Error: {error}</p>;
  if (!viewFile) return <p className="error">No view file found.</p>;

  const appName     = appDetails?.name    || 'Unknown App';
  const projectName = projectDetails?.name|| 'Unknown Project';

  return (
    <div className="view-file-detail-container">
      <header className="view-file-header">
        <h2>{`${projectName}/${appName}/views.py`}</h2>
      </header>

      <textarea
        className="view-file-textarea"
        value={content}
        onChange={e => setContent(e.target.value)}
        rows={20}
      />

      <div className="view-file-buttons">
        <button
          className="primary-btn"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
       
        <button
          className="secondary-btn"
          onClick={() => navigate(`/view-diagram/${viewFile.id}`)}
        >
          View Diagram
        </button>
      </div>

      {Object.keys(viewSummaries).length > 0 && (
        <section className="view-file-section">
          <h3>Individual View Summaries</h3>
          <ul>
            {Object.entries(viewSummaries).map(([name, sum]) => (
              <li key={name}>
                <strong>{name}:</strong> {sum || 'No summary'}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
};

export default ViewFileDetail;
