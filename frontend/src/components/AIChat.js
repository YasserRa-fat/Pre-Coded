import axios from 'axios';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import './css/AIChat.css';

// Get WebSocket host from environment or use default Django development server
const WS_HOST = process.env.REACT_APP_WS_HOST || window.location.hostname + ':8001';

export default function AIChat({ projectId, appName, filePath, onDiff }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [status, setStatus] = useState('open');
  const [changeId, setChangeId] = useState(null);
  const [accessToken, setAccessToken] = useState(localStorage.getItem('access_token'));
  const wsRef = useRef(null);
  const messagesEnd = useRef(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [connectionError, setConnectionError] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const isComponentMounted = useRef(true);
  const processingTimeoutRef = useRef(null);
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 5; // Increased from 3 to 5
  const reconnectDelay = 1000; // 1 second
  const connectionTimeoutRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const pingIntervalRef = useRef(null); // For sending periodic pings

  const handleDiff = useCallback((diffData) => {
    if (onDiff) onDiff(diffData);
  }, [onDiff]);

  const cleanupWebSocket = useCallback(() => {
    // Clear all timeouts
    [processingTimeoutRef, connectionTimeoutRef, reconnectTimeoutRef, pingIntervalRef].forEach(ref => {
      if (ref.current) {
        clearTimeout(ref.current);
        clearInterval(ref.current);
        ref.current = null;
      }
    });
    
    // Clean up WebSocket
    if (wsRef.current) {
      const ws = wsRef.current;
      wsRef.current = null; // Clear ref first to prevent reconnection attempts
      
      // Remove all listeners
      ws.onopen = null;
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      
      // Close connection if needed
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        try {
          ws.close(1000, "Cleanup");
        } catch (err) {
          console.error('Error closing WebSocket:', err);
        }
      }
    }
  }, []);

  const connectWebSocket = useCallback(() => {
    if (!isComponentMounted.current) {
      console.log('Component not mounted, skipping connection');
      return;
    }

    // Clean up any existing connection
    cleanupWebSocket();

    // Check for token
    if (!accessToken) {
      console.error('No access token found');
      setConnectionError(true);
      setMessages(m => [...m, { 
        sender: 'assistant', 
        text: 'Authentication error: No access token found. Please log in again.' 
      }]);
      return;
    }

    // Check reconnection attempts
    if (reconnectAttempts.current >= maxReconnectAttempts) {
      console.error(`Max reconnection attempts (${maxReconnectAttempts}) reached`);
      setConnectionError(true);
      return;
    }

    try {
      reconnectAttempts.current++;
      console.log(`Connection attempt ${reconnectAttempts.current} of ${maxReconnectAttempts}`);

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${WS_HOST}/ws/projects/${projectId}/ai/?token=${accessToken}${appName ? `&app_name=${encodeURIComponent(appName)}` : ''}${filePath ? `&file_path=${encodeURIComponent(filePath)}` : ''}`;
      
      console.log('Connecting to:', wsUrl.replace(accessToken, 'TOKEN_HIDDEN'));
      console.log('Using WebSocket host:', WS_HOST);
      
      // Create a new WebSocket instance
      const ws = new WebSocket(wsUrl);
      
      // Set binary type to ensure proper message handling
      ws.binaryType = 'arraybuffer';
      
      // Store reference to the WebSocket
      wsRef.current = ws;

      // Set connection timeout
      connectionTimeoutRef.current = setTimeout(() => {
        if (ws.readyState !== WebSocket.OPEN) {
          console.error('Connection timeout');
          console.error('WebSocket state:', ws.readyState);
          cleanupWebSocket();
          
          // Only attempt reconnect if we haven't reached max attempts
          if (reconnectAttempts.current < maxReconnectAttempts && isComponentMounted.current) {
            const delay = reconnectDelay * Math.pow(2, reconnectAttempts.current - 1);
            console.log(`Retrying in ${delay}ms...`);
            reconnectTimeoutRef.current = setTimeout(connectWebSocket, delay);
          }
        }
      }, 5000);

      ws.onopen = () => {
        if (!isComponentMounted.current) {
          cleanupWebSocket();
          return;
        }
        
        console.log('WebSocket connected successfully');
        
        // Slight delay before doing any operations to let the connection stabilize
        setTimeout(() => {
          if (ws.readyState !== WebSocket.OPEN) {
            console.log('WebSocket no longer open after delay');
            return;
          }
          
          setIsConnected(true);
          setConnectionError(false);
          reconnectAttempts.current = 0;
          
          // Setup ping interval to keep connection alive - with a delay before first ping
          setTimeout(() => {
            if (isComponentMounted.current && ws.readyState === WebSocket.OPEN) {
              pingIntervalRef.current = setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) {
                  console.log('Sending ping to keep connection alive');
                  try {
                    ws.send(JSON.stringify({ type: 'ping' }));
                  } catch (err) {
                    console.error('Error sending ping:', err);
                  }
                }
              }, 30000); // Send ping every 30 seconds
            }
          }, 5000); // Wait 5 seconds before starting ping interval
          
          if (messages.length === 0) {
            const contextMsg = appName ? 
              `AI assistant connected. I'm focused on the ${appName} app. How can I help?` :
              filePath ?
              `AI assistant connected. I'm focused on ${filePath}. How can I help?` :
              'AI assistant connected. Ask me to modify your project!';
            setMessages([{ sender: 'assistant', text: contextMsg }]);
          }
        }, 1000); // Wait 1 second before any UI updates or interactions
      };

      // Use a local message handler to prevent closure issues
      const handleMessage = async (e) => {
        // Ensure component is still mounted
        if (!isComponentMounted.current) return;
        
        let data = e.data;
        console.log('Raw message received type:', typeof data);
        
        try {
          // Check if message is a ping response
          if (data === 'pong' || data === '{"type":"pong"}') {
            console.log('Received pong');
            return;
          }
          
          // Parse the JSON message
          let msg;
          if (typeof data === 'string') {
            msg = JSON.parse(data);
          } else {
            // Handle binary data if needed
            const textDecoder = new TextDecoder('utf-8');
            const jsonString = textDecoder.decode(data);
            msg = JSON.parse(jsonString);
          }
          
          console.log('Received message type:', msg.type || msg.kind);
          
          const kind = msg.type || msg.kind;
          
          if (kind === 'connection_established') {
            setIsConnected(true);
            setConnectionError(false);
            return;
          }

          if (kind === 'connection_error' || kind === 'error') {
            console.error('Server error:', msg.message);
            setIsLoading(false);
            setIsProcessing(false);
            setMessages(m => [...m, { 
              sender: 'assistant', 
              text: msg.message.includes('conversation') ?
                'Error with conversation. Please refresh the page to start a new session.' :
                `Error: ${msg.message}`
            }]);
            return;
          }
          
          // Handle ping response for keeping connection alive
          if (kind === 'ping' || kind === 'pong') {
            console.log('Received ping/pong');
            return;
          }

          if (kind === 'status') {
            setIsLoading(msg.status === 'thinking');
            return;
          }

          if (kind === 'chat_message') {
            setMessages(m => [...m, { sender: msg.sender, text: msg.text }]);
            if (msg.sender === 'assistant') {
              // Start a timeout to clear processing state
              if (processingTimeoutRef.current) {
                clearTimeout(processingTimeoutRef.current);
              }
              processingTimeoutRef.current = setTimeout(() => {
                setIsLoading(false);
                setIsProcessing(false);
              }, 1000); // Give server time to complete processing
            }
            return;
          }

          if (kind === 'show_diff_modal') {
            console.log('Handling show_diff_modal:', msg);
            if (processingTimeoutRef.current) {
                clearTimeout(processingTimeoutRef.current);
            }
            setIsLoading(false);
            setIsProcessing(false);

            try {
                let formattedFiles = [];
                const files = msg.files;
                const diff = msg.diff || {};

                if (Array.isArray(files)) {
                    formattedFiles = files.map(file => {
                        if (typeof file === 'object' && file.filePath) {
                            return {
                                ...file,
                                filePath: file.filePath.replace(/^templates\//, ''),
                                projectId,
                                changeId: msg.change_id
                            };
                        }
                        return {
                            filePath: file.replace(/^templates\//, ''),
                            fullPath: file,
                            before: diff[file] || '',
                            after: files[file] || diff[file] || '',
                            projectId,
                            changeId: msg.change_id
                        };
                    });
                } else if (typeof files === 'object') {
                    formattedFiles = Object.entries(files).map(([path, content]) => ({
                        filePath: path.replace(/^templates\//, ''),
                        fullPath: path,
                        before: diff[path] || '',
                        after: content || '',
                        projectId,
                        changeId: msg.change_id
                    }));
                }

                if (!formattedFiles.length) {
                    throw new Error('No files to review');
                }

                console.log('Formatted files for diff modal:', formattedFiles);
                
                // Call onDiff with the formatted data
                onDiff({
                    files: formattedFiles,
                    previewMap: msg.previewMap || {},
                    change_id: msg.change_id
                });
                
                setChangeId(msg.change_id);
                setStatus('review');
            } catch (error) {
                console.error('Error processing diff modal data:', error);
                setMessages(m => [...m, { sender: 'assistant', text: `Error: ${error.message}` }]);
            }
          }
        } catch (err) {
          console.error('Error handling message:', err, data);
        }
      };

      // Set message handler
      ws.onmessage = handleMessage;

      ws.onerror = (e) => {
        if (!isComponentMounted.current) return;
        console.error('WebSocket error:', e);
        setIsConnected(false);
        setConnectionError(true);
        setIsLoading(false);
        setIsProcessing(false);
      };

      ws.onclose = (e) => {
        if (!isComponentMounted.current) return;
        console.log('WebSocket closed:', e.code, e.reason);
        setIsConnected(false);
        setIsLoading(false);
        setIsProcessing(false);

        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }

        // Only attempt reconnect for abnormal closures or if we didn't initiate the close
        if (e.code !== 1000 && e.code !== 1001) {
          setConnectionError(true);
          if (reconnectAttempts.current < maxReconnectAttempts) {
            const delay = reconnectDelay * Math.pow(2, reconnectAttempts.current - 1);
            console.log(`Connection closed. Retrying in ${delay}ms...`);
            reconnectTimeoutRef.current = setTimeout(connectWebSocket, delay);
          }
        }
      };

    } catch (error) {
      console.error('Error in connectWebSocket:', error);
      setConnectionError(true);
      if (reconnectAttempts.current < maxReconnectAttempts && isComponentMounted.current) {
        const delay = reconnectDelay * Math.pow(2, reconnectAttempts.current - 1);
        reconnectTimeoutRef.current = setTimeout(connectWebSocket, delay);
      }
    }
  }, [projectId, appName, filePath, messages.length, cleanupWebSocket, reconnectDelay, maxReconnectAttempts, accessToken, onDiff]);

  // Initialize component
  useEffect(() => {
    console.log('Initializing AIChat component');
    isComponentMounted.current = true;
    reconnectAttempts.current = 0;
    connectWebSocket();

    return () => {
      console.log('Cleaning up AIChat component');
      isComponentMounted.current = false;
      cleanupWebSocket();
    };
  }, [connectWebSocket, cleanupWebSocket, accessToken]);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Add automatic reconnection on connection loss
  useEffect(() => {
    let reconnectTimer = null;

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
          console.log('Page visible, attempting reconnection...');
          connectWebSocket();
        }
      }
    };

    const handleOnline = () => {
      console.log('Network online, attempting reconnection...');
      connectWebSocket();
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('online', handleOnline);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('online', handleOnline);
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
    };
  }, [connectWebSocket]);

  // Add effect to update token if it changes in localStorage
  useEffect(() => {
    const handleStorageChange = (e) => {
      if (e.key === 'access_token') {
        setAccessToken(e.newValue);
      }
    };
    
    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, []);

  // Update token state when it changes in localStorage
  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token !== accessToken) {
      setAccessToken(token);
    }
  }, [accessToken]);

  const sendMessage = useCallback((text) => {
    if (!text.trim()) return;

    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setMessages(m => [...m, { 
        sender: 'assistant', 
        text: 'Connection lost. Please refresh the page to reconnect.' 
      }]);
      setConnectionError(true);
      return;
    }

    // Cache the message locally
    const messageText = text.trim();
    console.log('Preparing to send message:', messageText);
    
    // Update UI state first
    setInput('');
    setIsProcessing(true);
    setIsLoading(true);
    setMessages(m => [...m, { sender: 'user', text: messageText }]);
    
    // Delay sending to allow UI to update and connection to stabilize
    setTimeout(() => {
      try {
        // Check again if WebSocket is still connected
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
          console.error('WebSocket closed before sending message');
          setConnectionError(true);
          setIsProcessing(false);
          setIsLoading(false);
          return;
        }
        
        // Log and send the message
        console.log('Sending message to WebSocket');
        wsRef.current.send(JSON.stringify({ 
          type: 'chat_message', 
          text: messageText 
        }));
        console.log('Message sent successfully');
      } catch (err) {
        console.error('Error sending message:', err);
        setMessages(m => [...m, { 
          sender: 'assistant', 
          text: 'Error sending message. Please refresh the page to reconnect.' 
        }]);
        setConnectionError(true);
        setIsProcessing(false);
        setIsLoading(false);
      }
    }, 500); // 500ms delay before sending
  }, []);

  const handleInputSubmit = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }, [input, sendMessage]);

  const confirm = () => {
    if (!changeId) return;

    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setMessages(m => [...m, { sender: 'assistant', text: 'Reconnecting before applying changes...' }]);
      connectWebSocket();
      setTimeout(() => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          doConfirm();
        } else {
          setMessages(m => [...m, { sender: 'assistant', text: 'Cannot connect to server. Please try again.' }]);
          setConnectionError(true);
        }
      }, 1000);
      return;
    }

    doConfirm();
  };

  const doConfirm = () => {
    console.log('Confirming change:', changeId);
    try {
      wsRef.current.send(JSON.stringify({ type: 'confirm_changes', change_id: changeId }));
      setStatus('open');
      setChangeId(null);
      setMessages(m => [...m, { sender: 'assistant', text: 'Changes applied successfully.' }]);
    } catch (err) {
      console.error('Error confirming changes:', err);
      setMessages(m => [...m, { sender: 'assistant', text: 'Error applying changes. Please try reconnecting.' }]);
      setConnectionError(true);
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
          onKeyDown={handleInputSubmit}
          placeholder="Ask AI to modify..."
          disabled={!isConnected || isLoading || status === 'review'}
        />
        <button
          className="send-btn"
          onClick={() => sendMessage(input)}
          disabled={!isConnected || isLoading || status === 'review'}
        >
          Send
        </button>
        {connectionError && (
          <button
            className="refresh-btn"
            onClick={() => window.location.reload()}
          >
            Refresh Page
          </button>
        )}
      </div>
    </div>
  );
}