import React, { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import api from '../api';
import "./css/Login.css";

const Login = () => {
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [error, setError]         = useState('');
  const navigate                  = useNavigate();
  const { projectId }             = useParams();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const { data } = await api.post('/token/', formData);
      localStorage.setItem('access_token',  data.access);
      localStorage.setItem('refresh_token', data.refresh);
      console.log('Logged in:', data);

      if (projectId) {
        navigate(`/projects/${projectId}/`, { replace: true });
      } else {
        navigate('/', { replace: true });
      }
    } catch (err) {
      // only read status if it exists
      const status = err.response?.status;
      if (status === 401) {
        setError('Invalid login credentials');
      } else {
        setError('Network error—please try again');
      }
      console.error(err);
    }
  };

  return (
    <div className="login-container">
      <header className="login-header">
        <h2>Login</h2>
      </header>

      {error && <p className="login-error">{error}</p>}

      <form onSubmit={handleSubmit} className="login-form">
        <div className="login-input-group">
          <label>Username</label>
          <input
            type="text"
            value={formData.username}
            onChange={(e) => setFormData({ ...formData, username: e.target.value })}
          />
        </div>
        <div className="login-input-group">
          <label>Password</label>
          <input
            type="password"
            value={formData.password}
            onChange={(e) => setFormData({ ...formData, password: e.target.value })}
          />
        </div>
        <div className="login-buttons">
          <button type="submit" className="login-btn primary-btn">Login</button>
        </div>
      </form>
    </div>
  );
};

export default Login;
