import Editor from '@monaco-editor/react';
import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import './css/ModelDetail.css';

const ModelDetail = () => {
  const { id } = useParams();
  const [modelDetail, setModelDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);
  const [code, setCode] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [syntaxErrors, setSyntaxErrors] = useState([]);

  const handleEditorDidMount = (editor, monaco) => {
    // Optionally register completions if needed
  };

  useEffect(() => {
    const savedCode = localStorage.getItem(`code_${id}`);
    if (savedCode) {
      setCode(savedCode);
    }

    const fetchModelDetail = async () => {
      const token = localStorage.getItem('access_token');
      try {
        const response = await fetch(`http://localhost:8000/usermodels/${id}/`, {
          method: 'GET',
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) throw new Error('Failed to fetch model details.');
        const data = await response.json();
        setModelDetail(data);
        setCode(data.full_code || '');
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchModelDetail();
  }, [id]);

  // (Optional) Basic syntax validation—for example, for Django field definitions—
  // is still provided. You can remove or modify it as needed.
  const validateParameters = (codeStr) => {
    const errors = [];
    const lines = codeStr.split('\n');
    const regex = /^\s*(\w+)\s*=\s*models\.(\w+Field)\(([^)]*)\)/;
    lines.forEach(line => {
      if (line.includes('=') && line.includes('models.')) {
        const match = line.match(regex);
        if (!match) {
          errors.push(`Invalid field definition: ${line.trim()}`);
        }
      }
    });
    setSyntaxErrors(errors);
  };

  const handleEditorChange = (value) => {
    setCode(value);
    localStorage.setItem(`code_${id}`, value);
    validateParameters(value);
  };

  const handleSaveChanges = async () => {
    // Directly update full_code with the code string from the editor.
    const updatedData = {
      ...modelDetail,
      full_code: code,
    };

    try {
      const token = localStorage.getItem('access_token');
      const response = await fetch(`http://localhost:8000/usermodels/${id}/`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(updatedData),
      });

      if (!response.ok) {
        throw new Error(`Failed to save changes: ${response.statusText}`);
      }

      const responseData = await response.json();
      setModelDetail(responseData);
      setIsEditing(false);
      setError(null);
      setSuccess(true);
    } catch (err) {
      setError(err.message);
      setSuccess(false);
    }
  };

  if (loading) return <p>Loading...</p>;
  if (error) return <p>Error: {error}</p>;

  return (
    <div className="model-detail-container">
      <h1 style={{ color: '#f0f0f0' }}>Model: {modelDetail.model_name}</h1>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      {success && <p style={{ color: 'green' }}>Changes saved successfully!</p>}
      <div className="code-snippet" style={{ height: "400px" }}>
        {isEditing ? (
          <>
            <Editor
              height="300px"
              language="python"
              value={code}
              theme="vs-dark"
              onMount={handleEditorDidMount}
              options={{
                selectOnLineNumbers: true,
                automaticLayout: true,
                fontFamily: 'Consolas, "Courier New", monospace',
                fontSize: 14,
              }}
              onChange={handleEditorChange}
            />
            <button onClick={handleSaveChanges} style={{ marginTop: "10px" }}>
              Save Changes
            </button>
            {syntaxErrors.length > 0 && (
              <div style={{ color: "red", marginTop: "10px" }}>
                <h3>Syntax Errors:</h3>
                <ul>
                  {syntaxErrors.map((error, index) => (
                    <li key={index}>{error}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <div onClick={() => setIsEditing(true)} style={{ cursor: "pointer" }}>
            <pre style={{ whiteSpace: "pre-wrap", wordWrap: "break-word" }}>
              {code}
            </pre>
          </div>
        )}
      </div>
      <h2 style={{ color: "#f0f0f0", marginTop: "20px" }}>Model Details in JSON:</h2>
      <pre style={{ backgroundColor: "#222", color: "#f0f0f0", padding: "10px", borderRadius: "5px" }}>
        {JSON.stringify(modelDetail, null, 2)}
      </pre>
    </div>
  );
};

export default ModelDetail;
