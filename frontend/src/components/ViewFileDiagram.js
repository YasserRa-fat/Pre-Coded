import axios from 'axios';
import dagre from 'dagre';
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
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
import SaveViewPopup from './SaveViewPopup';

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

const getLayoutedElements = (nodes, edges, direction = 'TB') => {
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

  return {
    nodes: nodes.map((node) => {
      const { x, y } = dagreGraph.node(node.id);
      return {
        ...node,
        position: { x: x - nodeWidth / 2, y: y - nodeHeight / 2 },
        sourcePosition: 'bottom',
        targetPosition: 'top',
      };
    }),
    edges,
  };
};

const enrichNodesWithSummaries = (nodes, summaries) =>
  nodes.map((node) => {
    if (node.type === 'customView') {
      const modelRef = (node.data?.model_reference || '').trim();
      let modelSummary = '';
      if (modelRef && modelRef.toLowerCase() !== 'not specified') {
        const key = Object.keys(summaries).find(
          (k) => k.toLowerCase() === modelRef.toLowerCase()
        );
        if (key) modelSummary = summaries[key];
      }
      return {
        ...node,
        data: { ...node.data, model_summary: modelSummary },
      };
    } else if (node.type === 'customForm') {
      const ref = (node.data?.form_reference || node.data?.form_name || '').trim();
      let formSummary = '';
      if (ref && ref.toLowerCase() !== 'not specified') {
        const key = Object.keys(summaries).find(
          (k) => k.toLowerCase() === ref.toLowerCase()
        );
        if (key) formSummary = summaries[key];
      }
      return {
        ...node,
        data: {
          ...node.data,
          form_summary: formSummary,
          form_reference: ref,
        },
      };
    } else if (node.type === 'customModel') {
      const modelName = (node.data?.model_name || '').trim();
      let modelSummary = '';
      if (modelName && modelName.toLowerCase() !== 'not specified') {
        const key = Object.keys(summaries).find(
          (k) => k.toLowerCase() === modelName.toLowerCase()
        );
        if (key) modelSummary = summaries[key];
      }
      return {
        ...node,
        data: {
          ...node.data,
          model_summary: modelSummary,
          model_name: modelName,
        },
      };
    }
    return node;
  });

