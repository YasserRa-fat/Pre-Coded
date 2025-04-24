import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import './css/FileListPage.css';

export default function MediaFilesPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();

  const [files, setFiles] = useState([]);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [selectedEntries, setSelectedEntries] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef();

  const ENDPOINT = `/api/projects/${projectId}/media-files/`;

  // Fetch files on mount and when projectId changes
  const fetchFiles = () => {
    fetch(ENDPOINT, {
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` }
    })
      .then(r => r.ok ? r.json() : Promise.reject('Failed to fetch media'))
      .then(setFiles)
      .catch(() => setError('Error loading media.'));
  };

  useEffect(() => {
    setError(''); setSuccess('');
    fetchFiles();
  }, [projectId]);

  // Flatten the file list and get the relative path
  const flattenFileList = fileList =>
    Array.from(fileList).map(file => ({
      file,
      relativePath: file.webkitRelativePath || file.name
    }));

  // Recursively traverse folders
  const traverseFileTree = (item, path = '') =>
    new Promise(resolve => {
      if (item.isFile) {
        item.file(f => resolve([{ file: f, relativePath: path + f.name }]));
      } else if (item.isDirectory) {
        const reader = item.createReader();
        reader.readEntries(async entries => {
          const nested = await Promise.all(
            entries.map(e => traverseFileTree(e, path + item.name + '/'))
          );
          resolve(nested.flat());
        });
      }
    });

  // Handle file or folder selection
  const handleFiles = filesList => {
    setSelectedEntries(flattenFileList(filesList));
    setError('');
  };

  // Handle drag over
  const handleDragOver = e => { e.preventDefault(); setDragActive(true); };
  const handleDragLeave = e => { e.preventDefault(); setDragActive(false); };

  // Handle file drop (drag & drop)
  const handleDrop = async e => {
    e.preventDefault(); setDragActive(false);
    const items = e.dataTransfer.items;
    if (!items) return;

    const all = [];
    for (let i = 0; i < items.length; i++) {
      const entry = items[i].webkitGetAsEntry();
      if (entry) {
        const result = await traverseFileTree(entry);
        all.push(...result);
      }
    }
    setSelectedEntries(all);
    setError('');
  };

  // Handle file upload
  const handleUpload = e => {
    e.preventDefault();
    if (selectedEntries.length === 0) {
      setError('Please choose at least one file or folder.');
      return;
    }

    const fd = new FormData();
    selectedEntries.forEach(({ file, relativePath }) => {
      fd.append('files', file);
      fd.append('paths', relativePath);
    });

    fetch(ENDPOINT, {
      method: 'POST',
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
      body: fd
    })
      .then(r => r.ok ? r.json() : Promise.reject('Upload failed'))
      .then(() => {
        setSuccess('Upload successful!');
        setSelectedEntries([]);
        fetchFiles();
      })
      .catch(() => setError('Upload failed.'));
  };

  // Handle delete file
  const handleDeleteClick = (e, fileId) => {
    e.stopPropagation(); // Prevents the card click from triggering navigation
  
    fetch(`/api/projects/${projectId}/media-files/${fileId}/`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
    })
      .then(response => {
        if (response.ok) {
          setSuccess('File deleted successfully');
          setFiles(files.filter(file => file.id !== fileId));
        } else {
          return response.text().then(text => {
            throw new Error(text || 'Failed to delete file');
          });
        }
      })
      .catch(err => setError(`Error deleting file: ${err.message}`));
  };

  return (
    <div className="file-list-page">
      <header>
        <h2>Media Files (Project {projectId})</h2>
      </header>

      <form onSubmit={handleUpload}>
        <div
          className={`drop-zone ${dragActive ? 'drag-active' : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current.click()}
        >
          {selectedEntries.length > 0
            ? `${selectedEntries.length} item(s) selected`
            : 'Drag & drop media here, or click to browse.'}
        </div>

        <input
          ref={fileInputRef}
          type="file"
          multiple
          webkitdirectory=""
          directory=""
          onChange={e => handleFiles(e.target.files)}
          style={{ display: 'none' }}
        />

        <button type="submit" className="upload-btn">Upload</button>
      </form>

      {error && <p className="error">{error}</p>}
      {success && <p className="success">{success}</p>}

      <div className="cards-container">
        {files.length === 0 ? (
          <p>No media files available.</p>
        ) : (
          files.map(f => (
            <div key={f.id} className="file-card">
              {f.file_type.startsWith('image/') && (
                <img src={f.file} alt={f.name} className="file-thumbnail" />
              )}
              <h4>{f.path}</h4>
              <button onClick={(e) => handleDeleteClick(e, f.id)} className="delete-btn">Delete</button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
