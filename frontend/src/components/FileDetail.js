import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import './css/FileDetail.css';

const FileDetail = ({ apiBase: propApiBase, displayPathPrefix: propDisplayPrefix }) => {
  const { projectId, appId, fileType, fileId } = useParams();
  const apiBase = propApiBase || fileType;
  const navigate = useNavigate();
  const token = localStorage.getItem('access_token');

  const displayPrefix = propDisplayPrefix ||
    (apiBase === 'url-files' ? 'urls.py' :
    apiBase === 'settings-files' ? 'settings.py' :
    apiBase === 'app-files' ? 'app' : undefined);

  // State management
  const [file, setFile] = useState(null);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const textareaRef = useRef(null);

  // API URL construction
  const apiUrl = (() => {
    const basePaths = {
      'url-files': appId ? `/api/apps/${appId}/url-files/${fileId}/` 
                         : `/api/projects/${projectId}/url-files/${fileId}/`,
      'app-files': `/api/apps/${appId}/app-files/${fileId}/`,
      'settings-files': `/api/settings-files/${fileId}/`,
      'project-files': `/api/project-files/${fileId}/`,
      'default': appId ? `/api/apps/${appId}/${apiBase}/${fileId}/` 
                       : `/api/projects/${projectId}/${apiBase}/${fileId}/`
    };
    return basePaths[apiBase] || basePaths.default;
  })();

  // Fetch file data
  useEffect(() => {
    const fetchFile = async () => {
      try {
        const res = await fetch(apiUrl, {
          headers: { 
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          }
        });
        
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        setFile(data);
        setContent(data.content || '');
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    
    fetchFile();
  }, [apiUrl, token]);

  // Save handler
  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await fetch(apiUrl, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ ...file, content })
      });

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || `Save failed: HTTP ${res.status}`);
      }

      const updated = await res.json();
      setFile(updated);
      setContent(updated.content);
      alert("File saved successfully!");
    } catch (err) {
      alert(`Error saving file: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  // Input change handler
  const handleContentChange = (e) => {
    setContent(e.target.value);
  };

  // Dynamic header construction
  const headerSegments = [];
  if (appId) headerSegments.push(appId);
  if (displayPrefix) headerSegments.push(displayPrefix);
  if (file?.name) headerSegments.push(file.name);
  const header = headerSegments.join(' / ');

  // Loading and error states
  if (loading) return <p className="model-file-loading">Loading file…</p>;
  if (error) return <p className="model-file-error">Error: {error}</p>;
  if (!file) return <p className="model-file-error">File not found.</p>;

  return (
    <div className="model-file-detail-container">
      <header className="model-file-header">
        <h2>{header}</h2>
      </header>

      <textarea
        ref={textareaRef}
        className="file-content-editor"
        value={content}
        onChange={handleContentChange}
        spellCheck="false"
        placeholder="Start editing file content..."
      />

      <div className="model-file-buttons">
        <button
          className={`model-file-btn primary-btn ${saving ? 'saving' : ''}`}
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? "Saving…" : "Save Changes"}
        </button>
        
        <button
          className="model-file-btn secondary-btn"
          onClick={() => navigate(-1)}
          disabled={saving}
        >
          Cancel
        </button>
      </div>
    </div>
  );
};

export default FileDetail;