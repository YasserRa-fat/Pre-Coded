// AppSelector.jsx
import React, { useEffect, useState } from 'react';
import "./css/AppSelector.css";

const AppSelector = ({ onAppSelect, suppressNavigation = false }) => {
  const [apps, setApps] = useState([]);
  const [selectedAppId, setSelectedAppId] = useState('');
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newAppName, setNewAppName] = useState('');
  const [error, setError] = useState(null);

  // Get project id and token from localStorage.
  const projectId = localStorage.getItem('project_id');
  const token = localStorage.getItem('access_token');

  useEffect(() => {
    if (!projectId) {
      setError("No project selected. Please select a project first.");
      setLoading(false);
      return;
    }
    // Fetch apps for the given project.
    fetch(`/api/apps/?project_id=${projectId}`, {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error("Failed to fetch apps");
        }
        return res.json();
      })
      .then((data) => {
        const fetchedApps = data.apps || data;
        setApps(fetchedApps);
        if (fetchedApps.length > 0) {
          setSelectedAppId(fetchedApps[0].id);
        }
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [projectId, token]);

  const handleAppChange = (e) => {
    setSelectedAppId(e.target.value);
  };

  const handleSelect = () => {
    if (!selectedAppId) {
      alert("Please select a valid app.");
      return;
    }
    const selected = apps.find((app) => app.id === parseInt(selectedAppId, 10));
    if (selected) {
      onAppSelect(selected);
      if (!suppressNavigation) {
        // Optionally navigate here if needed.
        // For example: navigate(`/apps/${selected.id}`);
      }
    } else {
      alert("Please select a valid app.");
    }
  };

  const handleCreateApp = () => {
    if (!newAppName.trim()) {
      alert("Please enter an app name.");
      return;
    }
    fetch('/api/apps/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({
        project: projectId,
        name: newAppName,
      }),
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error("Failed to create app");
        }
        return res.json();
      })
      .then((newApp) => {
        setApps((prev) => [...prev, newApp]);
        setSelectedAppId(newApp.id);
        onAppSelect(newApp);
        setCreating(false);
      })
      .catch((err) => {
        alert(err.message);
      });
  };

  if (loading) return <p>Loading apps...</p>;
  if (error) return <p>Error: {error}</p>;

  return (
    <div style={{ padding: '1rem', textAlign: 'center' }}>
      <h2>Select an App</h2>
      {apps.length > 0 && !creating ? (
        <>
          <select
            value={selectedAppId}
            onChange={handleAppChange}
            style={{ width: '300px', padding: '0.5rem', fontSize: '1rem' }}
          >
            {apps.map((app) => (
              <option key={app.id} value={app.id}>
                {app.name}
              </option>
            ))}
          </select>
          <div style={{ marginTop: '1rem' }}>
            <button onClick={handleSelect} style={{ padding: '0.5rem 1rem' }}>
              Select App
            </button>
          </div>
        </>
      ) : (
        <p>No apps found for this project.</p>
      )}
      <div style={{ marginTop: '1rem' }}>
        {creating ? (
          <div>
            <input
              type="text"
              placeholder="New App Name"
              value={newAppName}
              onChange={(e) => setNewAppName(e.target.value)}
              style={{ width: '300px', padding: '0.5rem', fontSize: '1rem' }}
            />
            <div style={{ marginTop: '0.5rem' }}>
              <button onClick={handleCreateApp} style={{ padding: '0.5rem 1rem', marginRight: '1rem' }}>
                Create App
              </button>
              <button onClick={() => setCreating(false)} style={{ padding: '0.5rem 1rem' }}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button onClick={() => setCreating(true)} style={{ padding: '0.5rem 1rem' }}>
            Create New App
          </button>
        )}
      </div>
    </div>
  );
};

export default AppSelector;
