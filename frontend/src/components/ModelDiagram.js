// src/components/ModelDiagram.jsx

import dagre from 'dagre';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import ReactFlow, {
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
} from 'reactflow';
import 'reactflow/dist/style.css';
import CustomCardinalityEdge from './CustomCardinalityEdge';
import CustomModelNode from './CustomModelNode';
import OverwriteModal from './OverwriteModal';
import SaveModelPopup from './SaveModelPopup';
import "./css/ModelDiagram.css";

// Helper to compute layout
const dagreGraph = new dagre.graphlib.Graph();
dagreGraph.setDefaultEdgeLabel(() => ({}));
const NODE_WIDTH = 180;
const NODE_HEIGHT = 80;

export const getLayoutedElements = (nodes, edges, direction = 'TB') => {
  dagreGraph.setGraph({ rankdir: direction, nodesep: 30, ranksep: 70, marginx: 20, marginy: 20 });
  nodes.forEach(n => dagreGraph.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach(e => dagreGraph.setEdge(e.source, e.target));
  dagre.layout(dagreGraph);

  const layoutedNodes = nodes.map(n => {
    const { x, y } = dagreGraph.node(n.id);
    return {
      ...n,
      position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 },
      sourcePosition: 'bottom',
      targetPosition: 'top',
    };
  });
  return { nodes: layoutedNodes, edges };
};

// Cardinality helpers
export const getCardinalities = relType => {
  if (relType === 'ForeignKey' || relType === 'ManyToOne') return { source: 'N', target: '1' };
  if (relType === 'OneToOneField') return { source: '1', target: '1' };
  if (relType === 'ManyToManyField') return { source: 'N', target: 'N' };
  return { source: '', target: '' };
};

const determineRelationType = (s, t) => {
  if (s === '1' && t === '1') return 'OneToOneField';
  if (s === 'N' && t === 'N') return 'ManyToManyField';
  if (s || t) return 'ForeignKey';
  return '';
};

const nodeTypes = { customModel: CustomModelNode };
const edgeTypes = { customEdge: CustomCardinalityEdge };

