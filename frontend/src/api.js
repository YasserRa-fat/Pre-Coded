import axios from "axios";

const api = axios.create({
  baseURL: process.env.REACT_APP_API_BASE_URL || "http://127.0.0.1:8000/api/",
});

// attach JWT token if present
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// handle responses & errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // if server responded, error.response exists
    if (error.response) {
      // e.g. auto‐logout on 401
      if (error.response.status === 401) {
        localStorage.clear();
        // optionally send them to a global /login
        window.location.href = "/login";
      }
      return Promise.reject(error);
    }
    // otherwise it’s a network / CORS / timeout / DNS error
    console.error("Network / CORS error:", error);
    return Promise.reject(error);
  }
);

export default api;
