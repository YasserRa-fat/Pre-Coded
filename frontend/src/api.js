// src/api.js
import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api/', // Django API URL
  headers: {
    'Content-Type': 'application/json',
  },
});

// Attach JWT access token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Refresh the access token when expired
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    if (error.response.status === 401) {
      if (originalRequest._retry) {
        console.error('Refresh token expired, redirecting to login');
        window.location.href = '/login';
        return Promise.reject(error);
      }
      originalRequest._retry = true;
      const refreshToken = localStorage.getItem('refresh_token');
      try {
        const { data } = await axios.post('http://localhost:8000/api/token/refresh/', {
          refresh: refreshToken,
        });
        localStorage.setItem('access_token', data.access);
        originalRequest.headers.Authorization = `Bearer ${data.access}`;
        return api(originalRequest);
      } catch (refreshError) {
        console.error('Failed to refresh token:', refreshError);
        window.location.href = '/login'; // Redirect if refresh fails
        return Promise.reject(refreshError);
      }
    }
    return Promise.reject(error);
  }
);

export default api;
