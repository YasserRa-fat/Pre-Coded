// src/chat-widget/index.jsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import Draggable from 'react-draggable';
import AIChat from '../components/AIChat'; // your existing chat panel

function FloatingChat({ projectId, appName, filePath }) {
  const [open, setOpen] = React.useState(false);

  return (
    <>
      {/* Floating icon */}
      <div
        onClick={() => setOpen(true)}
        style={{
          position: 'fixed',
          bottom: 20,
          right: 20,
          width: 60,
          height: 60,
          borderRadius: '50%',
          background: '#007bff',
          color: '#fff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          zIndex: 10000
        }}
      >
        🤖
      </div>

      {open && (
        <Draggable>
          <div
            style={{
              position: 'fixed',
              bottom: 100,
              right: 20,
              width: 320,
              height: 400,
              background: '#fff',
              border: '1px solid #ccc',
              borderRadius: 8,
              boxShadow: '0 2px 10px rgba(0,0,0,0.2)',
              zIndex: 10000,
              display: 'flex',
              flexDirection: 'column'
            }}
          >
            <button
              onClick={() => setOpen(false)}
              style={{ alignSelf: 'flex-end', margin: 4 }}
            >
              ✖
            </button>
            <div style={{ flex: 1, overflow: 'auto' }}>
              <AIChat
                projectId={projectId}
                appName={appName}
                filePath={filePath}
              />
            </div>
          </div>
        </Draggable>
      )}
    </>
  );
}

// find the mount point Django will render
const el = document.getElementById('chatbot-root');
if (el) {
  const projectId = el.dataset.projectId;
  const appName   = el.dataset.appName   || '';
  const filePath  = el.dataset.filePath  || '';
  createRoot(el).render(
    <FloatingChat projectId={projectId} appName={appName} filePath={filePath}/>
  );
}
