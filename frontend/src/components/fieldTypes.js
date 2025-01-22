const fieldTypes = [
    { 
        value: 'CharField', 
        label: 'CharField', 
        parameters: [
            { name: 'max_length', required: true }, 
            { name: 'default', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'IntegerField', 
        label: 'IntegerField', 
        parameters: [
            { name: 'min_value', required: true }, 
            { name: 'max_value', required: false },
            { name: 'default', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'EmailField', 
        label: 'EmailField', 
        parameters: [
            { name: 'max_length', required: false },
            { name: 'default', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'BooleanField', 
        label: 'BooleanField', 
        parameters: [
            { name: 'default', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'DateField', 
        label: 'DateField', 
        parameters: [
            { name: 'auto_now', required: false }, 
            { name: 'auto_now_add', required: false },
            { name: 'default', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'DateTimeField', 
        label: 'DateTimeField', 
        parameters: [
            { name: 'auto_now', required: false }, 
            { name: 'auto_now_add', required: false },
            { name: 'default', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'ForeignKey', 
        label: 'ForeignKey', 
        parameters: [
            { name: 'to', required: true },
            { name: 'on_delete', required: true },
            { name: 'related_name', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'ManyToManyField', 
        label: 'ManyToManyField', 
        parameters: [
            { name: 'to', required: true },
            { name: 'related_name', required: false },
            { name: 'blank', required: false }
        ] 
    },
    { 
        value: 'DecimalField', 
        label: 'DecimalField', 
        parameters: [
            { name: 'max_digits', required: true },
            { name: 'decimal_places', required: true },
            { name: 'default', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'FileField', 
        label: 'FileField', 
        parameters: [
            { name: 'upload_to', required: true },
            { name: 'max_length', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'ImageField', 
        label: 'ImageField', 
        parameters: [
            { name: 'upload_to', required: true },
            { name: 'max_length', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'UUIDField', 
        label: 'UUIDField', 
        parameters: [
            { name: 'default', required: true },
            { name: 'editable', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'SlugField', 
        label: 'SlugField', 
        parameters: [
            { name: 'max_length', required: true },
            { name: 'unique', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'TextField', 
        label: 'TextField', 
        parameters: [
            { name: 'blank', required: false },
            { name: 'null', required: false },
            { name: 'default', required: false }
        ] 
    },
    { 
        value: 'TimeField', 
        label: 'TimeField', 
        parameters: [
            { name: 'auto_now', required: false },
            { name: 'auto_now_add', required: false },
            { name: 'default', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'DurationField', 
        label: 'DurationField', 
        parameters: [
            { name: 'default', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'IPAddressField', 
        label: 'IPAddressField', 
        parameters: [
            { name: 'protocol', required: false },
            { name: 'unpack', required: false },
            { name: 'default', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
    { 
        value: 'GenericIPAddressField', 
        label: 'GenericIPAddressField', 
        parameters: [
            { name: 'protocol', required: false },
            { name: 'unpack', required: false },
            { name: 'default', required: false },
            { name: 'blank', required: false },
            { name: 'null', required: false }
        ] 
    },
];

export default fieldTypes;