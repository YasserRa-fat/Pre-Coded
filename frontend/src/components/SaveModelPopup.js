import React, { useEffect, useState } from 'react';
import "./css/SaveModelPopup.css"; // Import the CSS file here

const SaveModelPopup = ({ onClose, onSave }) => {
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

  // When selected project changes (and not creating a new project), fetch apps for that project.
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

  // Handler for project dropdown change.
  const handleProjectChange = (e) => {
    const value = e.target.value;
    setSelectedProjectId(value);
    if (value === 'new') {
      setCreatingProject(true);
      // Clear apps selection when creating a new project.
      setApps([]);
      setSelectedAppId('new');
      setCreatingApp(true);
    } else {
      setCreatingProject(false);
    }
  };

  // Handler for app dropdown change.
  const handleAppChange = (e) => {
    const value = e.target.value;
    setSelectedAppId(value);
    if (value === 'new') {
      setCreatingApp(true);
    } else {
      setCreatingApp(false);
    }
  };

  // When user clicks Save, call onSave with the selected/created project and app.
  const handleSave = async () => {
    let finalProject = null;
    let finalApp = null;

    if (selectedProjectId === 'new') {
      if (!newProjectName.trim()) {
        alert("Please enter a new project name.");
        return;
      }
      // Create new project (or return an object with its details)
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
      // Create new app (or return an object with its details)
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
    onSave(finalProject, finalApp);
  };

  return (
    <div className="save-model-popup-overlay">
      <div className="save-model-popup-container">
        <h2>Save Model File</h2>

        <div className="save-model-field">
          <label htmlFor="projectSelect">Project:</label>
          <select
            id="projectSelect"
            value={selectedProjectId}
            onChange={handleProjectChange}
          >
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
            <option value="new">Create New Project</option>
          </select>
          {creatingProject && (
            <div className="new-project-fields">
              <input
                type="text"
                placeholder="New Project Name"
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
              />
              <textarea
                placeholder="Project Description (optional)"
                value={newProjectDescription}
                onChange={(e) => setNewProjectDescription(e.target.value)}
              />
            </div>
          )}
        </div>

        <div className="save-model-field">
          <label htmlFor="appSelect">App:</label>
          <select
            id="appSelect"
            value={selectedAppId}
            onChange={handleAppChange}
          >
            {apps.map((app) => (
              <option key={app.id} value={app.id}>
                {app.name}
              </option>
            ))}
            <option value="new">Create New App</option>
          </select>
          {creatingApp && (
            <div className="new-app-fields">
              <input
                type="text"
                placeholder="New App Name"
                value={newAppName}
                onChange={(e) => setNewAppName(e.target.value)}
              />
            </div>
          )}
        </div>

        <div className="save-model-buttons">
          <button onClick={handleSave}>Save Model File</button>
          <button onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
};

export default SaveModelPopup;
