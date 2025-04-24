import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const AppList = () => {
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  // Retrieve projectId from localStorage.
  const projectId = localStorage.getItem('project_id');
  const token = localStorage.getItem('access_token');

  useEffect(() => {
    if (!projectId) {
      setError('No project selected. Please select a project first.');
      setLoading(false);
      return;
    }
    console.log('Project ID:', projectId);
    const fetchApps = async () => {
      try {
        const res = await fetch(`/api/apps/?project_id=${projectId}`, {
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
        });
        if (!res.ok) {
          throw new Error(`HTTP error! Status: ${res.status}`);
        }
        const data = await res.json();
        // Expecting data to be an array or an object with a key "apps"
        const appsData = data.apps || data;
        setApps(appsData);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchApps();
  }, [projectId, token]);

  if (loading) return <p>Loading apps...</p>;
  if (error) return <p>Error: {error}</p>;
  if (!apps || apps.length === 0)
    return <p>No apps found for this project.</p>;

  return (
    <div style={{ padding: '2rem' }}>
      <h2 style={{ marginBottom: '1rem' }}>Apps in Your Project</h2>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem' }}>
        {apps.map((app) => (
          <div
            key={app.id}
            onClick={() => navigate(`/projects/${projectId}/apps/${app.id}`)}
            style={{
              border: '1px solid #ddd',
              borderRadius: '8px',
              padding: '1rem',
              width: '240px',
              cursor: 'pointer',
              boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
              transition: 'transform 0.2s, box-shadow 0.2s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.transform = 'translateY(-4px)';
              e.currentTarget.style.boxShadow = '0 4px 8px rgba(0,0,0,0.15)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = 'none';
              e.currentTarget.style.boxShadow = '0 2px 4px rgba(0,0,0,0.1)';
            }}
          >
            <h3 style={{ margin: '0 0 0.5rem 0' }}>{app.name}</h3>
            <p style={{ fontSize: '0.9rem', color: '#555' }}>
              {app.description || 'No description provided.'}
            </p>
          </div>
        ))}
        {/* "Create New App" Card */}
        <div
          onClick={() => navigate(`/projects/${projectId}/apps/new`)}
          style={{
            border: '2px dashed #aaa',
            borderRadius: '8px',
            padding: '1rem',
            width: '240px',
            height: '150px',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            cursor: 'pointer',
            color: '#aaa',
            fontSize: '3rem',
          }}
        >
          +
        </div>
      </div>
    </div>
  );
};

export default AppList;
