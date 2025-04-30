// src/components/AIChat.js

import React, { useEffect, useRef, useState } from 'react';
import './css/AIChat.css';

export default function AIChat({ projectId, appName, filePath }) {
  const [convId, setConvId]       = useState(null);
  const [messages, setMessages]   = useState([]);
  const [input, setInput]         = useState('');
  const [status, setStatus]       = useState('open');
  const [changeId, setChangeId]   = useState(null);
  const wsRef = useRef(null);

  const token = localStorage.getItem('access_token');
  const authHeader = { 'Authorization': `Bearer ${token}` };

  // 1) start a conversation on mount
  useEffect(() => {
    fetch('/api/ai/conversations/', {
      method: 'POST',
      headers: {
        ...authHeader,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        project:   projectId,
        app_name:  appName,
        file_path: filePath
      })
    })
    .then(res => res.json())
    .then(data => setConvId(data.id))
    .catch(console.error);
  }, [projectId, appName, filePath]);

  // 2) open WebSocket once we have convId
  useEffect(() => {
    if (!convId) return;
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  
    const wsHost = process.env.NODE_ENV === 'development'
      ? 'localhost:8000'
      : window.location.host;
  
    const ws = new WebSocket(
      `${proto}://${wsHost}/ws/projects/${projectId}/`
    );
  
    ws.onopen = () => console.log('WS connected for AI chat');
    ws.onmessage = e => {
      const { chat } = JSON.parse(e.data);
      if (chat.conversation_id === convId) {
        setMessages(chat.messages);
        const last = chat.changes[chat.changes.length - 1];
        setChangeId(last?.id ?? null);
        setStatus(chat.changes.length ? 'review' : 'open');
      }
    };
    ws.onclose = () => console.log('WS closed');
  
    wsRef.current = ws;
    return () => ws.close();
  }, [convId, projectId]);
  

  const sendMessage = () => {
    if (!input.trim() || !convId) return;
    setMessages(msgs => [...msgs, { sender:'user', text: input }]);
    fetch(`/api/ai/conversations/${convId}/message/`, {
      method: 'POST',
      headers: {
        ...authHeader,
        'Content-Type':'application/json'
      },
      body: JSON.stringify({
        message: input,
        file_type: filePath.endsWith('.html') ? 'template' :
                   filePath.endsWith('models.py') ? 'model' :
                   filePath.endsWith('views.py')  ? 'view' :
                   filePath.endsWith('forms.py')  ? 'form' : 'other'
      })
    });
    setInput('');
  };

  const applyChange = () => {
    fetch(`/api/ai/conversations/${convId}/confirm/`, {
      method: 'POST',
      headers: {
        ...authHeader,
        'Content-Type':'application/json'
      },
      body: JSON.stringify({ change_id: changeId })
    })
    .then(() => setStatus('closed'))
    .catch(console.error);
  };

  const cancelChange = () => {
    fetch(`/api/ai/conversations/${convId}/cancel/`, {
      method:'POST',
      headers: authHeader
    })
    .then(() => setStatus('cancelled'))
    .catch(console.error);
  };

  return (
    <div className="ai-chat-widget">
      <div className="messages">
        {messages.map((m,i) => (
          <div key={i} className={`msg ${m.sender}`}>
            <b>{m.sender}:</b> {m.text}
          </div>
        ))}
      </div>

      {status === 'review' && (
        <div className="review-buttons">
          <button onClick={applyChange}>Apply Changes</button>
          <button onClick={cancelChange}>Cancel</button>
        </div>
      )}

      {status !== 'closed' && (
        <div className="input-row">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendMessage()}
            placeholder="Ask AI to modify this file…"
          />
          <button onClick={sendMessage}>Send</button>
        </div>
      )}
    </div>
  );
}
