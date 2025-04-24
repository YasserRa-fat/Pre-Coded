import axios from 'axios';
import React, { useEffect, useState } from 'react';
import Select from 'react-select';
import './css/CreateUserModel.css';
import fieldTypes from './fieldTypes';

const CreateUserModel = () => {
  const [modelName, setModelName] = useState('');
  const [fields, setFields] = useState([{ name: '', type: '', parameters: {}, selectedParam: '' }]);
  const [visibility, setVisibility] = useState('private');
  const [userInfo, setUserInfo] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [generatedCode, setGeneratedCode] = useState('');

  useEffect(() => {
    const fetchUserInfo = async () => {
      const token = localStorage.getItem('access_token');
      try {
        const response = await axios.get('http://localhost:8000/api/current_user/', {
          headers: { Authorization: `Bearer ${token}` },
        });
        setUserInfo(response.data);
      } catch (err) {
        console.error("Error fetching user info:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchUserInfo();
  }, []);

  const handleAddField = () => {
    setFields([...fields, { name: '', type: '', parameters: {}, selectedParam: '' }]);
  };

  const handleFieldChange = (index, field, value) => {
    const updatedFields = [...fields];
    updatedFields[index][field] = value;
    // When field type changes, clear parameters and selectedParam.
    if (field === 'type') {
      updatedFields[index].parameters = {};
      updatedFields[index].selectedParam = '';
    }
    setFields(updatedFields);
  };

  const handleParameterChange = (index, param, value) => {
    const updatedFields = [...fields];
    if (value.trim() !== '') {
      updatedFields[index].parameters[param] = value;
    } else {
      delete updatedFields[index].parameters[param];
    }
    setFields(updatedFields);
  };

  const validateFields = () => {
    for (const field of fields) {
      if (!field.name || !field.type) {
        setError("All fields must have a name and a field type.");
        return false;
      }
      const fieldType = fieldTypes.find(ft => ft.value === field.type);
      if (fieldType) {
        for (const param of fieldType.parameters) {
          if (param.required && !field.parameters[param.name]) {
            setError(`Missing required parameter: ${param.name} for field ${field.name}`);
            return false;
          }
        }
      }
    }
    return true;
  };

  // Model name must start with a capital letter and be alphanumeric.
  const isValidModelName = (name) => {
    const modelNamePattern = /^[A-Z][a-zA-Z0-9]*$/;
    return modelNamePattern.test(name);
  };

  // Generate Django model code based on current data.
  const generateFullCode = () => {
    if (!modelName.trim()) return "Model name not specified.";
    const validFields = fields.filter(field => field.name && field.type);
    if (validFields.length === 0) return "No fields defined.";
    const codeLines = validFields.map(field => {
      const paramString = Object.entries(field.parameters)
        .map(([key, value]) => {
          const formattedValue =
            (key === 'max_length' || key === 'min_value') && !isNaN(value)
              ? Number(value)
              : `'${value}'`;
          return `${key}=${formattedValue}`;
        })
        .join(', ');
      return `    ${field.name} = models.${field.type}(${paramString})`;
    });
    return `from django.db import models\n\nclass ${modelName}(models.Model):\n${codeLines.join('\n')}`;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!isValidModelName(modelName)) {
      setError("Model name must start with a capital letter and follow Django's naming conventions.");
      return;
    }
    if (!validateFields()) return;

    // Generate the full Django model code based on the fields.
    const full_code = generateFullCode();
    setGeneratedCode(full_code);

    setSubmitting(true);
    const token = localStorage.getItem('access_token');

    try {
      // Updated payload: Only send the generated full_code instead of a separate fields JSON.
      await axios.post(
        'http://localhost:8000/usermodels/',
        {
          model_name: modelName,
          visibility,
          user: userInfo.username,
          email: userInfo.email,
          full_code: full_code,
        },
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );

      // Reset form values if desired.
      setModelName('');
      setFields([{ name: '', type: '', parameters: {}, selectedParam: '' }]);
      setVisibility('private');
      setSuccess(true);
      setError(null);
    } catch (err) {
      if (err.response) {
        const errorData = err.response.data;
        if (errorData.model_name) {
          setError(`Model Name Error: ${errorData.model_name[0]}`);
        } else if (errorData.non_field_errors) {
          setError(`Error: ${errorData.non_field_errors[0]}`);
        } else {
          setError("Error creating model. Please try again.");
        }
      } else {
        setError("Network or server error occurred.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const renderFields = () => {
    return fields.map((field, index) => (
      <tr key={index}>
        <td>
          <input
            type="text"
            placeholder="Field Name"
            value={field.name}
            onChange={(e) => handleFieldChange(index, 'name', e.target.value)}
            className="input-field"
          />
        </td>
        <td>
          <Select
            value={field.type ? { value: field.type, label: field.type } : null}
            options={fieldTypes}
            onChange={(selectedOption) => handleFieldChange(index, 'type', selectedOption.value)}
            placeholder="Select Field Type"
            className="select-field"
          />
        </td>
        <td>
          {field.type && (
            <>
              <Select
                value={field.selectedParam ? { value: field.selectedParam, label: field.selectedParam } : null}
                options={
                  (fieldTypes.find(ft => ft.value === field.type)?.parameters || []).map(param => ({
                    value: param.name,
                    label: (
                      <span>
                        {param.name}
                        {param.required && <span style={{ color: 'red' }}> (required)</span>}
                      </span>
                    ),
                  }))
                }
                onChange={(selectedOption) =>
                  handleFieldChange(index, 'selectedParam', selectedOption.value)
                }
                placeholder="Select Parameter"
                className="select-field"
              />
              {field.selectedParam && (
                <div className="parameter-input">
                  <span>{field.selectedParam}: </span>
                  <input
                    type="text"
                    placeholder={`Value for ${field.selectedParam}`}
                    value={field.parameters[field.selectedParam] || ''}
                    onChange={(e) => handleParameterChange(index, field.selectedParam, e.target.value)}
                    className="inline-input"
                  />
                </div>
              )}
            </>
          )}
        </td>
      </tr>
    ));
  };

  if (loading) return <p>Loading user information...</p>;

  return (
    <div className="create-user-model">
      <h2>Create User Model</h2>
      {error && <p className="error">{error}</p>}
      {success && <p className="success">Model created successfully!</p>}
      <form onSubmit={handleSubmit}>
        <div>
          <input
            type="text"
            placeholder="Model Name"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            className="input-field"
          />
        </div>
        <table>
          <thead>
            <tr>
              <th>Field Name</th>
              <th>Field Type</th>
              <th>Parameters</th>
            </tr>
          </thead>
          <tbody>{renderFields()}</tbody>
        </table>
        <button type="button" onClick={handleAddField} className="add-field-button">
          Add Field
        </button>
        <button type="submit" className="submit-button" disabled={submitting}>
          {submitting ? 'Creating...' : 'Create Model'}
        </button>
      </form>
      {/* Display generated code if available */}
      {generatedCode && (
        <div className="code-output">
          <h3>Generated Code:</h3>
          <pre>{generatedCode}</pre>
        </div>
      )}
    </div>
  );
};

export default CreateUserModel;
