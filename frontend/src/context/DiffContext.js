import React, { createContext, useContext, useState } from 'react';

const DiffContext = createContext();

export function DiffProvider({ children }) {
  const [diffData, setDiffData] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isChatOpen, setIsChatOpen] = useState(false);

  const showDiffModal = (data, shouldOpen = true) => {
    console.log('DiffContext: Showing modal with data:', data);
    setDiffData(data);
    if (shouldOpen) {
      setIsModalOpen(true);
    }
  };

  const hideDiffModal = (force = false) => {
    // Only hide the modal, don't clear data unless forced
    setIsModalOpen(false);
    if (force) {
      setDiffData(null);
    }
  };

  const clearDiffData = () => {
    // Only clear data when explicitly requested (after apply/cancel)
    setDiffData(null);
    setIsModalOpen(false);
  };

  const setChatOpen = (isOpen) => {
    console.log('DiffContext: Setting chat open state:', isOpen);
    setIsChatOpen(isOpen);
    // Never close the modal when chat is closed
  };

  return (
    <DiffContext.Provider
      value={{
        diffData,
        isModalOpen,
        isChatOpen,
        showDiffModal,
        hideDiffModal,
        clearDiffData,
        setChatOpen,
      }}
    >
      {children}
    </DiffContext.Provider>
  );
}

export function useDiff() {
  const context = useContext(DiffContext);
  if (!context) {
    throw new Error('useDiff must be used within a DiffProvider');
  }
  return context;
}

export default DiffContext; 