import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import "./css/ModelFileDetail.css";

const ModelFileDetail = () => {
  const { fileId,projectId,appId } = useParams();
  const [modelFile, setModelFile] = useState(null);
  const [content, setContent] = useState('');
  const [appDetails, setAppDetails] = useState(null);
  const [projectDetails, setProjectDetails] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const navigate = useNavigate();
  const token = localStorage.getItem('access_token');

  useEffect(() => {
    const fetchModelFile = async () => {
      try {
        const response = await fetch(`/api/model-files/${fileId}/`, {
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
        });
        if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
        const data = await response.json();
        setModelFile(data);
        setContent(data.content || '');
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchModelFile();
  }, [fileId, token]);

  useEffect(() => {
    if (modelFile && modelFile.app && !appDetails) {
      const projectIdLocal = localStorage.getItem('project_id');
      fetch(`/api/apps/?project_id=${projectIdLocal}`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
      })
        .then((res) => res.json())
        .then((apps) => {
          const app = apps.find((a) => a.id === Number(modelFile.app));
          setAppDetails(app);
        })
        .catch(console.error);
    }
  }, [modelFile, appDetails, token]);

  useEffect(() => {
    if (!projectDetails) {
      const projectIdLocal = localStorage.getItem('project_id');
      fetch(`/api/projects/${projectIdLocal}/`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
      })
        .then((res) => res.json())
        .then(setProjectDetails)
        .catch(console.error);
    }
  }, [projectDetails, token]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const response = await fetch(`/api/model-files/${fileId}/`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ ...modelFile, content }),
      });
      if (!response.ok) throw new Error(`Save failed. Status: ${response.status}`);
      const updated = await response.json();
      setModelFile(updated);
      alert("Model file saved successfully!");
    } catch (err) {
      alert(`Error saving file: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="model-file-loading">Loading model file details...</p>;
  if (error) return <p className="model-file-error">Error: {error}</p>;
  if (!modelFile) return <p className="model-file-error">No model file found.</p>;

  const appName = appDetails?.name || 'Unknown App';
  const projectName = projectDetails?.name || 'Unknown Project';
  const displaySummaries = modelFile.model_summaries && Object.keys(modelFile.model_summaries).length > 0
    ? modelFile.model_summaries
    : null;

  return (
    <div className="model-file-detail-container">
      <header className="model-file-header">
        <h2>{`${projectName}/${appName}/models.py`}</h2>
      </header>

      {displaySummaries ? (
        <div className="model-file-summary">
          <h3>Individual Model Summaries</h3>
          <ul>
            {Object.entries(displaySummaries).map(([modelName, summary]) => (
              <li key={modelName}><strong>{modelName}:</strong> {summary}</li>
            ))}
          </ul>
        </div>
      ) : modelFile.summary ? (
        <div className="model-file-summary">
          <h3>AI-Generated Summary</h3>
          <p>{modelFile.summary}</p>
        </div>
      ) : (
        <div className="model-file-summary"><h3>No Summary Available</h3></div>
      )}

      <textarea
        className="model-file-textarea"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={30}
      />

      <div className="model-file-buttons">
        <button
          onClick={() => navigate(`/projects/${projectId}/apps/${appId}/model-diagram/${modelFile.id}`)}
          className="model-file-btn primary-btn"
        >
          View Model Diagram
        </button>
        <button
          onClick={() => navigate('/dashboard')}
          className="model-file-btn secondary-btn"
        >
          Back to Dashboard
        </button>
        <button
          onClick={handleSave}
          className="model-file-btn save-btn"
          disabled={saving}
        >
          {saving ? "Saving..." : "Save Changes"}
        </button>
      </div>
    </div>
  );
};

export default ModelFileDetail;