const ModelDiagram = ({ initialNodes = [], initialEdges = [] }) => {
  const navigate = useNavigate();
  const { fileId } = useParams();
  const [projectId] = useState(localStorage.getItem('project_id'));
  const [pendingAppId, setPendingAppId] = useState(null);
  const [existingModelFileId, setExistingModelFileId] = useState(null);
  const [existingModelFileContent, setExistingModelFileContent] = useState('');

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [codeOutput, setCodeOutput] = useState('');
  const [cardinalityEditor, setCardinalityEditor] = useState(null);
  const [showSavePopup, setShowSavePopup] = useState(false);
  const [showOverwriteModal, setShowOverwriteModal] = useState(false);
  const token = localStorage.getItem('access_token');

  // Load existing file (edit mode)
  useEffect(() => {
    if (!fileId) return;
    (async () => {
      try {
        const res = await fetch(`/api/model-file/?fileId=${fileId}`, {
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error('Load failed');
        const data = await res.json();
        setNodes(data.diagram?.nodes || []);
        setEdges(data.diagram?.edges || []);
        if (data.content) setCodeOutput(data.content);
      } catch (err) {
        console.error(err);
      }
    })();
  }, [fileId, token]);

  // Parse raw code into diagram
  useEffect(() => {
    if (!codeOutput || nodes.length || edges.length) return;
    (async () => {
      try {
        const res = await fetch('/api/parse-model/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ code: codeOutput }),
        });
        if (!res.ok) throw new Error('Parse failed');
        const { elements } = await res.json();
        setNodes(elements.filter(el => !el.source));
        setEdges(elements.filter(el => el.source));
      } catch (err) {
        console.error(err);
      }
    })();
  }, [codeOutput, nodes, edges, token]);

  // Attach controls to edges
  const removeEdge = useCallback(id => setEdges(es => es.filter(e => e.id !== id)), [setEdges]);
  const openCardinalityEditor = useCallback(
    (id, data) => {
      const src = nodes.find(n => n.id === data.source);
      const tgt = nodes.find(n => n.id === data.target);
      setCardinalityEditor({
        edgeId: id,
        sourceLabel: src?.data.model_name || 'Source',
        targetLabel: tgt?.data.model_name || 'Target',
        sourceCardinality: data.sourceCardinality || '',
        targetCardinality: data.targetCardinality || '',
      });
    },
    [nodes]
  );
  useEffect(() => {
    setEdges(es =>
      es.map(e => ({
        ...e,
        data: {
          ...e.data,
          onRemoveEdge: removeEdge,
          onOpenCardinalityEditor: openCardinalityEditor,
        },
      }))
    );
  }, [removeEdge, openCardinalityEditor]);

  const updateEdgeCardinality = useCallback((id, s, t) => {
    const rt = determineRelationType(s, t);
    setEdges(es =>
      es.map(e =>
        e.id === id
          ? { ...e, data: { ...e.data, sourceCardinality: s, targetCardinality: t, relation_type: rt } }
          : e
      )
    );
  }, []);

  const onConnect = useCallback(
    conn => {
      if (
        edges.some(
          e =>
            (e.source === conn.source && e.target === conn.target) ||
            (e.source === conn.target && e.target === conn.source)
        )
      )
        return;
      setEdges(es =>
        addEdge(
          {
            ...conn,
            id: `e${conn.source}-${conn.target}-${Date.now()}`,
            type: 'customEdge',
            data: {
              relation_type: '',
              source: conn.source,
              target: conn.target,
              sourceCardinality: '',
              targetCardinality: '',
              onRemoveEdge: removeEdge,
              onOpenCardinalityEditor: openCardinalityEditor,
            },
          },
          es
        )
      );
    },
    [edges, removeEdge, openCardinalityEditor]
  );

  const renderedNodes = useMemo(() => nodes.filter(n => !n.data?.isBuiltIn), [nodes]);
  const renderedEdges = useMemo(
    () =>
      edges.filter(e => {
        const s = nodes.find(n => n.id === e.source);
        const t = nodes.find(n => n.id === e.target);
        return s && t && !s.data?.isBuiltIn && !t.data?.isBuiltIn;
      }),
    [edges, nodes]
  );

  // Auto‐layout on changes
  useEffect(() => {
    if (!nodes.length && !edges.length) return;
    const { nodes: ln, edges: le } = getLayoutedElements([...nodes], [...edges]);
    setNodes(ln);
    setEdges(le);
  }, [nodes.length, edges.length]);

  // Generate Django model code
  const updateModelCode = async () => {
    try {
      const res = await fetch('/api/generate-model-code/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ elements: [...nodes, ...edges] }),
      });
      const { code } = await res.json();
      if (code) setCodeOutput(code);
    } catch (err) {
      console.error(err);
    }
  };

  // AI summary per model
  const generateAiSummaryForModel = async (modelName, fields, relationships) => {
    const res = await fetch('/api/generate-model-summary/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ model_name: modelName, fields, relationships }),
    });
    const { summary } = await res.json();
    return summary || 'No summary available';
  };

  // Save or update model file
  const saveModel = async (appId, updateId = null) => {
    // collect summaries
    const summaryPromises = renderedNodes.map(async node => {
      const modelName = node.data.model_name;
      const fields = node.data.fields || [];
      const relationships = renderedEdges
        .filter(e => e.source === node.id || e.target === node.id)
        .map(e => ({
          type: e.data.relation_type,
          target: e.source === node.id ? e.target : e.source,
        }));
      const summary = await generateAiSummaryForModel(modelName, fields, relationships);
      return { modelName, summary };
    });
    const resolved = await Promise.all(summaryPromises);

    const modelSummariesObj = {};
    resolved.forEach(({ modelName, summary }) => {
      modelSummariesObj[modelName] = summary;
    });
    const combinedSummary = resolved.map(({ modelName, summary }) => `${modelName}: ${summary}`).join('\n');

    const url = updateId ? `/api/save-model-file/${updateId}/` : `/api/save-model-file/`;
    const payload = {
      app: appId,
      content: codeOutput,
      description: 'models.py',
      diagram: { nodes: renderedNodes, edges: renderedEdges },
      summary: combinedSummary,
      model_summaries: modelSummariesObj,
    };

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.ok) {
        navigate(`/projects/${projectId}/apps/${appId}/model-files/${data.id}`);
      } else {
        console.error('Save failed:', data);
        alert('Error saving model file.');
      }
    } catch (err) {
      console.error(err);
      alert('Error saving model file.');
    }
  };

  // Handle initial save click
  const handlePopupSave = async (selectedProject, selectedApp) => {
    setShowSavePopup(false);
    localStorage.setItem('project_id', selectedProject.id);
    localStorage.setItem('app_id', selectedApp.id);
    const appId = Number(selectedApp.id);
    setPendingAppId(appId);

    if (!codeOutput.trim()) {
      alert('Generate code before saving.');
      return;
    }

    // Check existing
    try {
      const res = await fetch(`/api/model-file/?app_id=${appId}`, {
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const existing = await res.json();
        if (existing?.id) {
          setExistingModelFileId(existing.id);
          setExistingModelFileContent(existing.content);
          setShowOverwriteModal(true);
          return;
        }
      }
    } catch (err) {
      console.error(err);
    }

    // No existing → create
    await saveModel(appId);
  };

  // Handle overwrite confirmation
  const handleOverwrite = async () => {
    setShowOverwriteModal(false);
    if (!pendingAppId || !existingModelFileId) {
      console.error('Cannot overwrite: missing IDs.');
      return;
    }
    await saveModel(pendingAppId, existingModelFileId);
  };

  const handleCancelOverwrite = () => {
    setShowOverwriteModal(false);
    alert('Overwrite canceled.');
  };

  return (
    <div className="model-diagram-container">
      <div className="react-flow-container">
        <ReactFlowProvider>
          <ReactFlow
            nodes={renderedNodes}
            edges={renderedEdges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
          />
        </ReactFlowProvider>
      </div>

      <div className="action-buttons">
        <button className="primary-btn" onClick={updateModelCode}>
          Generate Code
        </button>
        <button className="secondary-btn" onClick={() => setShowSavePopup(true)}>
          Save Model File
        </button>
      </div>

      {codeOutput && (
        <div className="code-preview">
          <h3>Generated Code (Preview)</h3>
          <pre>{codeOutput}</pre>
        </div>
      )}

      {cardinalityEditor && (
        <>
          <div className="modal-overlay" onClick={() => setCardinalityEditor(null)} />
          <div className="modal-container">
            <h3>Edit Cardinality</h3>
            <div className="modal-content">
              <div>
                <strong>{cardinalityEditor.sourceLabel}</strong> (Source):
                <select
                  value={cardinalityEditor.sourceCardinality}
                  onChange={e =>
                    setCardinalityEditor(prev => ({ ...prev, sourceCardinality: e.target.value }))
                  }
                >
                  <option value="">Select</option>
                  <option value="1">1</option>
                  <option value="N">N</option>
                </select>
              </div>
              <div style={{ marginTop: '0.5rem' }}>
                <strong>{cardinalityEditor.targetLabel}</strong> (Target):
                <select
                  value={cardinalityEditor.targetCardinality}
                  onChange={e =>
                    setCardinalityEditor(prev => ({ ...prev, targetCardinality: e.target.value }))
                  }
                >
                  <option value="">Select</option>
                  <option value="1">1</option>
                  <option value="N">N</option>
                </select>
              </div>
              <div className="modal-actions">
                <button
                  className="primary-btn"
                  onClick={() => {
                    updateEdgeCardinality(
                      cardinalityEditor.edgeId,
                      cardinalityEditor.sourceCardinality,
                      cardinalityEditor.targetCardinality
                    );
                    setCardinalityEditor(null);
                  }}
                >
                  Save
                </button>
                <button className="secondary-btn" onClick={() => setCardinalityEditor(null)}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {showSavePopup && <SaveModelPopup onClose={() => setShowSavePopup(false)} onSave={handlePopupSave} />}

      {showOverwriteModal && (
        <OverwriteModal
          existingContent={existingModelFileContent}
          onOverwrite={handleOverwrite}
          onCancel={handleCancelOverwrite}
          showDetails={!fileId}
        />
      )}
    </div>
  );
};

export default ModelDiagram;
