import axios from 'axios';
import React, { useEffect, useState } from 'react';
import Select from 'react-select';
import './css/GenerateAPITable.css'; // Import your CSS styles

const GenerateApiTable = () => {
    const [modelsData, setModelsData] = useState({});
    const [selectedModels, setSelectedModels] = useState('builtIn');
    const [customModelName, setCustomModelName] = useState('Custom Model');
    const [customFields, setCustomFields] = useState([{ name: '', type: '' }]);
    const [loading, setLoading] = useState(true);
    const [fieldTypes] = useState([
        { value: 'AutoField', label: 'AutoField' },
        { value: 'BigAutoField', label: 'BigAutoField' },
        { value: 'BigIntegerField', label: 'BigIntegerField' },
        { value: 'BinaryField', label: 'BinaryField' },
        { value: 'BooleanField', label: 'BooleanField' },
        { value: 'CharField', label: 'CharField' },
        { value: 'DateField', label: 'DateField' },
        { value: 'DateTimeField', label: 'DateTimeField' },
        { value: 'DecimalField', label: 'DecimalField' },
        { value: 'EmailField', label: 'EmailField' },
        { value: 'FileField', label: 'FileField' },
        { value: 'FilePathField', label: 'FilePathField' },
        { value: 'FloatField', label: 'FloatField' },
        { value: 'ImageField', label: 'ImageField' },
        { value: 'IntegerField', label: 'IntegerField' },
        { value: 'IPAddressField', label: 'IPAddressField' },
        { value: 'GenericIPAddressField', label: 'GenericIPAddressField' },
        { value: 'JSONField', label: 'JSONField' },
        { value: 'ManyToManyField', label: 'ManyToManyField' },
        { value: 'OneToOneField', label: 'OneToOneField' },
        { value: 'PositiveBigIntegerField', label: 'PositiveBigIntegerField' },
        { value: 'PositiveIntegerField', label: 'PositiveIntegerField' },
        { value: 'SlugField', label: 'SlugField' },
        { value: 'TextField', label: 'TextField' },
        { value: 'TimeField', label: 'TimeField' },
        { value: 'URLField', label: 'URLField' },
        { value: 'UUIDField', label: 'UUIDField' },
    ]);

    useEffect(() => {
        const fetchModelsData = async () => {
            setLoading(true);
            try {
                const response = await axios.get('http://localhost:8000/api/available-models/'); // Ensure this matches your Django endpoint
                setModelsData(response.data);
            } catch (error) {
                console.error("Error fetching models:", error);
            } finally {
                setLoading(false);
            }
        };
        fetchModelsData();
    }, []);

    const handleAddField = () => {
        setCustomFields([...customFields, { name: '', type: '' }]);
    };

    const handleFieldChange = (index, field, value) => {
        const updatedFields = [...customFields];
        updatedFields[index][field] = value;
        setCustomFields(updatedFields);
    };

    const renderCustomFields = () => {
        return customFields.map((field, index) => (
            <tr key={index}>
                <td>
                    <input
                        type="text"
                        placeholder="Field Name"
                        value={field.name}
                        onChange={(e) => handleFieldChange(index, 'name', e.target.value)}
                        className="model-name-input"
                    />
                </td>
                <td>
                    <Select
                        options={fieldTypes}
                        onChange={(selectedOption) => handleFieldChange(index, 'type', selectedOption.value)}
                        placeholder="Select Field Type"
                    />
                </td>
            </tr>
        ));
    };

    const handleCreateCustomModel = async () => {
        const modelData = {
            name: customModelName,
            fields: customFields
        };

        try {
            await axios.post('http://localhost:8000/api/create-model/', modelData); // Ensure this matches your Django endpoint for creating models
            // Optionally reset state or show a success message
        } catch (error) {
            console.error("Error creating model:", error);
        }
    };

    return (
        <div>
            <h2>Generate API from Models</h2>
            <Select
                options={[
                    { value: 'builtIn', label: 'Use Built-in Models' },
                    { value: 'custom', label: 'Build Custom Model' },
                ]}
                onChange={(option) => setSelectedModels(option.value)}
                className="select-models"
            />
            {selectedModels === 'custom' && (
                <div className="custom-model-container">
                    <table className="custom-model-table">
                        <thead>
                            <tr>
                                <th colSpan="2" className="model-header">
                                    <div
                                        contentEditable
                                        suppressContentEditableWarning
                                        onBlur={(e) => setCustomModelName(e.target.innerText)}
                                        className="model-name-editable"
                                    >
                                        {customModelName}
                                    </div>
                                </th>
                                <th>
                                    <button className="add-field-button" onClick={handleAddField}>+</button>
                                </th>
                            </tr>
                            <tr>
                                <th>Field Name</th>
                                <th>Field Type</th>
                            </tr>
                        </thead>
                        <tbody>
                            {renderCustomFields()}
                        </tbody>
                    </table>
                    <button className="create-model-button" onClick={handleCreateCustomModel}>
                        Create Custom Model
                    </button>
                </div>
            )}
            {selectedModels === 'builtIn' && (
                <table className="built-in-models-table">
                    <thead>
                        <tr>
                            <th>Model Name</th>
                            <th>Fields</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr>
                                <td colSpan="2">Loading models...</td>
                            </tr>
                        ) : (
                            Object.keys(modelsData).map((modelName) => (
                                <tr key={modelName}>
                                    <td>{modelName}</td>
                                    <td>{modelsData[modelName].join(', ')}</td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            )}
        </div>
    );
};

export default GenerateApiTable;
