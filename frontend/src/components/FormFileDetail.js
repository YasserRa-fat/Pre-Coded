import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import './css/FormFileDetail.css';

const FormFileDetail = () => {
  const { projectId, appId, fileId } = useParams();
  const [formFile, setFormFile] = useState(null);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [saveStatus, setSaveStatus] = useState('');
  const [error, setError] = useState(null);

  const navigate = useNavigate();
  const token = localStorage.getItem('access_token');
  const contentRef = useRef(null);

  // 1) Fetch the form‑file
  useEffect(() => {
    const fetchFormFile = async () => {
      try {
        const res = await fetch(`/api/formfile/${fileId}/`, {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setFormFile(data);
        setContent(data.content);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchFormFile();
  }, [fileId, token]);

  // 2) Initialize editable div
  useEffect(() => {
    if (contentRef.current) {
      contentRef.current.innerHTML = formatContent(content);
    }
  }, [content, loading]);

  const handleContentChange = (e) => {
    setContent(e.currentTarget.innerText);
  };

  // Function to decode HTML entities
  const decodeHTML = (str) => {
    const textArea = document.createElement('textarea');
    textArea.innerHTML = str;
    return textArea.value;
  };

  // Function to format content with preserved formatting
  const formatContent = (str) => {
    return str.replace(/\n/g, '<br>').replace(/ /g, '&nbsp;');
  };

  // 3) Save via your custom endpoint
  const handleSaveContent = async () => {
    try {
      const plainTextContent = decodeHTML(content); // Decode HTML entities
      const res = await fetch('/api/save-formfile-content/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          id: formFile.id,
          content: plainTextContent,  // Send plain text here
        }),
      });
      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(`Save failed: HTTP ${res.status} - ${errorText}`);
      }
      setSaveStatus('Content saved successfully!');
    } catch (err) {
      setSaveStatus(`Error saving content: ${err.message}`);
    }
  };

  if (loading) return <p className="loading">Loading form file details...</p>;
  if (error) return <p className="error">Error: {error}</p>;
  if (!formFile) return <p className="error">No form file found.</p>;

  // 4) Build a safe filename: name ➔ path ➔ fallback
  const filename = formFile.name || formFile.path || `formfile-${formFile.id}`;

  return (
    <div className="form-file-detail-container">
      <header className="form-file-header">
        <h2>{`${projectId}/${filename}`}</h2>
      </header>

      <label htmlFor="file-content" className="form-file-label">
        Editable File Content:
      </label>
      <div
        id="file-content"
        className="form-file-content"
        contentEditable
        ref={contentRef}
        onInput={handleContentChange}
        suppressContentEditableWarning
        style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word' }}
      />

      <div className="form-file-buttons">
        <button className="primary-btn" onClick={handleSaveContent}>
          Save Content
        </button>
        <button
          className="primary-btn"
          onClick={() => navigate(`/form-diagram/${formFile.id}`)}
        >
          View Form Diagram
        </button>
        <button
          className="secondary-btn"
          onClick={() => navigate('/dashboard')}
        >
          Back to Dashboard
        </button>
      </div>

      {saveStatus && <p className="save-status">{saveStatus}</p>}
    </div>
  );
};

export default FormFileDetail;
