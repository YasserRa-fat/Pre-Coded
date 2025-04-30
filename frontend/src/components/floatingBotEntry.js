import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import FloatingChat from './components/FloatingChat';

const container = document.createElement('div');
container.id = 'floating-chat-container';
document.body.appendChild(container);

const root = createRoot(container);
root.render(
  <BrowserRouter>
    <FloatingChat />
  </BrowserRouter>
);
