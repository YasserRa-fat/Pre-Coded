import React from 'react';
import { Route, BrowserRouter as Router, Routes } from 'react-router-dom';
import CreateUserModel from './components/CreateUserModel';
import GenerateApiTable from './components/GenerateAPITable';
import Login from './components/Login';
import ModelDetail from './components/ModelDetail'; // Import the ModelDetail component
import Register from './components/Register';
import UserModels from './components/UserModels';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/register" element={<Register />} />
        <Route path="/login" element={<Login />} />
        <Route path="/create-user-model" element={<CreateUserModel />} />
        <Route path="/generate-api" element={<GenerateApiTable />} />
        <Route path="/user-models" element={<UserModels />} /> 
        <Route path="/usermodel/:id" element={<ModelDetail />} /> 
      </Routes>
    </Router>
  );
}

export default App;
