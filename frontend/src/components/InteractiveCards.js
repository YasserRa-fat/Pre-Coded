import React from 'react';
import { useNavigate } from 'react-router-dom';
import './InteractiveCards.css'; // Add styling for hover effects

const routes = [
  { path: "/register", title: "Register", description: "Create an account" },
  { path: "/login", title: "Login", description: "Access your dashboard" },
  { path: "/create-user-model", title: "Create Model", description: "Build your model" },
  { path: "/user-models", title: "User Models", description: "Manage your models" },
  { path: "/my-projects", title: "Projects", description: "View all projects" },
];

const InteractiveCards = () => {
  const navigate = useNavigate();

  return (
    <div className="card-container">
      {routes.map((route, index) => (
        <div key={index} className="card" onClick={() => navigate(route.path)}>
          <h3>{route.title}</h3>
          <p>{route.description}</p>
        </div>
      ))}
    </div>
  );
};

export default InteractiveCards;