const ViewFileDiagram = () => {
  const navigate = useNavigate();
  const { fileId } = useParams();
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(false);
  const [codeOutput, setCodeOutput] = useState('');
  const [showPopup, setShowPopup] = useState(false);
  const [showOverwriteModal, setShowOverwriteModal] = useState(false);
  const [existingContent, setExistingContent] = useState('');
  const token = localStorage.getItem('access_token');

  // 🔧 FIXED: use ?app= instead of ?app_id=
  const fetchModelSummaries = async (appId) => {
    try {
      const res = await axios.get(`/api/model-files/?app_id=${appId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      console.log('Full API Response:', res.data);  // Log the entire response
          const files = res.data;
          if (Array.isArray(files) && files.length > 0) {
            // pick the latest or first one
            return files[0].model_summaries || {};
          }
          return {};  // Fallback to empty object if model_summaries is missing
    } catch (err) {
      console.error('Error fetching model summaries:', err);
      return {};  // Return empty object on error
    }
  };
  
  // 🔧 FIXED: use ?app= instead of ?app_id=
  const fetchFormSummaries = async (appId) => {
    try {
      const res = await axios.get(`/api/formfile/?app_id=${appId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
            const files = res.data;
            if (Array.isArray(files) && files.length > 0) {
              // take the first saved FormFile’s summaries
              return files[0].form_summaries || {};
            }
            return {};
    } catch (err) {
      console.error('Error fetching form summaries:', err);
      return {};
    }
  };

  const fetchSavedViewFile = useCallback(async () => {
    if (!fileId) return;

    setLoading(true);
    try {
      const { data } = await axios.get(`/api/viewfile/${fileId}/`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      setCodeOutput(data.content || '');

      if (
        data.diagram &&
        Array.isArray(data.diagram.nodes) &&
        Array.isArray(data.diagram.edges) &&
        data.diagram.nodes.length > 0 &&
        data.diagram.edges.length > 0
      ) {
        const [ms, fs] = await Promise.all([
          fetchModelSummaries(data.app),
          fetchFormSummaries(data.app),
        ]);

        const enriched = enrichNodesWithSummaries(
          data.diagram.nodes,
          { ...ms, ...fs }
        );
        const { nodes: ln, edges: le } = getLayoutedElements(
          enriched,
          data.diagram.edges
        );
        setNodes(ln);
        setEdges(le);
      } else {
        await fetchDiagram(data.content);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [fileId, token]);

  const fetchDiagram = useCallback(
    async (codeText) => {
      if (!codeText) return;

      setLoading(true);
      try {
        const appId = localStorage.getItem('app_id');
        console.log('Parsing code to generate diagram...');
        const { data } = await axios.post(
          '/api/parse-viewfile/',
          { code: codeText, app_id: appId },
          { headers: { Authorization: `Bearer ${token}` } }
        );

        setCodeOutput(codeText);
        const incomingNodes = data.elements.filter((el) => !el.source);
        const incomingEdges = data.elements.filter((el) => el.source);

        const [ms, fs] = await Promise.all([
          fetchModelSummaries(appId),
          fetchFormSummaries(appId),
        ]);

        const enriched = enrichNodesWithSummaries(incomingNodes, {
          ...ms,
          ...fs,
        });

        const { nodes: ln, edges: le } = getLayoutedElements(
          enriched,
          incomingEdges
        );
        setNodes(ln);
        setEdges(le);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    },
    [token]
  );

  useEffect(() => {
    if (fileId) {
      fetchSavedViewFile();
    } else {
      const savedCode = localStorage.getItem('pastedViewCode');
      if (savedCode) {
        fetchDiagram(savedCode);
      }
    }
  }, [fileId, fetchSavedViewFile, fetchDiagram]);

  const onConnect = useCallback((params) => {
    setEdges((eds) => addEdge(params, eds));
  }, []);

  const saveDiagram = () => setShowPopup(true);

  const handlePopupSave = async (project, app) => {
    setShowPopup(false);
    try {
      const res = await axios.post(
        '/api/save-viewfile/',
        {
          app_id: app.id,
          diagram: { nodes, edges },
          content: codeOutput,
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      navigate(
        `/projects/${project.id}/apps/${app.id}/view-files/${res.data.file_id}`
      );
    } catch (err) {
      if (err.response?.status === 409) {
        setExistingContent(err.response.data.existingContent);
        setShowOverwriteModal(true);
      } else {
        console.error(err);
        alert('Error saving diagram.');
      }
    }
  };

  const handleOverwrite = async () => {
    setShowOverwriteModal(false);
    try {
      const res = await axios.post(
        '/api/save-viewfile/',
        {
          app_id: localStorage.getItem('app_id'),
          diagram: { nodes, edges },
          content: codeOutput,
          overwrite: true,
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const projectId = localStorage.getItem('project_id');
      const appId = localStorage.getItem('app_id');
      navigate(
        `/projects/${projectId}/apps/${appId}/viewfiles/${res.data.file_id}`
      );
    } catch (err) {
      console.error(err);
      alert('Error overwriting diagram.');
    }
  };

  return (
    <div style={{ padding: '2rem' }}>
      <h2 style={{ textAlign: 'center' }}>View Diagram</h2>
      {loading && <p>Loading…</p>}

      <div style={{ height: '80vh', border: '1px solid #ddd' }}>
        <ReactFlowProvider>
          <ReactFlow
            key={JSON.stringify(nodes)}
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
      </div>

      <div style={{ textAlign: 'center', marginTop: '1rem' }}>
        <button
          onClick={saveDiagram}
          style={{ padding: '0.5rem 1rem' }}
        >
          Save Diagram
        </button>
      </div>

      {showPopup && (
        <SaveViewPopup
          onClose={() => setShowPopup(false)}
          onSave={handlePopupSave}
        />
      )}
      {showOverwriteModal && (
        <OverwriteModal
          existingContent={existingContent}
          onOverwrite={handleOverwrite}
          onCancel={() => setShowOverwriteModal(false)}
          showDetails
        />
      )}
    </div>
  );
};

export default ViewFileDiagram;
