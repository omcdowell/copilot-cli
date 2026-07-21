# HTML template for viewing file contents
FILE_VIEW_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>File Viewer - {{ filename }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .header { background: #f0f0f0; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
        .back-link { margin-bottom: 20px; display: block; color: #0066cc; text-decoration: none; }
        .back-link:hover { text-decoration: underline; }
        .file-content { background: #f8f8f8; padding: 20px; border-radius: 5px; margin: 20px 0; }
        .file-content pre { white-space: pre-wrap; word-wrap: break-word; font-family: 'Courier New', monospace; }
        .binary-warning { color: #ff6600; font-weight: bold; background: #fff3cd; padding: 10px; border-radius: 5px; }
        .file-info { color: #666; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="header">
        <h1>📄 {{ filename }}</h1>
        <div class="file-info">
            <strong>Path:</strong> {{ file_path }}<br>
            <strong>Size:</strong> {{ file_size }}<br>
            <strong>Type:</strong> {{ file_type }}<br>
            <strong>Mimetype:</strong> {{ mimetype }}
        </div>
    </div>

    <a href="{{ url_for('browse', path=parent_path) }}" class="back-link">← Back to Directory</a>

    {% if is_binary %}
    <div class="binary-warning">
        ⚠️ This appears to be a binary file. Displaying content may not be meaningful.
    </div>
    {% endif %}

    <div class="file-content">
        <pre>{{ file_content }}</pre>
    </div>
</body>
</html>
"""
