import Editor from '@monaco-editor/react';
import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import './css/ModelDetail.css';
import fieldTypes from './fieldTypes'; // Import fieldTypes

const ModelDetail = () => {
    const { id } = useParams();
    const [modelDetail, setModelDetail] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [code, setCode] = useState('');
    const [isEditing, setIsEditing] = useState(false);
    const [syntaxErrors, setSyntaxErrors] = useState([]);

    useEffect(() => {
        const savedCode = localStorage.getItem(`code_${id}`);
        if (savedCode) {
            setCode(savedCode);
        }

        const fetchModelDetail = async () => {
            const token = localStorage.getItem('access_token');
            try {
                const response = await fetch(`http://localhost:8000/usermodels/${id}/`, {
                    method: 'GET',
                    headers: { Authorization: `Bearer ${token}` },
                });

                if (!response.ok) throw new Error('Failed to fetch model details.');

                const data = await response.json();
                console.log("Fetched model details:", data);

                setModelDetail(data);
                // Set code directly from full_code
                setCode(data.full_code || ''); // Ensure code is set from full_code
                validateParameters(data.full_code); // Validate parameters in the code

            } catch (err) {
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };

        fetchModelDetail();
    }, [id]);

    const validateParameters = (code) => {
        const errors = [];
        const lines = code.split('\n');
    
        lines.forEach((line) => {
            // Skip lines that contain class declarations
            if (line.trim().startsWith('class ')) {
                return; // Skip the class declaration
            }
    
            // Updated regex to match field definitions with or without models prefix
            const match = line.match(/(\w+)\s*=\s*(models\.\w+|FieldType)(\(([^)]*)\))/); // Match both styles
            if (match) {
                const fieldName = match[1];
                const fieldType = match[2]; // This will capture either models.FieldType or just FieldType
                const paramsString = match[4]; // Captured parameters string
                const params = paramsString ? paramsString.split(',').map(param => param.trim()) : []; // Extract parameters
    
                const fieldTypeConfig = fieldTypes.find(type => type.value === fieldType.replace(/^models\./, '')); // Strip models. if present
                if (fieldTypeConfig) {
                    fieldTypeConfig.parameters.forEach(param => {
                        const paramValue = params.find(p => p.startsWith(param.name));
                        const paramName = paramValue ? paramValue.split('=')[0] : undefined;
                        const paramVal = paramValue ? paramValue.split('=')[1] : undefined;
    
                        if (param.required && !paramName) {
                            errors.push(`Error: Parameter "${param.name}" is required for field type "${fieldType}".`);
                        }
    
                        // Check types of specific parameters
                        if (param.name === 'max_length' && paramVal) {
                            if (isNaN(paramVal)) {
                                errors.push(`Error: Parameter "max_length" must be a number for field type "${fieldType}".`);
                            }
                        }
    
                        if (param.name === 'min_value' && paramVal) {
                            if (isNaN(paramVal)) {
                                errors.push(`Error: Parameter "min_value" must be a number for field type "${fieldType}".`);
                            }
                        }
                    });
                } else {
                    errors.push(`Error: Field type "${fieldType}" is not recognized.`);
                }
            }
        });
    
        setSyntaxErrors(errors);
    };
    
    const handleEditorChange = (value) => {
        setCode(value);
        localStorage.setItem(`code_${id}`, value);
        validateParameters(value); // Validate parameters whenever code changes
    };

    const handleSaveChanges = async () => {
        const updatedData = {
            ...modelDetail,
            full_code: code, // Update the full code
        };

        try {
            const token = localStorage.getItem('access_token');
            console.log("Updated data to send:", JSON.stringify(updatedData, null, 2));

            const response = await fetch(`http://localhost:8000/usermodels/${id}/`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify(updatedData),
            });

            if (!response.ok) {
                const errorResponse = await response.json();
                console.error("Error response:", errorResponse);
                throw new Error(`Failed to save model details: ${response.status} ${response.statusText}`);
            }

            const responseData = await response.json();
            console.log("Successfully updated:", responseData);
            // Update the modelDetail state to reflect the changes
            setModelDetail(responseData);
        } catch (err) {
            console.error("Error while saving changes:", err);
            setError(err.message);
        }
    };

    if (loading) return <p>Loading...</p>;
    if (error) return <p>Error: {error}</p>;

    return (
        <div className="model-detail-container">
            <h1 style={{ color: '#f0f0f0' }}>Model: {modelDetail.model_name}</h1>
            <div className="code-snippet" style={{ height: '400px' }}>
                {isEditing ? (
                    <>
                        <Editor
                            height="300px"
                            language="python"
                            value={code}
                            options={{
                                selectOnLineNumbers: true,
                                automaticLayout: true,
                                theme: 'vs-dark',
                            }}
                            onChange={handleEditorChange}
                        />
                        <button onClick={handleSaveChanges} style={{ marginTop: '10px' }}>
                            Save Changes
                        </button>
                        {syntaxErrors.length > 0 && (
                            <div style={{ color: 'red', marginTop: '10px' }}>
                                <h3>Syntax Errors:</h3>
                                <ul>
                                    {syntaxErrors.map((error, index) => (
                                        <li key={index}>{error}</li>
                                    ))}
                                </ul>
                            </div>
                        )}
                    </>
                ) : (
                    <div onClick={() => setIsEditing(true)} style={{ cursor: 'pointer' }}>
                        <pre style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word' }}>
                            {code}
                        </pre>
                    </div>
                )}
            </div>

            <h2 style={{ color: '#f0f0f0', marginTop: '20px' }}>Model Details in JSON:</h2>
            <pre style={{ backgroundColor: '#222', color: '#f0f0f0', padding: '10px', borderRadius: '5px' }}>
                {JSON.stringify(modelDetail, null, 2)}
            </pre>
        </div>
    );
};

export default ModelDetail;
