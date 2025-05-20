import React, { useCallback, useEffect, useRef, useState } from 'react';
import Draggable from 'react-draggable';
import { useLocation } from 'react-router-dom';
import AIChat from '../components/AIChat';
import '../components/css/FloatingChat.css';
import { useDiff } from '../context/DiffContext';

export default function FloatingChat({ onDiff, projectId }) {
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  const nodeRef = useRef(null);
  const lastDiffData = useRef(null);
  const hiddenChatRef = useRef(null);
  const hasReappliedDiff = useRef(false);
  const { setChatOpen } = useDiff();

  // Extract project/app/file from URL
  const projectMatch = loc.pathname.match(/^\/projects\/([^/]+)/);
  const projectId2 = projectMatch?.[1] || projectId;
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

  // Update chat open state in DiffContext
  useEffect(() => {
    setChatOpen(open);
  }, [open, setChatOpen]);

  // Check for stored diff data on component mount but don't auto-apply
  useEffect(() => {
    try {
      const storedData = localStorage.getItem(`diff_data_${projectId2}`);
      if (storedData) {
        console.log('Found stored diff data in localStorage');
        lastDiffData.current = JSON.parse(storedData);
      }
    } catch (err) {
      console.error('Error loading stored diff data:', err);
    }
  }, [projectId2]);

  // Forward diff data to parent component - only when explicitly received from AIChat
  const handleAIChatDiff = useCallback((diffData) => {
    // Only process if this is a new diff (not just restoring previous state)
    if (!diffData.isRestoring) {
      // Save the complete diff data
      lastDiffData.current = diffData;
      
      console.log('FloatingChat received new diff data with files:', diffData.files?.length);
      
      // Store in localStorage for persistence
      try {
        localStorage.setItem(`diff_data_${projectId2}`, JSON.stringify(diffData));
      } catch (err) {
        console.error('Error storing diff data from FloatingChat:', err);
      }
      
      // Call the parent onDiff handler
      if (typeof onDiff === 'function') {
        onDiff(diffData);
      }
      
      // Also call the global handler if available (backup mechanism)
      if (typeof window.handleDiffFromChat === 'function') {
        window.handleDiffFromChat(diffData);
      }
    }
  }, [onDiff, projectId2]);

  // When chat is closed, we don't force the hidden chat to reapply diff data
  // Only reapply diff data if it's an explicit action from the user
  useEffect(() => {
    if (!open && hiddenChatRef.current && lastDiffData.current && !hasReappliedDiff.current) {
      // Do nothing - we no longer auto-reapply diff data when chat is closed
      // The diff modal should be managed independently through ProjectDetail.js
    }
  }, [open]);

  // Now safe to do conditional rendering
  if (!projectId2) return null;

  return (
    <>
      <div className="floating-icon" onClick={() => setOpen(true)}>🤖</div>

      {open && (
        <Draggable nodeRef={nodeRef} handle=".chat-header" bounds="parent">
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
              projectId={projectId2}
              appName={appId}
              filePath={filePath}
              onDiff={handleAIChatDiff}  
            />
          </div>
        </Draggable>
      )}
      
      {/* Hidden AIChat instance to maintain WebSocket connection when chat is closed */}
      {!open && (
        <div 
          ref={hiddenChatRef}
          style={{ 
            display: 'none', 
            visibility: 'hidden', 
            height: 0, 
            overflow: 'hidden', 
            opacity: 0,
            position: 'absolute',
            pointerEvents: 'none' 
          }}
        >
          <AIChat
            projectId={projectId2}
            appName={appId}
            filePath={filePath}
            onDiff={handleAIChatDiff}
            hiddenInstance={true}
          />
        </div>
      )}
    </>
  );
}
