import { useState } from 'react';

export function useFolderUpload() {
  const [files, setFiles] = useState([]);

  const handleFolderUpload = (event) => {
    const selectedFiles = Array.from(event.target.files);
    setFiles(selectedFiles);
  };

  return {
    files,
    handleFolderUpload,
  };
}
