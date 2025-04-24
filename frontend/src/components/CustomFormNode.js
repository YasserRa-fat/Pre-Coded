// CustomFormNode.jsx

import React from 'react';
import { Handle, Position } from 'reactflow';

const CustomFormNode = ({ data }) => {
  console.log("Rendering CustomFormNode with data:", data);
  console.log("Form reference:", data.form_reference, "Form summary:", data.form_summary);

  return (
    <div key={data.form_summary} style={{
      padding: '0.5rem',
      border: '1px solid #ddd',
      borderRadius: '4px',
      background: '#fff',
      width: '200px',
      fontFamily: 'Arial, sans-serif'
    }}>
      <h4 style={{ margin: '0 0 0.5rem 0', fontSize: '1rem', color: 'black' }}>
        {data.form_name || 'Unnamed Form'}
      </h4>

      {data.form_summary ? (
        <p style={{ fontSize: '0.8rem', color: '#555', margin: 0 }}>
          <em>{data.form_summary}</em>
        </p>
      ) : (
        <p style={{ fontSize: '0.75rem', color: '#999', margin: 0 }}>
          No summary available.
        </p>
      )}

      <Handle type="target" position={Position.Top} style={{ background: '#555' }} />
      <Handle type="source" position={Position.Bottom} style={{ background: '#555' }} />
    </div>
  );
};

export default CustomFormNode;
