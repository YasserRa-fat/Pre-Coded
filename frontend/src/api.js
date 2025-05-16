// src/api.js
import axios from 'axios';

// 1) create an axios instance
const api = axios.create({
  baseURL: 'http://127.0.0.1:8000/api',      // adjust if needed
  headers: { 'Content-Type': 'application/json' },
});

// 2) on every request, read the token and set Authorization header
api.interceptors.request.use(config => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;
