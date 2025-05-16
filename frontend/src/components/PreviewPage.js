// src/components/PreviewPage.js

import React, { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';

export default function PreviewPage() {
  const { projectId } = useParams();
  const [qs] = useSearchParams();
  const file     = qs.get('file');
  const mode     = qs.get('mode')      || 'after';
  const changeId = qs.get('change_id') || '';
  const [html, setHtml] = useState('');

  useEffect(() => {
    if (!file) return;

    const params = new URLSearchParams({
      file,
      mode,
      ...(changeId && { change_id: changeId }),
    });

    const url = `/api/projects/${projectId}/preview/?${params.toString()}`;

    fetch(url, {
      credentials: 'include',            // send your JWT cookie
      headers: { 'Accept': 'text/html' } // optional: ensure we ask for HTML
    })
      .then(res => {
        if (!res.ok) throw new Error(`Status ${res.status}`);
        return res.text();
      })
      .then(setHtml)
      .catch(err => {
        console.error('Preview fetch error:', err);
        setHtml(`<pre style="padding:1rem;color:red;">Error loading preview: ${err.message}</pre>`);
      });
  }, [projectId, file, mode, changeId]);

  return (
    <div style={{ width: '100%', height: '100vh' }} 
         dangerouslySetInnerHTML={{ __html: html }} />
  );
}
