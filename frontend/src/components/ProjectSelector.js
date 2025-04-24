// ProjectSelector.jsx
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import "./css/ProjectSelector.css";

const ProjectSelector = ({ onProjectSelect, suppressNavigation = false }) => {
  const [projects, setProjects] = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectDescription, setNewProjectDescription] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    fetch('/api/projects/', {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
      .then((res) => res.json())
      .then((data) => {
        const projs = data.projects || data;
        setProjects(projs);
        if (projs.length > 0) {
          setSelectedProjectId(projs[0].id);
        }
      })
      .catch((err) => console.error("Error fetching projects:", err));
  }, []);

  const handleProjectChange = (e) => {
    setSelectedProjectId(e.target.value);
  };

  const handleSelect = () => {
    if (!selectedProjectId) {
      alert("Please select a valid project.");
      return;
    }
    const selected = projects.find((p) => p.id === parseInt(selectedProjectId, 10));
    if (selected) {
      onProjectSelect(selected);
      localStorage.setItem('project_id', selected.id);
      if (!suppressNavigation) {
        // Navigate only if not suppressed.
        navigate(`/projects/${selected.id}`);
      }
    } else {
      alert("Please select a valid project.");
    }
  };

  const handleCreateProject = () => {
    if (!newProjectName.trim()) {
      alert("Please enter a project name.");
      return;
    }
    const token = localStorage.getItem('access_token');
    fetch('/api/projects/', {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ 
        name: newProjectName,
        description: newProjectDescription,
      }),
    })
      .then((res) => res.json())
      .then((newProject) => {
        setProjects((prev) => [...prev, newProject]);
        setSelectedProjectId(newProject.id);
        onProjectSelect(newProject);
        localStorage.setItem('project_id', newProject.id);
        setShowCreateModal(false);
        if (!suppressNavigation) {
          navigate(`/projects/${newProject.id}`);
        }
      })
      .catch((err) => {
        console.error("Error creating project:", err);
        alert("Error creating project.");
      });
  };

  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <h2>Select a Project</h2>
      <select
        value={selectedProjectId}
        onChange={handleProjectChange}
        style={{ width: '300px', padding: '0.5rem', fontSize: '1rem' }}
      >
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name} ({project.visibility})
          </option>
        ))}
      </select>
      <div style={{ marginTop: '1rem' }}>
        <button
          onClick={handleSelect}
          style={{ padding: '0.5rem 1rem', fontSize: '1rem', marginRight: '1rem' }}
        >
          Select Project
        </button>
        <button
          onClick={() => setShowCreateModal(true)}
          style={{ padding: '0.5rem 1rem', fontSize: '1rem' }}
        >
          Create Project
        </button>
      </div>
      {showCreateModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.5)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
          }}
        >
          <div
            style={{
              background: 'white',
              padding: '2rem',
              borderRadius: '8px',
              width: '300px',
              textAlign: 'center',
            }}
          >
            <h3>Create New Project</h3>
            <input
              type="text"
              placeholder="Project Name"
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              style={{ width: '100%', padding: '0.5rem', marginBottom: '1rem' }}
            />
            <textarea
              placeholder="Project Description (optional)"
              value={newProjectDescription}
              onChange={(e) => setNewProjectDescription(e.target.value)}
              style={{
                width: '100%',
                padding: '0.5rem',
                marginBottom: '1rem',
                resize: 'vertical',
              }}
            />
            <div>
              <button onClick={handleCreateProject} style={{ marginRight: '1rem' }}>
                Create
              </button>
              <button onClick={() => setShowCreateModal(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProjectSelector;
