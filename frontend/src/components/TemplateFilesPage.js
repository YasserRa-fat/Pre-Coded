import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import './css/FileListPage.css';

// Helper to recursively read dropped directories
const traverseFileTree = (item, path = '') => {
  return new Promise(resolve => {
    const entry = item.webkitGetAsEntry();
    if (!entry) return resolve([]);
    if (entry.isFile) {
      entry.file(file => {
        // attach relative path for upload
        file.relativePath = path + file.name;
        resolve([file]);
      });
    } else if (entry.isDirectory) {
      const dirReader = entry.createReader();
      dirReader.readEntries(entries => {
        Promise.all(
          entries.map(en => traverseFileTree({ webkitGetAsEntry: () => en }, path + entry.name + '/'))
        ).then(results => {
          resolve(results.flat());
        });
      });
    }
  });
};

export default function TemplateFilesPage({ isApp = false }) {
  const { projectId, appId } = useParams();
  const navigate = useNavigate();

  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // each item: { file: File, path: string }
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef();

  const getEndpoint = () => {
    if (isApp) {
      return `http://localhost:8000/api/apps/${appId}/template-files/`;
    }
    return `http://localhost:8000/api/projects/${projectId}/template-files/`;
  };

  useEffect(() => {
    fetch(getEndpoint(), {
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` }
    })
      .then(r => {
        if (!r.ok) throw new Error('Failed to fetch');
        return r.json();
      })
      .then(data => {
        setFiles(data);
        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setError('Error loading templates');
        setLoading(false);
      });
  }, [projectId, appId]);

  const handleFileInput = e => {
    const fileList = Array.from(e.target.files);
    const wrapped = fileList.map(f => ({ file: f, path: f.webkitRelativePath || f.name }));
    setSelectedFiles(wrapped);
  };

  const handleDragOver = e => {
    e.preventDefault();
    setDragActive(true);
  };

  const handleDragLeave = e => {
    e.preventDefault();
    setDragActive(false);
  };

  const handleDrop = async e => {
    e.preventDefault();
    setDragActive(false);
    const items = Array.from(e.dataTransfer.items);
    const allFiles = await Promise.all(
      items.map(item => traverseFileTree(item))
    );
    const flat = allFiles.flat().map(f => ({ file: f, path: f.relativePath }));
    if (flat.length) setSelectedFiles(flat);
  };

  const uploadFiles = async () => {
    if (!selectedFiles.length) return;

    const formData = new FormData();
    selectedFiles.forEach(({ file, path }) => {
      formData.append('files', file, file.name);
      formData.append('paths', path);
    });

    try {
      const res = await fetch(getEndpoint(), {
        method: 'POST',
        headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
        body: formData
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Upload failed');

      setFiles(prev => [...prev, ...data]);
      setSelectedFiles([]);
      fileInputRef.current.value = '';
      setError('');
    } catch (err) {
      console.error('Upload error:', err);
      setError(err.message);
    }
  };

  const deleteFile = fileId => {
    fetch(`${getEndpoint()}${fileId}/`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` }
    })
      .then(r => {
        if (!r.ok) throw new Error('Failed to delete');
        setFiles(prev => prev.filter(f => f.id !== fileId));
      })
      .catch(err => {
        console.error(err);
        setError('Error deleting file');
      });
  };

  const handleCardClick = fileId => {
    const prefix = isApp ? `/apps/${appId}` : `/projects/${projectId}`;
    navigate(`${prefix}/template-files/${fileId}`);
  };

  if (loading) return <p>Loading…</p>;

  return (
    <div className="file-list-page">
      <header>
        <h2>
          Template Files {isApp ? `(App ${appId})` : `(Project ${projectId})`}
        </h2>
      </header>

      <div
        className={`drop-zone ${dragActive ? 'drag-active' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current.click()}
      >
        {selectedFiles.length
          ? `${selectedFiles.length} file(s) ready to upload`
          : 'Drag & drop folders/files here, or click to select'}
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".html,.txt"
        multiple
        webkitdirectory
        directory
        style={{ display: 'none' }}
        onChange={handleFileInput}
      />

      <div className="template-form">
        <button
          onClick={uploadFiles}
          className="upload-btn"
          disabled={!selectedFiles.length}
        >
          Upload
        </button>
        {error && <p className="error">{error}</p>}
      </div>

      <div className="cards-container">
        {files.map(f => (
          <div key={f.id} className="file-card">
            <div onClick={() => handleCardClick(f.id)} className="file-info">
              <h4>{f.path}</h4>
              <p className="file-meta">
                Created at {new Date(f.created_at).toLocaleString()}
              </p>
            </div>
            <button
              className="delete-btn"
              onClick={() => deleteFile(f.id)}
            >
              Delete
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}