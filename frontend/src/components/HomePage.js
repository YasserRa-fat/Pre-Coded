import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './css/HomePage.css'; // Import the new CSS file

const HomePage = () => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const response = await fetch('/api/current_user/', {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
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

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div className="home-container">
      <header className="hero-section">
        <h1>Welcome to Core Fusion</h1>
        <p>Transform your code into interactive diagrams effortlessly. Our platform converts code into dynamic diagrams with reusable components and leverages AI to provide easy-to-understand code summaries.</p>
        <div className="cta-buttons">
          <button onClick={() => navigate('/login')} className="primary-btn">
            Log In
          </button>
          <button onClick={() => navigate('/register')} className="secondary-btn">
            Sign Up Free
          </button>
        </div>
      </header>

      {/* Features Section */}
      <section className="features-section">
        <h2>Why Choose Us?</h2>
        
        <div className="feature-grid">
          <div className="feature-item">
            <h3>Automated Diagrams</h3>
            <p>Convert your code to visual diagrams with zero manual effort.</p>
          </div>
          <div className="feature-item">
            <h3>Interactive Editing</h3>
            <p>Modify and update diagrams in real time.</p>
          </div>
          <div className="feature-item">
            <h3>AI Summaries</h3>
            <p>Receive concise, easy-to-understand summaries of your code components.</p>
          </div>
        </div>
      </section>

      {/* How It Works Section */}
      <section className="how-it-works">
        <h2>How It Works</h2>
        <div className="steps">
          <div className="step">
            <span>1</span>
            <p>Paste your code or upload files</p>
          </div>
          <div className="step">
            <span>2</span>
            <p>Let our AI analyze and visualize</p>
          </div>
          <div className="step">
            <span>3</span>
            <p>Edit and share your diagrams</p>
          </div>
        </div>
      </section>
    </div>
  );
};

export default HomePage;