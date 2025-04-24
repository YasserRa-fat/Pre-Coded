import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api';
import "./css/Register.css"; // Import the new CSS file

const Register = () => {
  const [formData, setFormData] = useState({ username: '', email: '', password: '' });
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    // Clear any existing tokens before registering
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');

    try {
      const response = await api.post('/register/', formData);
      // Store tokens and navigate on successful registration
      localStorage.setItem('access_token', response.data.access);
      localStorage.setItem('refresh_token', response.data.refresh);
      console.log('Registered successfully:', response.data);
      navigate('/generate-api'); // Redirect to /generate-api on success
    } catch (err) {
      console.log('Error response:', err.response);
      console.log('Error data:', err.response?.data);
      if (err.response && err.response.data) {
        const errorMessage = err.response.data.message || '';
        const userFriendlyMessages = [];
        if (errorMessage.includes("username")) {
          userFriendlyMessages.push("A user with that username already exists.");
        }
        if (errorMessage.includes("email")) {
          userFriendlyMessages.push("A user with this email already exists.");
        }
        setError(
          userFriendlyMessages.length > 0
            ? userFriendlyMessages.join('\n')
            : 'Registration failed.'
        );
      } else {
        setError('Registration failed. Please try again.');
      }
    }
  };

  return (
    <div className="register-container">
      <header className="register-header">
        <h2>Register</h2>
      </header>

      {error && <p className="register-error">{error}</p>}

      <form onSubmit={handleSubmit} className="register-form">
        <div className="register-input-group">
          <label>Username</label>
          <input
            type="text"
            value={formData.username}
            onChange={(e) =>
              setFormData({ ...formData, username: e.target.value })
            }
          />
        </div>
        <div className="register-input-group">
          <label>Email</label>
          <input
            type="email"
            value={formData.email}
            onChange={(e) =>
              setFormData({ ...formData, email: e.target.value })
            }
          />
        </div>
        <div className="register-input-group">
          <label>Password</label>
          <input
            type="password"
            value={formData.password}
            onChange={(e) =>
              setFormData({ ...formData, password: e.target.value })
            }
          />
        </div>
        <div className="register-buttons">
          <button type="submit" className="register-btn primary-btn">
            Register
          </button>
        </div>
      </form>
    </div>
  );
};

export default Register;