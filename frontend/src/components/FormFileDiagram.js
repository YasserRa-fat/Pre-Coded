import axios from 'axios';
import dagre from 'dagre';
import React, { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import ReactFlow, {
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
} from 'reactflow';
import 'reactflow/dist/style.css';
import CustomCardinalityEdge from './CustomCardinalityEdge';
import CustomFormNode from './CustomFormNode';
import CustomModelNode from './CustomModelNode';
import CustomViewNode from './CustomViewNode';
import OverwriteModal from './OverwriteModal';
import SaveFormPopup from './SaveFormPopup';
import './css/FormFileDiagram.css';

const nodeTypes = {
  customView: CustomViewNode,
  customModel: CustomModelNode,
  customForm: CustomFormNode,
};

const edgeTypes = { customEdge: CustomCardinalityEdge };

const dagreGraph = new dagre.graphlib.Graph();
dagreGraph.setDefaultEdgeLabel(() => ({}));
const nodeWidth = 180;
const nodeHeight = 80;

export const getLayoutedElements = (nodes, edges, direction = 'TB') => {
  dagreGraph.setGraph({
    rankdir: direction,
    nodesep: 30,
    ranksep: 70,
    marginx: 20,
    marginy: 20,
  });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  nodes.forEach((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    node.position = {
      x: nodeWithPosition.x - nodeWidth / 2,
      y: nodeWithPosition.y - nodeHeight / 2,
    };
    node.targetPosition = 'top';
    node.sourcePosition = 'bottom';
  });

  return { nodes, edges };
};

const enrichFormNodesWithModelSummaries = (nodeList, modelSummaries) => {
  return nodeList.map((node) => {
    if (node.type === 'customForm') {
      const modelUsed = node.data?.model_used?.trim() || '';
      if (modelUsed && modelUsed.toLowerCase() !== 'not specified') {
        const summary = modelSummaries[modelUsed] || 
          modelSummaries[Object.keys(modelSummaries).find(
            (key) => key.toLowerCase() === modelUsed.toLowerCase()
          )] || '';
        node.data.model_summary = summary;
      } else {
        node.data.model_summary = '';
      }
    }
    return node;
  });
};

const enrichModelNodesWithSummaries = (nodeList, modelSummaries) => {
  return nodeList.map((node) => {
    if (node.type === 'customModel') {
      const modelName = node.data?.model_name?.trim() || '';
      if (modelName && modelName.toLowerCase() !== 'not specified') {
        const summary = modelSummaries[modelName] || 
          modelSummaries[Object.keys(modelSummaries).find(
            (key) => key.toLowerCase() === modelName.toLowerCase()
          )] || node.data.model_summary || '';
        node.data.model_summary = summary;
      } else {
        node.data.model_summary = '';
      }
    }
    return node;
  });
};

const FormFileDiagram = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const code = location.state?.code || localStorage.getItem('pastedFormCode') || '';
  const fileId = location.state?.fileId;
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(false);
  const [codeOutput, setCodeOutput] = useState('');
  const [showSavePopup, setShowSavePopup] = useState(false);
  const [showOverwriteModal, setShowOverwriteModal] = useState(false);
  const [existingFormFile, setExistingFormFile] = useState('');
  const token = localStorage.getItem('access_token');

  useEffect(() => {
    console.log('All Nodes:', nodes);
    console.log('All Edges:', edges);
  }, [nodes, edges]);

  const fetchSavedFormFile = useCallback(async (id) => {
    setLoading(true);
    try {
      const res = await axios.get(`/api/formfile/?app_id=${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = res.data;
      if (data.length > 0) {
        const formFileData = data[0];
        if (formFileData.diagram) {
          setNodes(formFileData.diagram.nodes || []);
          setEdges(formFileData.diagram.edges || []);
        }
        setCodeOutput(formFileData.content || '');
      }
    } catch (err) {
      console.error('Error fetching saved form file:', err);
    } finally {
      setLoading(false);
    }
  }, [setNodes, setEdges, token]);
  
  const fetchDiagram = useCallback(async (codeText) => {
    if (!codeText) return;

    setLoading(true);
    try {
      const appId = localStorage.getItem('app_id');
      const res = await axios.post('/api/parse-formfile/', {
        code: codeText,
        app_id: appId,
      });

      const { elements } = res.data;
      let modelSummaries = {};

      try {
        const modelFileRes = await axios.get(`/api/model-file/?app_id=${appId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        modelSummaries = modelFileRes.data?.model_summaries || {};
      } catch (e) {
        console.warn('No model summaries found:', e);
      }

      const incomingNodes = elements.filter((el) => !el.source);
      const incomingEdges = elements.filter((el) => el.source);

      const cleanedEdges = incomingEdges.map((edge) => ({
        ...edge,
        data: { label: edge.data?.label || "" }
      }));

      let enrichedNodes = enrichFormNodesWithModelSummaries(incomingNodes, modelSummaries);
      enrichedNodes = enrichModelNodesWithSummaries(enrichedNodes, modelSummaries);

      const { nodes: layoutedNodes, edges: layoutedEdges } = 
        getLayoutedElements(enrichedNodes, cleanedEdges, 'TB');

      setNodes(layoutedNodes);
      setEdges(layoutedEdges);
    } catch (err) {
      console.error('Error fetching parsed form diagram:', err);
    } finally {
      setLoading(false);
    }
  }, [setNodes, setEdges, token]);

  useEffect(() => {
    if (fileId) {
      fetchSavedFormFile(fileId);
    } else if (code) {
      fetchDiagram(code);
    }
  }, [fileId, code, fetchDiagram, fetchSavedFormFile]);

  const onConnect = useCallback((params) => {
    setEdges((eds) => addEdge({ ...params, type: 'customEdge', data: {} }, eds));
  }, [setEdges]);

  const buildFormSummaries = (nodes) => {
    const summaries = {};
    nodes.forEach((node) => {
      if (node.type === 'customForm') {
        const formName = node.data?.form_name?.trim() || '';
        const formSummary = node.data?.form_summary?.trim() || 'No summary available.';
        if (formName) {
          summaries[formName] = formSummary;
        }
      }
    });
    return summaries;
  };

  const handleSaveFormFile = () => {
    if (fileId) {
      setShowOverwriteModal(true);
    } else {
      setShowSavePopup(true);
    }
  };

  // ✅ Moved functions ABOVE return statement
  const handleOverwrite = async () => {
    setShowOverwriteModal(false);
    const finalAppId = Number(localStorage.getItem('app_id'));
    await saveFormFile(finalAppId);
  };

  const handleCancelOverwrite = () => {
    setShowOverwriteModal(false);
    alert('Canceled overwriting. Please choose a different app or cancel the save operation.');
  };

  const handlePopupSave = async (selectedProject, selectedApp) => {
    setShowSavePopup(false);
    localStorage.setItem('project_id', selectedProject.id);
    localStorage.setItem('app_id', selectedApp.id);
    const finalAppId = Number(selectedApp.id);

    try {
      const res = await fetch(`/api/formfile/?app_id=${finalAppId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.ok) {
        const existingData = await res.json();
        if (existingData.length > 0 && existingData[0].content) {
          setExistingFormFile(existingData[0].content);
          setShowOverwriteModal(true);
          return;
        }
      }
    } catch (err) {
      console.error('Error checking existing form file:', err);
    }

    await saveFormFile(finalAppId);
  };
  const saveFormFile = async (finalAppId) => {
    const projectId = Number(localStorage.getItem('project_id')); // 👈 Get the project ID
  
    const formSummaries = buildFormSummaries(nodes);
  
    const payload = {
      app_id: finalAppId,
      project_id: projectId, // 👈 Add this line
      content: code,
      diagram: { nodes, edges },
      description: 'form.py',
      summary: 'Parsed form file...',
    };
  
    try {
      const res = await axios.post('/api/save-formfile/', payload, {
        headers: { Authorization: `Bearer ${token}` },
      });
  
      if (res.status === 201 || res.status === 200) {
        alert('Form file saved successfully.');
      } else {
        alert('Failed to save the form file.');
      }
    } catch (err) {
      console.error('Error saving form file:', err);
      alert('An error occurred while saving.');
    }
  };
  
  

  return (
    <div className="form-diagram-container" style={{ padding: '2rem' }}>
      <h2 style={{ textAlign: 'center' }}>Form Diagram</h2>
      {!code ? (
        <p>No form code provided. Please go back and paste your code.</p>
      ) : (
        <div style={{ height: '80vh', border: '1px solid #ddd' }}>
          {loading ? (
            <p style={{ textAlign: 'center', paddingTop: '2rem' }}>
              Loading form diagram...
            </p>
          ) : (
            <ReactFlowProvider>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                fitView
              />
            </ReactFlowProvider>
          )}
        </div>
      )}
      <div style={{ textAlign: 'center', marginTop: '1rem' }}>
        <button
          onClick={handleSaveFormFile}
          style={{
            padding: '0.5rem 1rem',
            borderRadius: '4px',
            border: 'none',
            backgroundColor: '#007BFF',
            color: 'white',
            cursor: 'pointer',
          }}
        >
          Save Form File
        </button>
      </div>
      {codeOutput && (
        <div style={{ margin: '1rem', textAlign: 'left' }}>
          <h3>Generated Code (Preview)</h3>
          <pre
            style={{
              background: '#f5f5f5',
              padding: '1rem',
              whiteSpace: 'pre-wrap',
              borderRadius: '4px',
              border: '1px solid #ccc',
              fontFamily: 'Consolas, Courier New, monospace',
              maxHeight: '400px',
              overflow: 'auto',
            }}
          >
            {codeOutput}
          </pre>
        </div>
      )}
      {showSavePopup && (
        <SaveFormPopup
          onClose={() => setShowSavePopup(false)}
          onSave={handlePopupSave}
        />
      )}
      {showOverwriteModal && (
        <OverwriteModal
          existingContent={existingFormFile}
          onOverwrite={handleOverwrite}
          onCancel={handleCancelOverwrite}
          showDetails={true}
        />
      )}
    </div>
  );
};

export default FormFileDiagram;