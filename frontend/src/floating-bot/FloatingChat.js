import React, { useEffect, useRef, useState } from 'react';
import Draggable from 'react-draggable';
import { useLocation } from 'react-router-dom';
import AIChat from '../components/AIChat';
import '../components/css/FloatingChat.css';

export default function FloatingChat({ onDiff }) {
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  const nodeRef = useRef(null);

  // Extract project/app/file from URL
  const projectMatch = loc.pathname.match(/^\/projects\/([^/]+)/);
  const projectId = projectMatch?.[1];
  const appMatch = loc.pathname.match(/^\/projects\/[^/]+\/apps\/([^/]+)/);
  const appId = appMatch?.[1] || '';
  const filePathMatch = loc.pathname.match(/\/([^/]+)\/?$/);
  const filePath = filePathMatch?.[1] || '';

  const INITIAL_WIDTH = 360;
  const INITIAL_HEIGHT = 480;
  const [position, setPosition] = useState({ left: 0, top: 0 });

  // Hook must always be called — even if we don't render
  useEffect(() => {
    const left = window.innerWidth - 20 - INITIAL_WIDTH;
    const top = window.innerHeight - 90 - INITIAL_HEIGHT;
    setPosition({ left, top });
  }, []);

  // Now safe to do conditional rendering
  if (!projectId) return null;

  return (
    <>
      <div className="floating-icon" onClick={() => setOpen(true)}>🤖</div>

      {open && (
        <Draggable nodeRef={nodeRef} handle=".chat-header"  bounds="parent"  >
          <div
            ref={nodeRef}
            className="resizable-chat-wrapper"
            style={{
              left: position.left,
              top: position.top,
              width: INITIAL_WIDTH,
              height: INITIAL_HEIGHT,
            }}
          >
            <div className="chat-header">
              <span>AI Chat</span>
              <button className="close-btn" onClick={() => setOpen(false)}>
                ✖
              </button>
            </div>
            <AIChat
              projectId={projectId}
              appName={appId}
              filePath={filePath}
              onDiff={onDiff}  
            />
          </div>
        </Draggable>
      )}
    </>
  );
}
