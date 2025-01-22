import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api';

const Register = () => {
  const [formData, setFormData] = useState({ username: '', email: '', password: '' });
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await api.post('/register/', formData);
      // Store tokens and navigate on successful registration
      localStorage.setItem('access_token', response.data.access);
      localStorage.setItem('refresh_token', response.data.refresh);
      navigate('/generate-api'); // Redirect to /generate-api on success
    } catch (err) {
      console.log('Error response:', err.response); // Log the entire error response
      console.log('Error data:', err.response?.data); // Log just the data part for inspection
    
      if (err.response && err.response.data) {
        const errorMessage = err.response.data.message; // Extract the message string
    
        // Initialize an array to hold user-friendly messages
        const userFriendlyMessages = [];
    
        // Check for username errors
        if (errorMessage.includes("username")) {
          userFriendlyMessages.push("A user with that username already exists.");
        }
        
        // Check for email errors
        if (errorMessage.includes("email")) {
          userFriendlyMessages.push("A user with this email already exists.");
        }
    
        // Set error messages to state, using line breaks for separation
        setError(userFriendlyMessages.length > 0 ? userFriendlyMessages.join('\n') : 'Registration failed.');
      } else {
        setError('Registration failed. Please try again.');
      }
    }
    
  };
  return (
    <form onSubmit={handleSubmit}>
      <h2>Register</h2>
      {error && (
        <div style={{ whiteSpace: 'pre-line', color: 'red' }}>
          {error}
        </div>
      )}
      <div>
        <label>Username</label>
        <input
          type="text"
          value={formData.username}
          onChange={(e) => setFormData({ ...formData, username: e.target.value })}
        />
      </div>
      <div>
        <label>Email</label>
        <input
          type="email"
          value={formData.email}
          onChange={(e) => setFormData({ ...formData, email: e.target.value })}
        />
      </div>
      <div>
        <label>Password</label>
        <input
          type="password"
          value={formData.password}
          onChange={(e) => setFormData({ ...formData, password: e.target.value })}
        />
      </div>
      <button type="submit">Register</button>
    </form>
  );
  
};

export default Register;
