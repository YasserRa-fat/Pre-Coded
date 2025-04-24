import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './css/ViewFilePaste.css'; // Import the new CSS file

const ViewFilePaste = () => {
  const [viewCode, setViewCode] = useState('');
  const navigate = useNavigate();

  const handleParse = () => {
    if (!viewCode.trim()) return alert("Please paste some view code.");
    localStorage.setItem('pastedViewCode', viewCode);
    navigate('/view-diagram', { state: { code: viewCode } });
  };

  return (
    <div className="view-paste-container">
      <h2 className="view-paste-title">Paste Your Django View Code</h2>
      <textarea
        className="code-input"
        rows="10"
        placeholder="Paste your Django view code here..."
        value={viewCode}
        onChange={(e) => setViewCode(e.target.value)}
      />
      <button className="primary-btn" onClick={handleParse}>
        Parse View Code
      </button>
    </div>
  );
};

export default ViewFilePaste;