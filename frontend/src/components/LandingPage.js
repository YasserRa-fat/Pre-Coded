import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './css/LandingPage.css';

const LandingPage = () => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const response = await fetch('/api/current_user/', {
          headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
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

  const loggedInCards = [
    {
      title: 'Browse User Models',
      description: 'View and manage all of your user models.',
      route: '/user-models',
    },
    {
      title: 'Parse Model',
      description: 'Paste code to parse and visualize your model.',
      route: '/parse-model',
    },
    {
      title: 'Parse View',
      description: 'Paste code to generate a view diagram quickly.',
      route: '/parse-view',
    },
    {
      title: 'My Projects',
      description: 'Access and manage all of your projects in one place.',
      route: '/my-projects',
    },
  ];

  return (
    <div className={`landing-container ${user ? 'logged-in' : ''}`}>
      {/* Hero Section */}
      <header className="hero-section">
        <h1>{user ? `Hi, ${user.username}!` : 'Welcome to Core Fusion'}</h1>
        <p>
          {user
            ? 'What are we building today?'
            : 'Transform your code into interactive diagrams effortlessly. Our platform converts code into dynamic diagrams with reusable components and leverages AI to provide easy-to-understand code summaries.'}
        </p>
       
      </header>

      {/* Logged-in View: Interactive Cards */}
      {user && (
        <section className="dashboard-cards">
          <h2>Quick Actions</h2>
          <p>Select one of the options below to get started.</p>
          <br/>
          <div className="cards-grid">
            {loggedInCards.map((card, index) => (
              <div className="action-card" key={index}>
                <h3>{card.title}</h3>
                <p>{card.description}</p>
                <button onClick={() => navigate(card.route)} className="primary-btn">
                  Go
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Guest View: Marketing Sections */}
      {!user && (
        <>
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
        </>
      )}
    </div>
  );
};

export default LandingPage;