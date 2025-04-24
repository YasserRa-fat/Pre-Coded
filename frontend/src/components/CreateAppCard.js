import React, { useState } from 'react';

const CreateAppCard = ({ projectId, onAppCreated }) => {
  const [isCreating, setIsCreating] = useState(false);
  const [appName, setAppName] = useState('');

  const handleCreate = async () => {
    if (!appName.trim()) {
      alert("Please enter an app name.");
      return;
    }

    try {
      // Make API call to create app
      const response = await fetch(`/api/apps/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
        body: JSON.stringify({
          name: appName,
          project: projectId, // Associate with the specific project
        }),
      });

      if (response.ok) {
        const newApp = await response.json();
        onAppCreated(newApp);  // Notify parent component about the new app
        setAppName('');
        setIsCreating(false); // Close modal after successful creation
      } else {
        alert("Failed to create app. Please try again.");
      }
    } catch (error) {
      console.error("Error creating app:", error);
      alert("An error occurred. Please try again.");
    }
  };

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
        <p style={{ color: '#aaa' }}>Create App</p>
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
            <h3>Create New App</h3>
            <input
              type="text"
              placeholder="App Name"
              value={appName}
              onChange={(e) => setAppName(e.target.value)}
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

export default CreateAppCard;
