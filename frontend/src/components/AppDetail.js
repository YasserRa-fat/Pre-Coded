import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import './css/AppDetail.css'; // Create this CSS file for styling

const AppDetail = () => {
  const { projectId, appId } = useParams();
  const [app, setApp] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchApps = async () => {
      const token = localStorage.getItem('access_token');
      try {
        const res = await fetch(`/api/apps/?project_id=${projectId}`, {
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
        });
        if (!res.ok) throw new Error(`HTTP error! Status: ${res.status}`);
        const data = await res.json();
        const appsArray = Array.isArray(data) ? data : data.apps;
        const foundApp = appsArray.find((a) => a.id === Number(appId));
        if (foundApp) {
          setApp(foundApp);
        } else {
          throw new Error("App not found");
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchApps();
  }, [projectId, appId]);

  if (loading) return <p className="status-message">Loading app details...</p>;
  if (error) return <p className="status-message error">Error: {error}</p>;
  if (!app) return <p className="status-message error">No app found.</p>;

  return (
    <div className="app-detail-container">
      <header className="app-header">
        <h1>{app.name}</h1>
        <p>{app.description || 'No description provided.'}</p>
      </header>

      <section className="file-section">
        <h2>Model Files</h2>
        {app.model_files && app.model_files.length > 0 ? (
          <div className="file-grid">
            {app.model_files.map(({ id, description }) => (
              <div
                key={id}
                className="file-card"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate(`/projects/${projectId}/model-files/${id}`);
                }}
              >
                <h3>models.py</h3>
                <p>{description || 'No description provided.'}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="no-files">No model files found for this app.</p>
        )}
      </section>

      <div className="back-button-wrapper">
        <button onClick={() => navigate(`/projects/${projectId}`)}>Back to Project</button>
      </div>
    </div>
  );
};

export default AppDetail;
