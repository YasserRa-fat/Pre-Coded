import React from 'react';
import { getBezierPath } from 'reactflow';
import "./css/CustomCardinalityEdge.css";

const foreignObjectSize = 40;

const CustomCardinalityEdge = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  data,
  markerEnd,
}) => {
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const handleRemove = (event) => {
    event.stopPropagation();
    if (data.onRemoveEdge) {
      data.onRemoveEdge(id);
    }
  };

  const handleEditCardinality = (event) => {
    event.stopPropagation();
    if (data.onOpenCardinalityEditor) {
      data.onOpenCardinalityEditor(id, data);
    }
  };

  return (
    <>
      <path id={id} style={style} className="react-flow__edge-path" d={edgePath} markerEnd={markerEnd} />
      <foreignObject
        width={foreignObjectSize}
        height={foreignObjectSize}
        x={(sourceX + targetX) / 2 - foreignObjectSize / 2}
        y={(sourceY + targetY) / 2 - foreignObjectSize / 2}
        requiredExtensions="http://www.w3.org/1999/xhtml"
      >
        <div className="edge-toolbar">
          <button onClick={handleRemove} className="edge-remove-btn" title="Disconnect">
            X
          </button>
          <button onClick={handleEditCardinality} className="edge-edit-btn" title="Edit Cardinality">
            {data.sourceCardinality}:{data.targetCardinality}
          </button>
        </div>
      </foreignObject>
    </>
  );
};

export default CustomCardinalityEdge;
