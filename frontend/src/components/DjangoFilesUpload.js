// DjangoFilesUpload.jsx
import React, { useState } from 'react';
import DiagramCanvas from './DiagramCanvas';

const DjangoFilesUpload = () => {
  const [diagramData, setDiagramData] = useState({ nodes: [], edges: [] });
  const [error, setError] = useState(null);

  const handleFilesUpload = async (e) => {
    const files = e.target.files;
    const formData = new FormData();
    for (let file of files) {
      formData.append('files', file);
    }

    try {
      const res = await fetch('/api/upload-files', {
        method: 'POST',
        body: formData,
      });
      const result = await res.json();
      if (result.nodes && result.edges) {
        setDiagramData({ nodes: result.nodes, edges: result.edges });
        setError(null);
      } else {
        setError('Invalid response from server.');
      }
    } catch (err) {
      setError('Error uploading files.');
    }
  };

  return (
    <div>
      <h2>Upload Your Django Project Files</h2>
      <input type="file" accept=".py" multiple onChange={handleFilesUpload} />
      {error && <p style={{ color: 'red' }}>{error}</p>}
      <div style={{ height: '80vh', border: '1px solid #ccc', marginTop: '20px' }}>
        <DiagramCanvas initialData={diagramData} />
      </div>
    </div>
  );
};

export default DjangoFilesUpload;
