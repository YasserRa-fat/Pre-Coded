import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import './css/FileListPage.css';

export default function StaticFilesPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();

  const [files, setFiles] = useState([]);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [selectedEntries, setSelectedEntries] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const [loading, setLoading] = useState(true);
  const fileInputRef = useRef();

  const ENDPOINT = `/api/projects/${projectId}/static-files/`;

  const fetchFiles = () => {
    setLoading(true);
    fetch(ENDPOINT, {
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` }
    })
      .then(r => r.ok ? r.json() : Promise.reject('Failed to fetch files'))
      .then(data => {
        setFiles(data);
        setLoading(false);
      })
      .catch(err => {
        setError(typeof err === 'string' ? err : 'Error loading files.');
        setLoading(false);
      });
  };

  useEffect(() => {
    setError(''); 
    setSuccess('');
    fetchFiles();
  }, [projectId]);

  const flattenFileList = fileList => 
    Array.from(fileList).map(file => ({
      file,
      relativePath: file.webkitRelativePath || file.name, // webkitRelativePath will contain the relative path
    }));
  
    const traverseFileTree = async (item, path = '') => {
      if (item.isFile) {
        const file = await new Promise(resolve => item.file(resolve));
        return [{ file, relativePath: path + file.name }];
      } else if (item.isDirectory) {
        const dirReader = item.createReader();
        let entries = [];
        let readEntries;
        do {
          readEntries = await new Promise(resolve => dirReader.readEntries(resolve));
          const subEntries = await Promise.all(
            readEntries.map(entry => traverseFileTree(entry, path + item.name + '/'))
          );
          entries = entries.concat(subEntries.flat());
        } while (readEntries.length > 0);
        return entries;
      }
      return [];
    };

  const handleFiles = filesList => {
    setSelectedEntries(flattenFileList(filesList));
    setError('');
  };

  const handleDragOver = e => { e.preventDefault(); setDragActive(true); };
  const handleDragLeave = e => { e.preventDefault(); setDragActive(false); };
  const handleDrop = async e => {
    e.preventDefault();
    setDragActive(false);
    const items = Array.from(e.dataTransfer.items); // Convert to array to avoid live collection issues
    if (!items.length) return;
  
    const all = [];
    for (const item of items) { // Iterate using for...of over the static array
      const entry = item.webkitGetAsEntry();
      if (entry) {
        try {
          const result = await traverseFileTree(entry);
          all.push(...result);
        } catch (err) {
          console.error('Error processing entry:', err);
        }
      }
    }
    setSelectedEntries(all);
    setError('');
  };
  const handleUpload = e => {
    e.preventDefault();
    if (selectedEntries.length === 0) {
      setError('Please choose at least one file or folder.');
      return;
    }
  
    const fd = new FormData();
    selectedEntries.forEach(({ file, relativePath }) => {
      fd.append('files', file); // Append the file with its original name
      fd.append('paths', relativePath); // Append the relative path
    });
    fd.append('project', projectId); // Add the project to the FormData explicitly

    (async () => {
      try {
        const response = await fetch(ENDPOINT, {
          method: 'POST',
          headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
          body: fd
        });
        const data = await response.json();
        if (!response.ok) {
          const msgs = data.errors.map(err =>
            `${err.file}: ` +
            Object.entries(err.errors)
              .map(([field, errs]) => `${field} ${errs.join('; ')}`)
              .join(', ')
          );
          setError(msgs.join('\n'));
          return;
        }
        setSuccess(`Uploaded ${data.created.length} file(s) successfully.`);
        setSelectedEntries([]);
        fetchFiles();
      } catch (err) {
        setError(`Upload failed: ${err.message}`);
      }
    })();
  };

  // Function to handle delete file
  const handleDeleteClick = (e, fileId) => {
    e.stopPropagation(); // Prevents the card click from triggering navigation
  
    fetch(`/api/projects/${projectId}/static-files/${fileId}/`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
    })
      .then(response => {
        if (response.ok) {
          // If the response is OK, assume successful deletion
          setSuccess('File deleted successfully');
          // Remove the deleted file from the state
          setFiles(files.filter(file => file.id !== fileId));
        } else {
          // If the response is not OK, throw an error
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
        <h2>Static Files (Project {projectId})</h2>
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
            ? selectedEntries.map(e => e.relativePath).join(', ')  // Show relative paths
            : 'Drag & drop files/folders here, or click to browse.'}
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

      {error && <pre className="error">{error}</pre>}
      {success && <p className="success">{success}</p>}

      {loading ? (
        <p className="loading">Loading files...</p>
      ) : (
        <div className="cards-container">
          {files.length === 0 ? (
            <p>No static files available.</p>
          ) : (
            files.map(f => (
              <div key={f.id} className="file-card">
              <h4>{f.path}</h4> {/* Use f.path instead of f.relativePath */}
              
              <button onClick={(e) => handleDeleteClick(e, f.id)} className="delete-btn">Delete</button>
            </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
