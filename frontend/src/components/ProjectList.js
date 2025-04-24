import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './css/ProjectList.css'; // Import the new CSS file

const ProjectList = () => {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectDescription, setNewProjectDescription] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    fetch('/api/projects/', {
      headers: { 'Authorization': `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP error! Status: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setProjects(data.projects || data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  const handleCardClick = (project) => {
    localStorage.setItem('project_id', project.id);
    navigate(`/projects/${project.id}`);
  };

  const handleCreateProject = () => {
    if (!newProjectName.trim()) return alert("Please enter a project name.");
    
    const token = localStorage.getItem('access_token');
    fetch('/api/projects/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ name: newProjectName, description: newProjectDescription }),
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP error! Status: ${res.status}`);
        return res.json();
      })
      .then((newProject) => {
        setProjects((prev) => [...prev, newProject]);
        setShowCreateModal(false);
        setNewProjectName('');
        setNewProjectDescription('');
        alert('Project created successfully!');
      })
      .catch((err) => alert(`Error creating project: ${err.message}`));
  };

  if (loading) return <p className="loading">Loading projects...</p>;
  if (error) return <p className="error">Error: {error}</p>;

  return (
    <div className="project-list-container">
      <h2 className="project-list-title">Projects</h2>
      <div className="project-grid">
        {projects.map((project) => (
          <div
            key={project.id}
            className="project-card"
            onClick={() => handleCardClick(project)}
          >
            <h3>{project.name}</h3>
            <p>{project.description || 'No description provided.'}</p>
            <p className="visibility-label">
              {project.visibility
                ? project.visibility.charAt(0).toUpperCase() + project.visibility.slice(1)
                : 'N/A'}
            </p>
          </div>
        ))}
        <div className="add-project-card" onClick={() => setShowCreateModal(true)}>
          <span>+</span>
        </div>
      </div>

      {showCreateModal && (
        <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>Create New Project</h3>
            <input
              type="text"
              placeholder="Project Name"
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
            />
            <textarea
              placeholder="Project Description (optional)"
              value={newProjectDescription}
              onChange={(e) => setNewProjectDescription(e.target.value)}
            />
            <div className="modal-actions">
              <button className="primary-btn" onClick={handleCreateProject}>
                Create
              </button>
              <button className="secondary-btn" onClick={() => setShowCreateModal(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProjectList;