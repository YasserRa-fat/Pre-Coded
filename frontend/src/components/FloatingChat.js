import React, { useCallback, useEffect, useRef, useState } from 'react';
import Draggable from 'react-draggable';
import AIChat from './AIChat';
import './css/FloatingChat.css';

export default function FloatingChat({ projectId, appName, filePath }) {
  const [isOpen, setIsOpen] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const chatRef = useRef(null);
  const dragTimeoutRef = useRef(null);

  // Handle window resize
  useEffect(() => {
    const handleResize = () => {
      if (chatRef.current) {
        const bounds = {
          right: window.innerWidth - chatRef.current.offsetWidth,
          bottom: window.innerHeight - chatRef.current.offsetHeight
        };
        setPosition(pos => ({
          x: Math.min(bounds.right, pos.x),
          y: Math.min(bounds.bottom, pos.y)
        }));
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleDragStart = () => {
    setIsDragging(true);
    if (dragTimeoutRef.current) {
      clearTimeout(dragTimeoutRef.current);
    }
  };

  const handleDragStop = () => {
    // Use a short timeout to distinguish between drag and click
    dragTimeoutRef.current = setTimeout(() => {
      setIsDragging(false);
    }, 100);
  };

  const handleDrag = (e, data) => {
    setPosition({ x: data.x, y: data.y });
  };

  const toggleChat = useCallback(() => {
    if (!isDragging) {
      setIsOpen(open => !open);
    }
  }, [isDragging]);

  const handleDiff = useCallback((diffData) => {
    // Handle diff data if needed
    console.log('Diff data:', diffData);
    
    // If this component is a child of ProjectDetail, forward the diff data
    if (window.parent && typeof window.parent.handleDiffFromChat === 'function') {
      window.parent.handleDiffFromChat(diffData);
    }
  }, []);

  return (
    <Draggable
      handle=".chat-header"
      position={position}
      onStart={handleDragStart}
      onStop={handleDragStop}
      onDrag={handleDrag}
      bounds="parent"
    >
      <div 
        ref={chatRef}
        className={`floating-chat ${isOpen ? 'open' : ''}`}
      >
        <div className="chat-header" onClick={toggleChat}>
          <span>AI Assistant</span>
          <button className="toggle-btn">
            {isOpen ? '−' : '+'}
          </button>
        </div>
        {/* Always keep AIChat mounted but hide it when chat is closed */}
        <div className={`chat-content ${isOpen ? 'visible' : 'hidden'}`}>
          <AIChat
            key={`chat-${projectId}-${appName || ''}-${filePath || ''}`}
            projectId={projectId}
            appName={appName}
            filePath={filePath}
            onDiff={handleDiff}
          />
        </div>
      </div>
    </Draggable>
  );
} 