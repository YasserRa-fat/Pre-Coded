// src/components/ProjectDetail.js
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import './css/ProjectDetail.css';

const ProjectDetail = () => {
  const { projectId } = useParams();
  const navigate = useNavigate();

  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [showCreateAppModal, setShowCreateAppModal] = useState(false);
  const [newAppName, setNewAppName] = useState('');
  const [newAppDescription, setNewAppDescription] = useState('');
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (!projectId) return;

    const token = localStorage.getItem('access_token');
    fetch(`/api/projects/${projectId}/`, {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(data => {
        setProject(data);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, [projectId]);

  const handleCreateApp = () => {
    if (!newAppName.trim()) {
      alert("Please enter an app name.");
      return;
    }

    const token = localStorage.getItem('access_token');
    fetch('/api/apps/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({
        project: project.id,
        name: newAppName,
        description: newAppDescription,
      }),
    })
      .then(res => {
        if (!res.ok) {
          return res.json().then(errData =>
            Promise.reject(new Error(`HTTP ${res.status}: ${JSON.stringify(errData)}`))
          );
        }
        return res.json();
      })
      .then(newApp => {
        setShowCreateAppModal(false);
        setNewAppName('');
        setNewAppDescription('');
        navigate(`/projects/${project.id}/apps/${newApp.id}`);
      })
      .catch(err => {
        alert(`Error creating app: ${err.message}`);
      });
  };
  const renderFileCards = (files, routePrefix, fixedName = null, appId = null) => {
    if (!Array.isArray(files)) return null;
  
    return files.map(f => (
      <div
        key={f.id}
        className="file-card"
        onClick={e => {
          e.stopPropagation();
          const base = appId
            ? `/projects/${projectId}/apps/${appId}/${routePrefix}`
            : `/projects/${projectId}/${routePrefix}`;
          navigate(`${base}/${f.id}`);  // Ensure it's navigating to the correct route
        }}
      >
        <h6>{fixedName || f.name || f.path}</h6>
      </div>
    ));
  };
  

/**
+   * Call the backend to “run” this project,
+   * then open the returned URL in a new tab.
+   */
const handleRunProject = async () => {
      setRunning(true);
      setError(null);
  
      try {
        const token = localStorage.getItem('access_token');
        const res = await fetch(`/api/projects/${projectId}/run/`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });
  
        if (!res.ok) {
          const errJson = await res.json().catch(() => ({}));
          throw new Error(errJson.detail || `HTTP ${res.status}`);
        }
  
        const { url } = await res.json();
        if (!url) throw new Error('No URL returned from server.');
  
        // open the running project in a new tab/window
        window.open(url, '_blank');
      } catch (err) {
        setError(`Failed to run project: ${err.message}`);
      } finally {
        setRunning(false);
      }
    };




  if (loading) return <p className="loading">Loading project details…</p>;
  if (error)   return <p className="error">Error: {error}</p>;
  if (!project) return <p className="error">No project found.</p>;

  // Project‑level groupings
  const projectUrlFiles = (project.url_files || []).filter(f => f.app === null);
  const settingsFiles   = project.settings_files || [];
  const projectFiles    = project.project_files || [];
  const staticFiles     = project.static_files  || [];
  const mediaFiles      = project.media_files   || [];

  const displayVisibility = project.visibility
    ? project.visibility[0].toUpperCase() + project.visibility.slice(1)
    : 'N/A';

  return (
    <div className="project-detail-container">
       <div className="project-header">

      <h2>{project.name}</h2>


      +       <button
         className="run-project-btn"
         onClick={handleRunProject}
         disabled={running}
       >
         {running ? 'Launching…' : 'Run Project'}
       </button>
     </div>
      <p>
        <strong>Visibility:</strong> {displayVisibility}
      </p>

      <div className="cards-container">
        {/* Project‑level files */}
        <div className="project-card">
          <h3>Project Files</h3>
          {renderFileCards(settingsFiles,    'settings-files')}
          {renderFileCards(projectUrlFiles,  'url-files')}
          {renderFileCards(projectFiles,     'project-files')}


          <div className="file-nav-buttons">
            <button onClick={() => navigate(`/projects/${projectId}/template-files`)}>
              Manage Templates
            </button>
            <button onClick={() => navigate(`/projects/${projectId}/static-files`)}>
              Manage Static
            </button>
            <button onClick={() => navigate(`/projects/${projectId}/media-files`)}>
              Manage Media
            </button>
          </div>
        </div>

        {/* Apps Section */}
        <div className="apps-card">
          <h3>Apps</h3>
          {project.apps?.length > 0 ? (
            <div className="apps-container">
              {project.apps.map(app => (
                <div
                  key={app.id}
                  className="app-card"
                  
                >
                  <h4>{app.name}</h4>
                  {renderFileCards(app.model_files,    'model-files',    'models.py', app.id)}
                  {renderFileCards(app.view_files,     'view-files',     'views.py',  app.id)}
                  {renderFileCards(app.form_files,     'form-files',     'forms.py',  app.id)}
                  {renderFileCards(app.app_url_files,  'url-files',      'urls.py',   app.id)}
                  {renderFileCards(app.template_files, 'template-files', null,       app.id)}
                  {renderFileCards(app.app_files,      'app-files',      null,       app.id)}
                  <div className="file-nav-buttons">
      <button onClick={() => navigate(`/projects/${projectId}/apps/${app.id}/template-files`)}>
        Manage Templates
      </button>
    </div>
                </div>
                
              ))}
              
            </div>
          ) : (
            <p>No apps found for this project.</p>
          )}

          <div
            className="create-app-card"
            onClick={() => setShowCreateAppModal(true)}
          >
            <h4>+</h4>
            <p>Create a new app</p>
          </div>
        </div>
      </div>

      {/* Create App Modal */}
      {showCreateAppModal && (
        <div className="modal-overlay" onClick={() => setShowCreateAppModal(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>Create New App for {project.name}</h3>
            <input
              type="text"
              placeholder="App Name"
              value={newAppName}
              onChange={e => setNewAppName(e.target.value)}
            />
            <textarea
              placeholder="App Description (optional)"
              value={newAppDescription}
              onChange={e => setNewAppDescription(e.target.value)}
            />
            <div className="modal-actions">
              <button className="primary-btn" onClick={handleCreateApp}>
                Create App
              </button>
              <button
                className="secondary-btn"
                onClick={() => {
                  setShowCreateAppModal(false);
                  setNewAppName('');
                  setNewAppDescription('');
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProjectDetail;
