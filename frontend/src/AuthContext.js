import React, { createContext, useEffect, useState } from 'react';
import api from './api';

export const AuthContext = createContext({
  user: null,
  token: null,
  setUser: () => {},
  setToken: () => {},
});

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('access_token') || null);

  // On mount, try to load current_user if we have a token
  useEffect(() => {
    const storedToken = localStorage.getItem('access_token');
    if (storedToken) {
      setToken(storedToken); // Sync token state with localStorage
      api.get('/current_user/', {
        headers: { Authorization: `Bearer ${storedToken}` },
      })
        .then(res => setUser(res.data))
        .catch(() => {
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          setUser(null);
          setToken(null);
        });
    }
  }, []);

  // Sync token to localStorage whenever it changes
  useEffect(() => {
    if (token) {
      localStorage.setItem('access_token', token);
    } else {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    }
  }, [token]);

  return (
    <AuthContext.Provider value={{ user, token, setUser, setToken }}>
      {children}
    </AuthContext.Provider>
  );
};