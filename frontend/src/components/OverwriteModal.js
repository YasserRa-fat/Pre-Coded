import React from 'react';

const OverwriteModal = ({ 
  existingContent,
  onOverwrite,
  onCancel,
  showDetails
}) => {
  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0,0,0,0.5)',
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center'
    }}>
      <div style={{
        background: 'white',
        padding: '2rem',
        borderRadius: '4px',
        width: '400px'
      }}>
        {showDetails && (
          <>
            <h3>Existing File Content:</h3>
            <pre style={{ maxHeight: '300px', overflow: 'auto' }}>
              {existingContent}
            </pre>
          </>
        )}
        <p>Would you like to overwrite it with your newly generated code?</p>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <button 
            onClick={onCancel}
            style={{ padding: '8px 16px', background: '#6c757d', color: 'white' }}
          >
            Cancel
          </button>
          <button 
            onClick={onOverwrite}
            style={{ padding: '8px 16px', background: '#dc3545', color: 'white' }}
          >
            Overwrite
          </button>
        </div>
      </div>
    </div>
  );
};

export default OverwriteModal;