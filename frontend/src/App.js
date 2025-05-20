import React from 'react';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import Navbar from './components/Navbar';
import { DiffProvider } from './context/DiffContext';
import AppRoutes from './routes';

function App() {
  return (
    <DiffProvider>
      <Navbar />
      <AppRoutes />
      {/* <FloatingChat /> */}
      <ToastContainer />
    </DiffProvider>
  );
}

export default App;
