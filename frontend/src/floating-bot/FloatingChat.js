// src/floating-bot/FloatingChat.jsx

import React, { useRef, useState } from 'react';
import Draggable from 'react-draggable';
import { useLocation } from 'react-router-dom';
import AIChat from '../components/AIChat';

export default function FloatingChat() {
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  // 1️⃣ create a ref for Draggable
  const nodeRef = useRef(null);

  // Manually extract projectId and appId from the URL:
  const projectMatch = loc.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch ? projectMatch[1] : null;

  const appMatch = loc.pathname.match(
    /^\/projects\/[^/]+\/apps\/([^/]+)/
  );
  const appId = appMatch ? appMatch[1] : null;

  // Extract the filePath (last segment)
  const filePathMatch = loc.pathname.match(/\/([^/]+)\/?$/);
  const filePath = filePathMatch?.[1] || '';

  // Only show on any /projects/:projectId/... route
  const shouldShow = Boolean(projectId);

  if (!shouldShow) return null;

  return (
    <>
      {/* floating icon */}
      <div
        onClick={() => setOpen(true)}
        style={{
          position: 'fixed',
          bottom: 20,
          right: 20,
          width: 56,
          height: 56,
          borderRadius: '50%',
          background: '#007bff',
          color: '#fff',
          fontSize: 28,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          zIndex: 10000,
        }}
      >
        🤖
      </div>

      {open && (
       <Draggable nodeRef={nodeRef} handle=".chat-header">
          <div
            style={{
              position: 'fixed',
              bottom: 90,
              right: 20,
              width: 320,
              height: 400,
              background: '#fff',
              border: '1px solid #ccc',
              borderRadius: 8,
              boxShadow: '0 2px 10px rgba(0,0,0,0.2)',
              zIndex: 10000,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            {/* HEADER */}
            <div
              className="chat-header"
              style={{
                cursor: 'move',
                padding: '4px 8px',
                borderBottom: '1px solid #eee',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <strong>AI Chat</strong>
              <button
                onClick={() => setOpen(false)}
                style={{ border: 'none', background: 'none', cursor: 'pointer' }}
              >
                ✖
              </button>
            </div>

            {/* CHAT BODY */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
              <AIChat
                projectId={projectId}
                appName={appId || ''}
                filePath={filePath}
              />
            </div>
          </div>
        </Draggable>
      )}
    </>
  );
}
