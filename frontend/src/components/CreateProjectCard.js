import React, { useState } from 'react';

const CreateProjectCard = ({ onProjectCreated }) => {
  const [isCreating, setIsCreating] = useState(false);
  const [projectName, setProjectName] = useState('');

  const handleCreate = () => {
    if (!projectName.trim()) {
      alert("Please enter a project name.");
      return;
    }
    // Make API call to create project.
    // Include authentication headers if necessary.
    fetch('/api/projects/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('access_token')}` // Ensure authentication
      },
      body: JSON.stringify({
        name: projectName,
        description: "Default description", // Provide a default or let the user input it
        visibility: "private", // Adjust as needed, depending on your model
      }),
    })
    
  return (
    <div>
      <div
        onClick={() => setIsCreating(true)}
        style={{
          border: '2px dashed #aaa',
          borderRadius: '8px',
          width: '200px',
          height: '150px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          cursor: 'pointer',
          margin: '1rem',
        }}
      >
        <span style={{ fontSize: '3rem', color: '#aaa' }}>+</span>
        <p style={{ color: '#aaa' }}>Create Project</p>
      </div>

      {isCreating && (
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
            zIndex: 1000,
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
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              style={{
                width: '100%',
                padding: '0.5rem',
                marginBottom: '1rem',
                fontSize: '1rem',
              }}
            />
            <div>
              <button
                onClick={handleCreate}
                style={{
                  padding: '0.5rem 1rem',
                  marginRight: '1rem',
                  fontSize: '1rem',
                }}
              >
                Create
              </button>
              <button
                onClick={() => setIsCreating(false)}
                style={{ padding: '0.5rem 1rem', fontSize: '1rem' }}
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

export default CreateProjectCard;
