import axios from 'axios';
import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import './css/UserModels.css';

const UserModels = () => {
    const [userModels, setUserModels] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [viewOption, setViewOption] = useState('my_models');

    useEffect(() => {
        const fetchUserModels = async () => {
            const token = localStorage.getItem('access_token');
            try {
                const response = await axios.get(`http://localhost:8000/usermodels/?filter_type=${viewOption}`, {
                    headers: {
                        Authorization: `Bearer ${token}`,
                    },
                });
                setUserModels(response.data);
            } catch (err) {
                console.error(err); // Log error for debugging
                setError(err.response ? err.response.data.detail : 'Failed to fetch user models.');
            } finally {
                setLoading(false);
            }
        };

        const timeoutId = setTimeout(() => {
            fetchUserModels();
        }, 300);

        return () => clearTimeout(timeoutId);
    }, [viewOption]);

    const handleViewOptionChange = (event) => {
        setViewOption(event.target.value);
    };

    if (loading) return <p>Loading...</p>;
    if (error) return <p>{error}</p>;

    return (
        <div className="user-models-container">
            <h1>User Models</h1>
            <div className="view-options">
                <label>
                    <input
                        type="radio"
                        value="my_models"
                        checked={viewOption === 'my_models'}
                        onChange={handleViewOptionChange}
                    />
                    My Models
                </label>
                <label>
                    <input
                        type="radio"
                        value="other_models"
                        checked={viewOption === 'other_models'}
                        onChange={handleViewOptionChange}
                    />
                    Other Users' Models
                </label>
                <label>
                    <input
                        type="radio"
                        value="all_models"
                        checked={viewOption === 'all_models'}
                        onChange={handleViewOptionChange}
                    />
                    All Models
                </label>
            </div>
            <div className="cards-container">
                {userModels.length === 0 ? (
                    <p>No models to display.</p>
                ) : (
                    userModels.map((model) => (
                        <Link to={`/usermodel/${model.id}`} key={model.id} className="model-card-link">
                            <div className="model-card">
                                <h2>{model.model_name || 'Unnamed Model'}</h2>
                                {/* Display the description of the model */}
                                <div className="model-description">
                                    {model.description ? (
                                        <p>{model.description}</p>
                                    ) : (
                                        <p>No description provided.</p>
                                    )}
                                </div>
                                <div>
                                    <strong>Visibility:</strong>
                                    <span className={`visibility-${model.visibility ? model.visibility.toLowerCase() : ''}`}>
                                        <span className="visibility-text">{model.visibility}</span>
                                    </span>
                                </div>
                            </div>
                        </Link>
                    ))
                )}
            </div>
        </div>
    );
};

export default UserModels;
