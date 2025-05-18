import React, { useContext, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import api from '../api';
import { AuthContext } from '../AuthContext';
import DiffModal from '../components/DiffModal';
import FloatingChat from '../floating-bot/FloatingChat';

import './css/ProjectDetail.css';

export default function ProjectDetail() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const { token } = useContext(AuthContext);

  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [showCreateAppModal, setShowCreateAppModal] = useState(false);
  const [newAppName, setNewAppName] = useState('');
  const [newAppDescription, setNewAppDescription] = useState('');

  const [aiDiffFiles, setAiDiffFiles] = useState([]);
  const [previewMap, setPreviewMap] = useState({});
  const [modalOpen, setModalOpen] = useState(false);
  const [changeId, setChangeId] = useState(null);
  const [running, setRunning] = useState(false);

  // Fetch project on mount
  useEffect(() => {
    if (!projectId) return;
    api
      .get(`/projects/${projectId}/`)
      .then(({ data }) => setProject(data))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [projectId]);

  // Handle AI diff payload
  const handleDiff = ({ files, previewMap, change_id }) => {
    console.log('ProjectDetail received diff data:', { files, previewMap, change_id });
    
    if (!files || !files.length) {
        console.error('No files to show in diff modal');
        return;
    }

    // Ensure we have all required data
    const formattedFiles = files.map(file => ({
        ...file,
        projectId: projectId,
        changeId: change_id
    }));

    console.log('Setting diff modal with formatted files:', formattedFiles);
    
    // Update state in a single batch to avoid race conditions
    setAiDiffFiles(formattedFiles);
    setPreviewMap(previewMap || {});
    setChangeId(change_id);
    setModalOpen(true);
  };

  const applyChanges = () =>
    api
      .post(`/projects/${projectId}/apply/${changeId}/`)
      .then(() => {
        setModalOpen(false);
        setAiDiffFiles([]);
        alert('✅ Changes applied');
      })
      .catch(err => alert(`Error: ${err.message}`));

  const discardChanges = () =>
    api
      .post(`/ai/conversations/${changeId}/cancel/`)
      .then(() => setModalOpen(false))
      .catch(err => alert(`Error: ${err.message}`));

  const handleCreateApp = () => {
    if (!newAppName.trim()) return alert('Enter an app name');
    api
      .post('/apps/', {
        project: project.id,
        name: newAppName,
        description: newAppDescription,
      })
      .then(({ data }) => navigate(`/projects/${project.id}/apps/${data.id}`))
      .catch(err => alert(`Error: ${JSON.stringify(err.response?.data || err)}`));
  };

  const handleRunProject = () => {
    setRunning(true);
    api
      .post(`/projects/${projectId}/run/`)
      .then(({ data }) => data.url && window.open(data.url, '_blank'))
      .catch(err => setError(err.message))
      .finally(() => setRunning(false));
  };

  if (loading) return <p className="status">Loading project…</p>;
  if (error) return <p className="status status--error">Error: {error}</p>;
  if (!project) return <p className="status status--error">Project not found</p>;

  const renderFileCards = (list, route, label, appId) =>
    list.map(f => (
      <div
        key={f.id}
        className="file-card"
        onClick={e => {
          e.stopPropagation();
          const base = appId
            ? `/projects/${projectId}/apps/${appId}/${route}`
            : `/projects/${projectId}/${route}`;
          navigate(`${base}/${f.id}`);
        }}
      >
        <h6 className="file-card__title">{label || f.name || f.path}</h6>
      </div>
    ));

  return (
    <main className="project-detail">
      <header className="project-detail__header">
        <h1 className="project-detail__title">{project.name}</h1>
        <button
          className="btn btn--primary"
          onClick={handleRunProject}
          disabled={running}
        >
          {running ? 'Launching…' : 'Run Project'}
        </button>
      </header>

      {modalOpen && aiDiffFiles.length > 0 && (
        <DiffModal
          projectId={projectId}
          changeId={changeId}
          files={aiDiffFiles}
          previewMap={previewMap}
          token={token}
          onApply={applyChanges}
          onCancel={discardChanges}
          onClose={() => setModalOpen(false)}
        />
      )}

      <FloatingChat onDiff={handleDiff} projectId={projectId} />

      <section className="project-detail__section project-detail__section--files">
        <h2 className="section-title">Project Files</h2>
        <div className="file-grid">
          {renderFileCards(project.settings_files, 'settings-files')}
          {renderFileCards(
            project.url_files.filter(f => f.app === null),
            'url-files'
          )}
          {renderFileCards(project.project_files, 'project-files')}

          <nav className="file-nav">
            <button onClick={() => navigate(`/projects/${projectId}/template-files`)}>
              Templates
            </button>
            <button onClick={() => navigate(`/projects/${projectId}/static-files`)}>
              Static
            </button>
            <button onClick={() => navigate(`/projects/${projectId}/media-files`)}>
              Media
            </button>
          </nav>
        </div>
      </section>

      <section className="project-detail__section project-detail__section--apps">
        <h2 className="section-title">Apps</h2>
        <div className="apps-grid">
          {project.apps.length ? (
            project.apps.map(app => (
              <div key={app.id} className="app-card">
                <h3 className="app-card__title">{app.name}</h3>
                <div className="app-file-grid">
                  {renderFileCards(app.model_files, 'model-files', 'models.py', app.id)}
                  {renderFileCards(app.view_files, 'view-files', 'views.py', app.id)}
                  {renderFileCards(app.form_files, 'form-files', 'forms.py', app.id)}
                  {renderFileCards(app.app_url_files, 'url-files', 'urls.py', app.id)}
                  {renderFileCards(app.template_files, 'template-files', null, app.id)}
                  {renderFileCards(app.app_files, 'app-files', null, app.id)}
                </div>
                <button
                  className="btn btn--secondary app-card__manage-btn"
                  onClick={() =>
                    navigate(`/projects/${projectId}/apps/${app.id}/template-files`)
                  }
                >
                  Manage Templates
                </button>
              </div>
            ))
          ) : (
            <p>No apps yet.</p>
          )}

          <div
            className="app-card app-card--create"
            onClick={() => setShowCreateAppModal(true)}
          >
            <div className="app-card--create-inner">
              <span className="app-card--create-icon">＋</span>
              <p>Create New App</p>
            </div>
          </div>
        </div>
      </section>

      {showCreateAppModal && (
        <div className="modal-overlay" onClick={() => setShowCreateAppModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2>Create New App</h2>
            <input
              type="text"
              placeholder="App Name"
              value={newAppName}
              onChange={e => setNewAppName(e.target.value)}
              className="modal__input"
            />
            <textarea
              placeholder="Description (optional)"
              value={newAppDescription}
              onChange={e => setNewAppDescription(e.target.value)}
              className="modal__textarea"
            />
            <div className="modal__actions">
              <button className="btn btn--primary" onClick={handleCreateApp}>
                Create
              </button>
              <button
                className="btn btn--secondary"
                onClick={() => setShowCreateAppModal(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
