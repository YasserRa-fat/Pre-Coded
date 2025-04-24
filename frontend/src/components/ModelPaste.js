import React, { useState } from 'react';
import ModelDiagram, { getCardinalities, getLayoutedElements } from './ModelDiagram';
import ProjectSelector from './ProjectSelector';
import "./css/ModelPaste.css";

const ModelPaste = () => {
  const [projectId, setProjectId] = useState(localStorage.getItem('project_id'));
  const [modelText, setModelText] = useState('');
  const [diagramReady, setDiagramReady] = useState(false);
  const [diagramData, setDiagramData] = useState({ nodes: [], edges: [] });

  const parseModel = async () => {
    try {
      const response = await fetch('/api/parse-model/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: modelText }),
      });
      const data = await response.json();
      if (data.elements) {
        // Separate nodes and edges.
        const parsedNodes = data.elements
          .filter((el) => !el.source)
          .map((node) => ({
            ...node,
            type: 'customModel',
          }));
        const parsedEdges = data.elements
          .filter((el) => el.source)
          .map((edge) => {
            const { source: sourceCardinality, target: targetCardinality } = getCardinalities(edge.data.relation_type);
            return {
              ...edge,
              type: 'customEdge',
              data: { ...edge.data, sourceCardinality, targetCardinality },
            };
          });
        
        const layouted = getLayoutedElements(parsedNodes, parsedEdges, 'TB');
        setDiagramData(layouted);
        setDiagramReady(true);
      } else {
        console.error('No elements returned from parse-model:', data);
      }
    } catch (error) {
      console.error('Error parsing model:', error);
    }
  };

  // If no project is selected, render the ProjectSelector
  if (!projectId) {
    return (
      <ProjectSelector
        onProjectSelect={(project) => {
          setProjectId(project.id);
          localStorage.setItem('project_id', project.id);
        }}
      />
    );
  }

  return (
    <div className="model-paste-container">
      {!diagramReady ? (
        <div className="model-paste-input">
          <h2 className="model-paste-heading">Paste Your Django Model Code</h2>
          <textarea
            className="model-paste-textarea"
            rows="10"
            value={modelText}
            onChange={(e) => setModelText(e.target.value)}
            placeholder="Paste your Django model code here..."
          />
          <button className="model-paste-button" onClick={parseModel}>Parse Model</button>
        </div>
      ) : (
        <div className="diagram-container">
          {/* ModelDiagram is responsible for rendering the full-screen diagram */}
          <ModelDiagram initialNodes={diagramData.nodes} initialEdges={diagramData.edges} />
        </div>
      )}
    </div>
  );
};

export default ModelPaste;
