import axios from 'axios';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import './css/AIChat.css';

export default function AIChat({ projectId, appName, filePath, onDiff }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [status, setStatus] = useState('open');
  const [changeId, setChangeId] = useState(null);
  const wsRef = useRef(null);
  const messagesEnd = useRef(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  // Memoize the onDiff callback to use in handlers without dependency issues
  const handleDiff = useCallback((diffData) => {
    if (onDiff) onDiff(diffData);
  }, [onDiff]);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Single connection setup on mount
  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) {
      setMessages(m => [...m, { sender: 'assistant', text: 'Authentication error: No access token' }]);
      return;
    }

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(
      `${proto}://${window.location.hostname}:8001/ws/projects/${projectId}/ai/?token=${token}`
    );

    ws.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
      setMessages(m => [...m, { sender: 'assistant', text: 'AI assistant connected. Ask me to modify your project!' }]);
    };

    ws.onmessage = e => {
      try {
        const msg = JSON.parse(e.data);
        console.log('Received WS message:', msg);
        const kind = msg.type || msg.kind;

        if (kind === 'show_diff_modal') {
          console.log('Handling show_diff_modal:', msg);
          setIsLoading(false);
          
          // Handle files as either an object map or array
          let formattedFiles = [];
          
          if (msg.files) {
            if (Array.isArray(msg.files)) {
              // Already an array format
              formattedFiles = msg.files.map(file => {
                // Ensure it has the right structure
                return {
                  filePath: typeof file === 'string' 
                    ? file.replace(/^templates\//, '') 
                    : (file.filePath || '').replace(/^templates\//, ''),
                  fullPath: typeof file === 'string' ? file : (file.fullPath || file.filePath || ''),
                  before: typeof file === 'object' ? (file.before || '') : (msg.diff?.[file] || ''),
                  after: typeof file === 'object' ? (file.after || '') : (msg.files[file] || ''),
                  projectId,
                  changeId: msg.change_id,
                };
              });
            } else if (typeof msg.files === 'object' && !Array.isArray(msg.files)) {
              // Files is an object map of path -> content
              formattedFiles = Object.keys(msg.files).map(path => ({
                filePath: path.replace(/^templates\//, ''),
                fullPath: path,
                before: msg.diff?.[path] || '',
                after: msg.files[path] || '',
                projectId,
                changeId: msg.change_id,
              }));
            }
          }

          if (!formattedFiles.length) {
            console.error('No files in show_diff_modal:', msg.files);
            setMessages(m => [...m, { sender: 'assistant', text: 'Error: No files to review' }]);
            return;
          }

          setChangeId(msg.change_id);
          setStatus('review');
          
          // Default preview URLs if none provided
          const previewMap = msg.previewMap || {
            before: `/api/projects/${projectId}/preview/?mode=before`,
            after: `/api/projects/${projectId}/preview/?change_id=${msg.change_id}&mode=after`
          };
          
          handleDiff({
            files: formattedFiles,
            previewMap,
            change_id: msg.change_id,
            beforeMap: msg.diff || {},
            afterMap: msg.files || {}
          });
          return;
        }

        if (kind === 'error') {
          console.error('Server error:', msg.message);
          setIsLoading(false);
          setMessages(m => [...m, { sender: 'assistant', text: `Error: ${msg.message}` }]);
          return;
        }

        if (kind === 'status') {
          if (msg.status === 'thinking') {
            setIsLoading(true);
          } else {
            setIsLoading(false);
          }
        }

        if (msg.sender && msg.text) {
          setMessages(m => [...m, { sender: msg.sender, text: msg.text }]);
          if (msg.sender === 'assistant') {
            setIsLoading(false);
          }
        }
      } catch (err) {
        console.error('Error parsing WS message:', err);
        setIsLoading(false);
      }
    };

    ws.onerror = e => {
      console.error('WebSocket error:', e);
      setIsConnected(false);
      setIsLoading(false);
      setMessages(m => [...m, { sender: 'assistant', text: 'WebSocket connection error' }]);
    };

    ws.onclose = e => {
      console.log('WebSocket closed:', e.code, e.reason);
      setIsConnected(false);
      setIsLoading(false);
      
      // Only show reconnection message if there was a connection before
      if (isConnected) {
        setMessages(m => [...m, { sender: 'assistant', text: 'Connection closed. Refresh to reconnect.' }]);
      }
    };

    wsRef.current = ws;

    // Cleanup on unmount
    return () => {
      if (wsRef.current) {
        console.log('Closing WebSocket connection');
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [projectId, handleDiff]);

  const sendMessage = () => {
    if (!input.trim() || !wsRef.current || !isConnected) return;
    console.log('Sending message:', input);
    wsRef.current.send(JSON.stringify({ type: 'chat_message', text: input }));
    setMessages(m => [...m, { sender: 'user', text: input }]);
    setInput('');
    setIsLoading(true);
  };

  const confirm = () => {
    if (wsRef.current && changeId) {
      console.log('Confirming change:', changeId);
      wsRef.current.send(JSON.stringify({ type: 'confirm_changes', change_id: changeId }));
      setStatus('open');
      setChangeId(null);
      setMessages(m => [...m, { sender: 'assistant', text: 'Changes applied successfully.' }]);
    }
  };

  const cancel = () => {
    if (!changeId) return;
    console.log('Canceling change:', changeId);
    axios
      .post(
        `/api/ai/conversations/${changeId}/cancel/`,
        {},
        { headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` } }
      )
      .then(() => {
        setStatus('open');
        setChangeId(null);
        setMessages(m => [...m, { sender: 'assistant', text: 'Changes discarded.' }]);
      })
      .catch(err => {
        console.error('Error canceling:', err);
        setMessages(m => [...m, { sender: 'assistant', text: `Error discarding: ${err.message}` }]);
      });
  };

  return (
    <div className="ai-chat-widget">
      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.sender}`}>
            <div className="bubble-text">{m.text}</div>
          </div>
        ))}
        {isLoading && (
          <div className="msg assistant">
            <div className="bubble-text typing-indicator">
              <span></span><span></span><span></span>
            </div>
          </div>
        )}
        <div ref={messagesEnd} />
      </div>

      {status === 'review' && (
        <div className="review-buttons">
          <button onClick={confirm}>Apply Changes</button>
          <button onClick={cancel}>Cancel</button>
        </div>
      )}

      <div className="input-row">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && sendMessage()}
          placeholder="Ask AI to modify..."
          disabled={!isConnected || isLoading || status === 'review'}
        />
        <button 
          className="send-btn" 
          onClick={sendMessage} 
          disabled={!isConnected || isLoading || status === 'review'}>
          Send
        </button>
      </div>
    </div>
  );
}