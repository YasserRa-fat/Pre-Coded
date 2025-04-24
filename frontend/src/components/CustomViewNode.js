import React from 'react';
import { Handle, Position } from 'reactflow';

const CustomViewNode = ({ data }) => {
  return (
    <div style={{
      padding: '0.5rem',
      border: '1px solid #ddd',
      borderRadius: '4px',
      background: '#fff',
      width: '200px',
      fontFamily: 'Arial, sans-serif'
    }}>
      <h4 style={{ margin: '0 0 0.5rem 0', fontSize: '1rem', color: 'black' }}>
        {data.view_name}
      </h4>
      {/* View AI Description */}
      <p style={{ fontSize: '0.8rem', color: '#555', margin: 0 }}>
        {data.ai_description || 'No description available.'}
      </p>
      
      <p style={{ fontSize: '0.75rem', color: '#999', margin: 0 }}>
        Type: {data.view_type || 'N/A'}
      </p>
  
     
      <Handle 
        type="target" 
        position={Position.Top} 
        style={{ background: '#555' }} 
      />
      <Handle 
        type="source" 
        position={Position.Bottom} 
        style={{ background: '#555' }} 
      />
    </div>
  );
};

export default CustomViewNode;
