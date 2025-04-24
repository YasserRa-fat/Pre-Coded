import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

const ModelFilesList = () => {
  // Renamed from modelId to appId.
  const { projectId, appId } = useParams();
  const [modelFiles, setModelFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();
  
  useEffect(() => {
    const token = localStorage.getItem('access_token');
    // Adjusted endpoint to filter by app_id.
    fetch(`/api/model-files/?app_id=${appId}`, {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP error! Status: ${res.status}`);
        }
        return res.json();
      })
      .then((data) => {
        // Assuming response returns an array of model files.
        setModelFiles(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [appId]);

  if (loading) return <p>Loading model files...</p>;
  if (error) return <p>Error: {error}</p>;
  if (!modelFiles || modelFiles.length === 0) return <p>No model files found for this app.</p>;

  return (
    <div style={{ padding: '2rem' }}>
      <h2>Model Files</h2>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem' }}>
        {modelFiles.map((file) => (
          <div
            key={file.id}
            onClick={() => navigate(`/projects/${projectId}/apps/${appId}/model-files/${file.id}`)}
            style={{
              border: '1px solid #ddd',
              borderRadius: '8px',
              padding: '1rem',
              width: '200px',
              textAlign: 'center',
              cursor: 'pointer',
            }}
          >
            <h4>{file.title || `File ${file.id}`}</h4>
            <p style={{ fontSize: '0.9rem', color: '#555' }}>
              {file.description || 'No description provided.'}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ModelFilesList;
