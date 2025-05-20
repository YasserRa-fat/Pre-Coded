import React, { useCallback, useEffect, useRef, useState } from 'react';
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
  onClose = () => {},
  isModalOpen,
  previewUrls = {},
}) {
  console.log('DiffModal rendered with:', { projectId, changeId, files, previewUrls });
  
  const [beforeUrl, setBeforeUrl] = useState(null);
  const [afterUrl, setAfterUrl] = useState(null);
  const [loadingBefore, setLoadingBefore] = useState(false);
  const [loadingAfter, setLoadingAfter] = useState(false);
  const [beforeError, setBeforeError] = useState(null);
  const [afterError, setAfterError] = useState(null);
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);
  const [viewMode, setViewMode] = useState('code'); // 'code' or 'preview'
  const [isProcessing, setIsProcessing] = useState(false);
  const modalRef = useRef(null);

  // Handle click outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      // Prevent closing on any outside click
      // Only close via the explicit X button
      return;
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose]);

  // Handle escape key
  useEffect(() => {
    const handleEscape = (event) => {
      // Prevent closing on escape key
      // Only close via the explicit X button
      return;
    };

    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  const handleApply = useCallback(async () => {
    try {
      setIsProcessing(true);
      await onApply();
    } finally {
      setIsProcessing(false);
    }
  }, [onApply]);

  const handleCancel = useCallback(async () => {
    try {
      setIsProcessing(true);
      await onCancel();
    } finally {
      setIsProcessing(false);
    }
  }, [onCancel]);

  // Use provided preview URLs
  useEffect(() => {
    if (!projectId || !changeId) {
      console.debug('[DiffModal] Missing required params:', { projectId, changeId });
      return;
    }

    const BACKEND = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000';
    
    // Set URLs from previewMap
    if (previewUrls.before) {
      const beforeFullUrl = previewUrls.before.startsWith('http') 
        ? previewUrls.before 
        : `${BACKEND}${previewUrls.before}`;
      setBeforeUrl(beforeFullUrl);
      setLoadingBefore(false);
    }
    
    if (previewUrls.after) {
      const afterFullUrl = previewUrls.after.startsWith('http') 
        ? previewUrls.after 
        : `${BACKEND}${previewUrls.after}`;
      setAfterUrl(afterFullUrl);
      setLoadingAfter(false);
    }

    return () => {
      setBeforeUrl(null);
      setAfterUrl(null);
      setBeforeError(null);
      setAfterError(null);
      setLoadingBefore(false);
      setLoadingAfter(false);
    };
  }, [projectId, changeId, previewUrls]);

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
    const BACKEND = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000';
    
    return (
      <div className="preview-section">
        <h4>Live Preview</h4>
        <div className="preview-comparison">
          <div className="preview-pane">
            <h5>Before</h5>
            {beforeError ? (
              <div className="preview-error">
                <p>{beforeError}</p>
                <button 
                  className="retry-btn"
                  onClick={() => {
                    setBeforeError(null);
                    const beforeFullUrl = previewUrls.before.startsWith('http') 
                      ? previewUrls.before 
                      : `${BACKEND}${previewUrls.before}`;
                    setBeforeUrl(beforeFullUrl);
                  }}
                >
                  Retry
                </button>
              </div>
            ) : loadingBefore ? (
              <div className="preview-loading">
                <div className="loading-spinner"></div>
                <p>Loading before preview...</p>
              </div>
            ) : beforeUrl ? (
              <iframe
                src={beforeUrl}
                className="preview-iframe"
                title="Before Preview"
                onError={() => setBeforeError('Error loading before preview - the preview server might be unavailable')}
                sandbox="allow-same-origin allow-scripts allow-forms"
              />
            ) : (
              <div className="preview-error">
                <p>Failed to load before preview</p>
                <button 
                  className="retry-btn"
                  onClick={() => {
                    const beforeFullUrl = previewUrls.before.startsWith('http') 
                      ? previewUrls.before 
                      : `${BACKEND}${previewUrls.before}`;
                    setBeforeUrl(beforeFullUrl);
                  }}
                >
                  Retry
                </button>
              </div>
            )}
          </div>

          <div className="preview-pane">
            <h5>After</h5>
            {afterError ? (
              <div className="preview-error">
                <p>{afterError}</p>
                <button 
                  className="retry-btn"
                  onClick={() => {
                    setAfterError(null);
                    const afterFullUrl = previewUrls.after.startsWith('http') 
                      ? previewUrls.after 
                      : `${BACKEND}${previewUrls.after}`;
                    setAfterUrl(afterFullUrl);
                  }}
                >
                  Retry
                </button>
              </div>
            ) : loadingAfter ? (
              <div className="preview-loading">
                <div className="loading-spinner"></div>
                <p>Loading after preview...</p>
              </div>
            ) : afterUrl ? (
              <iframe
                src={afterUrl}
                className="preview-iframe"
                title="After Preview"
                onError={() => setAfterError('Error loading after preview - the preview server might be unavailable')}
                sandbox="allow-same-origin allow-scripts allow-forms"
              />
            ) : (
              <div className="preview-error">
                <p>Failed to load after preview</p>
                <button 
                  className="retry-btn"
                  onClick={() => {
                    const afterFullUrl = previewUrls.after.startsWith('http') 
                      ? previewUrls.after 
                      : `${BACKEND}${previewUrls.after}`;
                    setAfterUrl(afterFullUrl);
                  }}
                >
                  Retry
                </button>
              </div>
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
    <div className="modal-overlay">
      <div ref={modalRef} className="diff-modal modal-content xlarge-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Preview Changes</h3>
          <button 
            className="close-btn" 
            onClick={() => {
              if (onClose) onClose();
            }}
            disabled={isProcessing}
          >
            ×
          </button>
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
          <button 
            className="primary-btn" 
            onClick={handleApply}
            disabled={isProcessing}
          >
            {isProcessing ? 'Applying...' : 'Apply Changes'}
          </button>
          <button 
            className="secondary-btn" 
            onClick={handleCancel}
            disabled={isProcessing}
          >
            {isProcessing ? 'Canceling...' : 'Discard Changes'}
          </button>
        </div>

        {isProcessing && (
          <div className="processing-overlay">
            <div className="processing-spinner"></div>
            <p>Processing changes...</p>
          </div>
        )}
      </div>
    </div>
  );
}
    