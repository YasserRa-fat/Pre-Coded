import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api';
import "./css/Login.css"; // Import the new CSS file

const Login = () => {
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await api.post('/token/', formData);
      localStorage.setItem('access_token', response.data.access);
      localStorage.setItem('refresh_token', response.data.refresh);
      console.log('Logged in:', response.data);
      navigate('/'); // Redirect to /
    } catch (err) {
      console.error(err);
      setError('Invalid login credentials');
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