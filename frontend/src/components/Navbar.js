import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import "./css/Navbar.css";

const Navbar = () => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    // Check authentication (adjust the API call as needed)
    const checkAuth = async () => {
      try {
        const response = await fetch('/api/current_user/', {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`
          }
        });
        if (response.ok) {
          const data = await response.json();
          setUser(data);
        } else {
          setUser(null);
        }
      } catch (error) {
        setUser(null);
      } finally {
        setLoading(false);
      }
    };

    checkAuth();
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('access_token');
    setUser(null);
    navigate('/');
  };

  const isAuthenticated = user && user.username;

  if (loading) return null; // or a spinner if desired

  return (
    <nav className="navbar">
      <div className="navbar-brand" onClick={() => navigate('/')}>
        Core Fusion
      </div>
      <ul className="navbar-links">
        {location.pathname !== '/' && (
          <li>
            <Link to="/">Home</Link>
          </li>
        )}
        {isAuthenticated ? (
          <>
            {location.pathname !== '/dashboard' && (
              <li>
                <Link to="/dashboard">Dashboard</Link>
              </li>
            )}
            <li className="logout-btn" onClick={handleLogout}>
              Logout
            </li>
          </>
        ) : (
          <>
            {location.pathname !== '/login' && (
              <li>
                <Link to="/login">Log In</Link>
              </li>
            )}
            {location.pathname !== '/register' && (
              <li>
                <Link to="/register">Sign Up</Link>
              </li>
            )}
          </>
        )}
      </ul>
    </nav>
  );
};

export default Navbar;
