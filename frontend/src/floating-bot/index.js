import React from 'react';
import { createRoot } from 'react-dom/client';
import FloatingChat from './FloatingChat';

const container = document.createElement('div');
container.id = 'floating-chat-container';
document.body.appendChild(container);

const root = createRoot(container);
root.render(<FloatingChat />);
