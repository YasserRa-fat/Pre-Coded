import React from 'react';
import { Handle, Position } from 'reactflow';
import "./css/CustomModelNode.css";

const CustomModelNode = ({ data, id }) => {
  return (
    <div className="custom-model-node">
      {/* Top handles */}
      <Handle
        id="top-target"
        type="target"
        position={Position.Top}
        className="handle-style"
        style={{ left: '30%' }}
      />
      <Handle
        id="top-source"
        type="source"
        position={Position.Top}
        className="handle-style"
        style={{ left: '70%' }}
      />

      {/* Right handles */}
      <Handle
        id="right-target"
        type="target"
        position={Position.Right}
        className="handle-style"
        style={{ top: '30%' }}
      />
      <Handle
        id="right-source"
        type="source"
        position={Position.Right}
        className="handle-style"
        style={{ top: '70%' }}
      />

      {/* Bottom handles */}
      <Handle
        id="bottom-target"
        type="target"
        position={Position.Bottom}
        className="handle-style"
        style={{ left: '30%' }}
      />
      <Handle
        id="bottom-source"
        type="source"
        position={Position.Bottom}
        className="handle-style"
        style={{ left: '70%' }}
      />

      {/* Left handles */}
      <Handle
        id="left-target"
        type="target"
        position={Position.Left}
        className="handle-style"
        style={{ top: '30%' }}
      />
      <Handle
        id="left-source"
        type="source"
        position={Position.Left}
        className="handle-style"
        style={{ top: '70%' }}
      />

      {/* Model Name */}
      <h3>{data.model_name || 'Unnamed Model'}</h3>

      {/* AI Description or fallback Model Summary */}
      {data.ai_description && data.ai_description.trim() !== '' ? (
        <p style={{ fontStyle: 'italic' }}>
          {data.ai_description}
        </p>
      ) : (
        <p style={{ fontSize: '0.8rem', fontStyle: 'italic', marginTop: '0.5rem' }}>
          <strong></strong> {data.model_summary && data.model_summary.trim() !== ''
            ? data.model_summary
            : 'No summary available.'}
        </p>
      )}
    </div>
  );
};

export default CustomModelNode;
