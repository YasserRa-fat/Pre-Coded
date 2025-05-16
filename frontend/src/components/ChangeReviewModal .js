
const [modalOpen, setModalOpen] = useState(false);
const [beforeText, setBeforeText] = useState('');
const [afterText, setAfterText] = useState('');
const [renderedPreview, setRenderedPreview] = useState('');

ws.onmessage = e => {
  const msg = JSON.parse(e.data);
  setMessages(prev => [...prev, msg]);
  if (msg.change_id) {
    setChangeId(msg.change_id);
    setBeforeText(msg.before || '');
    setAfterText(msg.after || '');
    setRenderedPreview(msg.preview || '');
    setModalOpen(true);
    setStatus('review');
  }
};
