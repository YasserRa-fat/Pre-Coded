import axios from 'axios';
import React, { useEffect, useState } from 'react';
import './css/DiffModal.css';

// Improved syntax highlighting function
const highlightCode = (code) => {
  if (!code) return '';
  
  // Create a safer approach using React elements instead of dangerouslySetInnerHTML
  const lines = code.split('\n');
  return lines.map((line, lineIndex) => {
    // Simple token types
    const tokens = [];
    let current = '';
    let inString = false;
    let stringChar = '';
    let inComment = false;
    
    // Process each character
    for (let i = 0; i < line.length; i++) {
      const char = line[i];
      
      // Handle comments (highest priority)
      if (char === '#' && !inString) {
        if (current) {
          tokens.push({ type: 'text', content: current });
          current = '';
        }
        tokens.push({ type: 'comment', content: line.slice(i) });
        break;
      }
      
      // Handle strings
      if ((char === '"' || char === "'") && !inComment) {
        if (inString && char === stringChar) {
          // End of string
          current += char;
          tokens.push({ type: 'string', content: current });
          current = '';
          inString = false;
        } else if (!inString) {
          // Start of string
          if (current) {
            tokens.push({ type: 'text', content: current });
            current = '';
          }
          current = char;
          inString = true;
          stringChar = char;
        } else {
          // Different quote inside a string
          current += char;
        }
        continue;
      }
      
      if (inString || inComment) {
        current += char;
        continue;
      }
      
      // Normal code
      current += char;
    }
    
    // Add any remaining text
    if (current) {
      tokens.push({ type: 'text', content: current });
    }
    
    // Process keywords, functions, etc. in text tokens
    const processedTokens = tokens.map(token => {
      if (token.type !== 'text') return token;
      
      // Python keywords
      const pythonKeywords = [
        'class', 'def', 'return', 'import', 'from', 'as', 'if', 'else', 'elif', 
        'for', 'while', 'in', 'try', 'except', 'with', 'not', 'and', 'or', 
        'is', 'None', 'True', 'False', 'self', 'models'
      ];
      
      let result = token.content;
      
      // Apply keyword highlighting
      for (const keyword of pythonKeywords) {
        const regex = new RegExp(`\\b${keyword}\\b`, 'g');
        if (regex.test(result)) {
          // This is a simplification - in a real app, you'd need a more sophisticated tokenizer
          const parts = result.split(new RegExp(`(\\b${keyword}\\b)`, 'g'));
          const highlightedParts = parts.map((part, i) => 
            part === keyword ? 
              <span key={i} className="token keyword">{part}</span> : 
              part
          );
          return { type: 'jsx', content: highlightedParts };
        }
      }
      
      // Match function calls
      if (/\w+\(/.test(result)) {
        const funcMatch = result.match(/(\w+)(\()/);
        if (funcMatch) {
          const [fullMatch, funcName, paren] = funcMatch;
          const index = result.indexOf(fullMatch);
          const before = result.slice(0, index);
          const after = result.slice(index + funcName.length + 1);
          
          return {
            type: 'jsx',
            content: (
              <>
                {before}
                <span className="token function">{funcName}</span>
                {paren}{after}
              </>
            )
          };
        }
      }
      
      // Match numbers
      if (/\b\d+\b/.test(result)) {
        const parts = result.split(/(\b\d+\b)/g);
        const highlightedParts = parts.map((part, i) => 
          /^\d+$/.test(part) ? 
            <span key={i} className="token number">{part}</span> : 
            part
        );
        return { type: 'jsx', content: highlightedParts };
      }
      
      return token;
    });
    
    // Render the line
    return (
      <div key={lineIndex} className="diff-line">
        <span className="diff-line-number"></span>
        <div className="diff-line-content">
          {processedTokens.map((token, i) => {
            if (token.type === 'text') return token.content;
            if (token.type === 'jsx') return <React.Fragment key={i}>{token.content}</React.Fragment>;
            return <span key={i} className={`token ${token.type}`}>{token.content}</span>;
          })}
        </div>
      </div>
    );
  });
};

export default function DiffModal({
  projectId,
  changeId,
  files,
  token,
  onApply,
  onCancel,
  onClose,
}) {
  console.log('DiffModal rendered with:', { projectId, changeId, files });
  
  const [beforeUrl, setBeforeUrl] = useState(null);
  const [afterUrl, setAfterUrl] = useState(null);
  const [loadingBefore, setLoadingBefore] = useState(true);
  const [loadingAfter, setLoadingAfter] = useState(true);
  const [beforeError, setBeforeError] = useState(null);
  const [afterError, setAfterError] = useState(null);
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);
  const [viewMode, setViewMode] = useState('code'); // 'code' or 'preview'

  // Fetch the two preview URLs on mount
  useEffect(() => {
    const BACKEND = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000';
    const headers = { Authorization: `Bearer ${token}` };
    console.log('[DiffModal] Loading previews for change:', changeId);
    
    // Before preview
    setLoadingBefore(true);
    setBeforeError(null);
    axios
      .post(
        `${BACKEND}/api/projects/${projectId}/preview/run/`,
        { mode: 'before' },
        { headers }
      )
      .then(res => {
        console.log('[DiffModal] Before preview URL:', res.data.url);
        setBeforeUrl(res.data.url);
        setLoadingBefore(false);
      })
      .catch(err => {
        console.error('[DiffModal] Error loading before preview:', err);
        setBeforeError(`Error loading before preview: ${err.message}`);
        setLoadingBefore(false);
      });

    // After preview  
    setLoadingAfter(true);
    setAfterError(null);
    axios
      .post(
        `${BACKEND}/api/projects/${projectId}/preview/run/`,
        { mode: 'after', change_id: changeId },
        { headers }
      )
      .then(res => {
        console.log('[DiffModal] After preview URL:', res.data.url);
        setAfterUrl(res.data.url);
        setLoadingAfter(false);
      })
      .catch(err => {
        console.error('[DiffModal] Error loading after preview:', err);
        setAfterError(`Error loading after preview: ${err.message}`);
        setLoadingAfter(false);
      });
  }, [projectId, changeId, token]);

  const renderFileList = () => {
    if (!files || files.length === 0) return null;
    
    return (
      <div className="file-list-section">
        <h4>Modified Files</h4>
        <div className="file-list">
          {files.map((file, index) => (
            <div 
              key={file.filePath} 
              className={`file-item ${index === selectedFileIndex ? 'selected' : ''}`}
              onClick={() => setSelectedFileIndex(index)}
            >
              {file.filePath}
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderFileDiff = () => {
    if (!files || files.length === 0 || !files[selectedFileIndex]) return null;
    
    const file = files[selectedFileIndex];
    return (
      <div className="file-diff-section">
        <h4>Changes in {file.filePath}</h4>
        <div className="diff-container">
          <div className="diff-pane before">
            <h5>Before</h5>
            <div className="diff-content">
              {highlightCode(file.before || '# Empty file')}
            </div>
          </div>
          <div className="diff-pane after">
            <h5>After</h5>
            <div className="diff-content">
              {highlightCode(file.after || '# Empty file')}
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderPreview = () => {
    return (
      <div className="preview-section">
        <h4>Live Preview</h4>
        <div className="preview-comparison">
          <div className="preview-pane">
            <h5>Before</h5>
            {beforeError ? (
              <div className="preview-error">{beforeError}</div>
            ) : loadingBefore ? (
              <div className="preview-loading">Loading before preview...</div>
            ) : beforeUrl ? (
              <iframe
                src={beforeUrl}
                className="preview-iframe"
                title="Before Preview"
                onError={() => setBeforeError('Error loading before preview')}
              />
            ) : (
              <div className="preview-error">Failed to load before preview</div>
            )}
          </div>

          <div className="preview-pane">
            <h5>After</h5>
            {afterError ? (
              <div className="preview-error">{afterError}</div>
            ) : loadingAfter ? (
              <div className="preview-loading">Loading after preview...</div>
            ) : afterUrl ? (
              <iframe
                src={afterUrl}
                className="preview-iframe"
                title="After Preview"
                onError={() => setAfterError('Error loading after preview')}
              />
            ) : (
              <div className="preview-error">Failed to load after preview</div>
            )}
          </div>
        </div>
      </div>
    );
  };

  const toggleViewMode = () => {
    setViewMode(viewMode === 'code' ? 'preview' : 'code');
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="diff-modal modal-content xlarge-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Preview Changes</h3>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>

        <div className="view-mode-toggle">
          <button 
            className={`toggle-btn ${viewMode === 'code' ? 'active' : ''}`} 
            onClick={() => setViewMode('code')}
          >
            Code Changes
          </button>
          <button 
            className={`toggle-btn ${viewMode === 'preview' ? 'active' : ''}`} 
            onClick={() => setViewMode('preview')}
          >
            Live Preview
          </button>
        </div>

        <div className="diff-layout">
          {renderFileList()}
          
          <div className="content-area">
            {viewMode === 'code' ? renderFileDiff() : renderPreview()}
          </div>
        </div>

        <div className="modal-footer">
          <button className="primary-btn" onClick={onApply}>Apply Changes</button>
          <button className="secondary-btn" onClick={onCancel}>Discard Changes</button>
        </div>
      </div>
    </div>
  );
}
    