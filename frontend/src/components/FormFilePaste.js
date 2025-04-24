// src/components/FormFilePaste.js
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './css/FormFilePaste.css';

const FormFilePaste = () => {
  const [formCode, setFormCode] = useState('');
  const navigate = useNavigate();

  const handleParse = () => {
    if (!formCode.trim()) {
      alert("Please paste some form code.");
      return;
    }
    localStorage.setItem('pastedFormCode', formCode);
    navigate('/form-diagram', { state: { code: formCode } });
  };

  return (
    <div className="form-paste-container">
      <h2 className="form-paste-title">Paste Your Django Form Code</h2>
      <textarea
        className="code-input"
        rows="10"
        placeholder="Paste your Django form code here..."
        value={formCode}
        onChange={(e) => setFormCode(e.target.value)}
      />
      <button className="primary-btn" onClick={handleParse}>
        Parse Form Code
      </button>
    </div>
  );
};

export default FormFilePaste;
