import React, { useContext, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import api from '../api';
import { AuthContext } from '../AuthContext';
import "./css/Login.css";

const Login = () => {
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const { projectId } = useParams();
  const { setUser, setToken } = useContext(AuthContext);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      // 1) get tokens
      const { data } = await api.post('/token/', formData);

      // 2) store tokens in context
      setToken(data.access);
      localStorage.setItem('refresh_token', data.refresh); // Keep refresh token in localStorage
      console.log("🔐 JWT access token:", data.access);

      // 3) fetch current_user and put into context
      const userRes = await api.get('/current_user/');
      setUser(userRes.data);

      // 4) redirect
      if (projectId) {
        navigate(`/projects/${projectId}/`, { replace: true });
      } else {
        navigate('/', { replace: true });
      }
    } catch (err) {
      const status = err.response?.status;
      if (status === 401) {
        setError('Invalid login credentials');
      } else {
        setError('Network error—please try again');
      }
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
            onChange={e => setFormData({ ...formData, username: e.target.value })}
          />
        </div>
        <div className="login-input-group">
          <label>Password</label>
          <input
            type="password"
            value={formData.password}
            onChange={e => setFormData({ ...formData, password: e.target.value })}
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