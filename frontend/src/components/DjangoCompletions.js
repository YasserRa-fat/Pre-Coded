// djangoCompletions.js

// This function registers Django-related completion suggestions for the Monaco Editor.
// The triggerCharacters setting ensures that suggestions show (e.g. when you type a dot).
export function registerDjangoCompletions(monaco) {
    const suggestions = [
      {
        label: 'models.CharField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: 'models.CharField(max_length=255)',
        documentation: 'Django CharField with max_length of 255.'
      },
      {
        label: 'models.TextField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: 'models.TextField()',
        documentation: 'Django TextField for large text.'
      },
      {
        label: 'models.IntegerField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: 'models.IntegerField()',
        documentation: 'Django IntegerField.'
      },
      {
        label: 'models.FloatField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: 'models.FloatField()',
        documentation: 'Django FloatField.'
      },
      {
        label: 'models.BooleanField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: 'models.BooleanField(default=False)',
        documentation: 'Django BooleanField with default False.'
      },
      {
        label: 'models.DateField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: 'models.DateField()',
        documentation: 'Django DateField.'
      },
      {
        label: 'models.DateTimeField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: 'models.DateTimeField(auto_now_add=True)',
        documentation: 'Django DateTimeField with auto_now_add set.'
      },
      {
        label: 'models.EmailField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: 'models.EmailField()',
        documentation: 'Django EmailField.'
      },
      {
        label: 'models.FileField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: "models.FileField(upload_to='uploads/')",
        documentation: 'Django FileField.'
      },
      {
        label: 'models.ImageField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: "models.ImageField(upload_to='images/')",
        documentation: 'Django ImageField.'
      },
      {
        label: 'models.SlugField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: 'models.SlugField(unique=True)',
        documentation: 'Django SlugField with uniqueness constraint.'
      },
      {
        label: 'models.URLField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: 'models.URLField()',
        documentation: 'Django URLField.'
      },
      {
        label: 'models.ForeignKey',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: "models.ForeignKey('RelatedModel', on_delete=models.CASCADE)",
        documentation: 'Django ForeignKey field.'
      },
      {
        label: 'models.OneToOneField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: "models.OneToOneField('RelatedModel', on_delete=models.CASCADE)",
        documentation: 'Django OneToOneField.'
      },
      {
        label: 'models.ManyToManyField',
        kind: monaco.languages.CompletionItemKind.Function,
        insertText: "models.ManyToManyField('RelatedModel')",
        documentation: 'Django ManyToManyField.'
      }
      // Add additional Django model field suggestions as necessary.
    ];
  
    monaco.languages.registerCompletionItemProvider('python', {
      provideCompletionItems: () => {
        return { suggestions };
      },
      triggerCharacters: ['.', '(']  // these characters can prompt suggestions automatically
    });
  }