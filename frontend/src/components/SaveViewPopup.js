import React, { useEffect, useState } from 'react';

const SaveViewPopup = ({ onClose, onSave }) => {
  const [projects, setProjects] = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [apps, setApps] = useState([]);
  const [selectedAppId, setSelectedAppId] = useState('');

  // For new project creation
  const [creatingProject, setCreatingProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectDescription, setNewProjectDescription] = useState('');

  // For new app creation
  const [creatingApp, setCreatingApp] = useState(false);
  const [newAppName, setNewAppName] = useState('');

  const token = localStorage.getItem('access_token');

  // Fetch projects on mount.
  useEffect(() => {
    const fetchProjects = async () => {
      try {
        const res = await fetch('/api/projects/', {
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
        });
        const data = await res.json();
        const projs = data.projects || data;
        setProjects(projs);
        if (projs.length > 0) {
          setSelectedProjectId(projs[0].id);
        }
      } catch (err) {
        console.error("Error fetching projects:", err);
      }
    };
    fetchProjects();
  }, [token]);

  // Fetch apps when selected project changes.
  useEffect(() => {
    if (!creatingProject && selectedProjectId && selectedProjectId !== 'new') {
      const fetchApps = async () => {
        try {
          const res = await fetch(`/api/apps/?project_id=${selectedProjectId}`, {
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${token}`,
            },
          });
          const data = await res.json();
          const fetchedApps = data.apps || data;
          setApps(fetchedApps);
          if (fetchedApps.length > 0) {
            setSelectedAppId(fetchedApps[0].id);
          } else {
            setSelectedAppId('new');
            setCreatingApp(true);
          }
        } catch (err) {
          console.error("Error fetching apps:", err);
        }
      };
      fetchApps();
    }
  }, [selectedProjectId, creatingProject, token]);

  const handleProjectChange = (e) => {
    const value = e.target.value;
    setSelectedProjectId(value);
    if (value === 'new') {
      setCreatingProject(true);
      setApps([]);
      setSelectedAppId('new');
      setCreatingApp(true);
    } else {
      setCreatingProject(false);
    }
  };

  const handleAppChange = (e) => {
    const value = e.target.value;
    setSelectedAppId(value);
    if (value === 'new') {
      setCreatingApp(true);
    } else {
      setCreatingApp(false);
    }
  };

  const handleSave = async () => {
    let finalProject = null;
    let finalApp = null;

    if (selectedProjectId === 'new') {
      if (!newProjectName.trim()) {
        alert("Please enter a new project name.");
        return;
      }
      try {
        const res = await fetch('/api/projects/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
          body: JSON.stringify({
            name: newProjectName,
            description: newProjectDescription,
          }),
        });
        if (!res.ok) {
          const errorData = await res.json();
          console.error("Project creation error:", errorData);
          alert("Error creating project: " + JSON.stringify(errorData));
          return;
        }
        finalProject = await res.json();
      } catch (err) {
        console.error("Error creating project:", err);
        alert("Error creating project.");
        return;
      }
    } else {
      finalProject = projects.find((p) => p.id === Number(selectedProjectId));
    }

    if (selectedAppId === 'new') {
      if (!newAppName.trim()) {
        alert("Please enter a new app name.");
        return;
      }
      try {
        const res = await fetch('/api/apps/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
          body: JSON.stringify({
            project: finalProject.id,
            name: newAppName,
          }),
        });
        if (!res.ok) {
          const errorData = await res.json();
          console.error("App creation error:", errorData);
          alert("Error creating app: " + JSON.stringify(errorData));
          return;
        }
        finalApp = await res.json();
      } catch (err) {
        console.error("Error creating app:", err);
        alert("Error creating app.");
        return;
      }
    } else {
      finalApp = apps.find((a) => a.id === Number(selectedAppId));
    }

    if (!finalProject || !finalApp) {
      alert("Please select valid project and app.");
      return;
    }
    console.log("Final project and app:", finalProject, finalApp);
    onSave(finalProject, finalApp);
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.5)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 2000,
    }}>
      <div style={{
        background: '#fff',
        padding: '2rem',
        borderRadius: '8px',
        width: '400px',
        maxHeight: '90vh',
        overflowY: 'auto',
        textAlign: 'center'
      }}>
        <h2>Save View File</h2>
        <div style={{ marginBottom: '1rem' }}>
          <label htmlFor="projectSelect">Project:</label>
          <br />
          <select
            id="projectSelect"
            value={selectedProjectId}
            onChange={handleProjectChange}
            style={{ width: '100%', padding: '0.5rem', fontSize: '1rem' }}
          >
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
            <option value="new">Create New Project</option>
          </select>
          {creatingProject && (
            <div style={{ marginTop: '0.5rem', textAlign: 'left' }}>
              <input
                type="text"
                placeholder="New Project Name"
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                style={{ width: '100%', padding: '0.5rem', fontSize: '1rem' }}
              />
              <textarea
                placeholder="Project Description (optional)"
                value={newProjectDescription}
                onChange={(e) => setNewProjectDescription(e.target.value)}
                style={{ width: '100%', padding: '0.5rem', fontSize: '1rem', marginTop: '0.5rem' }}
              />
            </div>
          )}
        </div>
        <div style={{ marginBottom: '1rem' }}>
          <label htmlFor="appSelect">App:</label>
          <br />
          <select
            id="appSelect"
            value={selectedAppId}
            onChange={handleAppChange}
            style={{ width: '100%', padding: '0.5rem', fontSize: '1rem' }}
          >
            {apps.map((app) => (
              <option key={app.id} value={app.id}>
                {app.name}
              </option>
            ))}
            <option value="new">Create New App</option>
          </select>
          {creatingApp && (
            <div style={{ marginTop: '0.5rem' }}>
              <input
                type="text"
                placeholder="New App Name"
                value={newAppName}
                onChange={(e) => setNewAppName(e.target.value)}
                style={{ width: '100%', padding: '0.5rem', fontSize: '1rem' }}
              />
            </div>
          )}
        </div>
        <div>
          <button onClick={handleSave} style={{ padding: '0.5rem 1rem', marginRight: '1rem' }}>
            Save View File
          </button>
          <button onClick={onClose} style={{ padding: '0.5rem 1rem' }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

export default SaveViewPopup;
