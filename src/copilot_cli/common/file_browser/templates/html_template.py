# HTML template for the file explorer

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>File Explorer</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .file-item { padding: 8px; border-bottom: 1px solid #eee; }
        .file-item:hover { background-color: #f5f5f5; }
        .directory { color: #0066cc; font-weight: bold; }
        .file { color: #333; }
        .back-link { margin-bottom: 20px; display: block; }
        .current-path { background: #f0f0f0; padding: 10px; margin-bottom: 20px; border-radius: 5px; }
        .file-size { color: #666; font-size: 0.9em; }
        .file-content { background: #f8f8f8; padding: 20px; border-radius: 5px; margin: 20px 0; }
        .file-content pre { white-space: pre-wrap; word-wrap: break-word; }
        .binary-warning { color: #ff6600; font-weight: bold; }

        table.browser {
            display: block;
            table-layout: fixed;
            border-collapse: collapse;
            overflow-x: auto;
            position: fixed;
            top: 180px;
            right: 15px;
            left: 15px;
        }

        table.browser tr:nth-child(2n) {
            background-color: #efefef;
        }

        table.browser th,
        table.browser td {
            margin: 0;
            text-align: center;
            vertical-align: middle;
            white-space: nowrap;
            padding: 10px;
        }

        table.browser th {
            padding-bottom: 10px;
            border-bottom: 1px solid black;
        }

        table.browser td:first-child {
            text-align: left;
            width: 100%;
        }

        table.browser td:nth-child(5) {
            width: 175px;
        }
    </style>
</head>
<body>
    {% macro th(text, property, type='text', colspan=1) -%}
    <th{% if colspan > 1 %} colspan="{{ colspan }}"{% endif %}> {{ text }} </th>
    {%- endmacro %}
    <h1>File Explorer</h1>

    <div class="current-path">
        <strong>Current Path:</strong> {{ current_path }}
    </div>

    {% if parent_path %}
        {% if parent_path == "root" %}
        <a href="{{ url_for('browse', path='') }}" class="back-link">← Back to Root</a>
        {% else %}
        <a href="{{ url_for('browse', path=parent_path) }}" class="back-link">← Back to {{ parent_path }}</a>
        {% endif %}
    {% endif %}
    {% if not items %}
        <p>This directory is empty.</p>
    {% else %}

        <table class="browser">
            <thead>
                <tr>
                {{ th('Name', 'text', 'text') }}
                {{ th('Modified', 'modified', 'numeric') }}
                {{ th('Mimetype', 'type') }}
                {{ th('Size', 'size', 'numeric') }}
                {{ th('View', '')}}
                {{ th('Download', '')}}
                </tr>
            </thead>
            <tbody>
                {% for item in items %}
                    <tr>
                        <td>
                            {% if item.is_dir %}
                                <a href="{{ url_for('browse', path=item.path) }}" class="directory">
                                    📁 {{ item.name }}/
                                </a>
                            {% else %}
                                <a href="{{ url_for('view', path=item.path) }}">
                                    📄 {{ item.name }}
                                </a>
                            {% endif %}
                        </td>
                        <td> {{ item.modified }} </td>
                        <td> {{ item.type }} </td>
                        <td> {{ item.size }} </td>
                        <td>
                            {% if item.is_dir %}
                                <a href="{{ url_for('browse', path=item.path) }}" class="directory">
                                    👁️
                                </a>
                            {% else %}
                                <a href="{{ url_for('view', path=item.path) }}">
                                    👁️
                                </a>
                            {% endif %}
                        </td>
                        <td>
                            {% if not item.is_dir %}
                                <a href="{{ url_for('download', path=item.path) }}">⬇️ </a>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}

            </tbody>
        </table>

    {% endif %}
</body>
</html>
"""
