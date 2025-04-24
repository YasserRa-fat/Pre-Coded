import Editor from '@monaco-editor/react';
import React from 'react';

const TestEditor = () => {
  const handleEditorDidMount = (editor, monaco) => {
    console.log("TestEditor Mounted", monaco);
    monaco.languages.registerCompletionItemProvider('python', {
      triggerCharacters: ['.'],
      provideCompletionItems: () => {
        return {
          suggestions: [
            {
              label: 'testSuggestion',
              kind: monaco.languages.CompletionItemKind.Text,
              insertText: 'testSuggestion()',
              documentation: 'This is a test suggestion.'
            }
          ]
        };
      }
    });
  };

  return (
    <Editor
      height="300px"
      language="python"
      value="import this\n"
      theme="vs-dark"
      onMount={handleEditorDidMount}
    />
  );
};

export default TestEditor;