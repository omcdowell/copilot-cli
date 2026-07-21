# HTML template for when no data is available to view
NO_DATA_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>No Data Available</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            text-align: center;
            padding-top: 50px;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background: #f8f8f8;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .icon {
            font-size: 48px;
            margin-bottom: 20px;
        }
        .message {
            color: #666;
            margin-bottom: 20px;
        }
        .back-link {
            color: #0066cc;
            text-decoration: none;
        }
        .back-link:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">📄</div>
        <h1>No Data Available</h1>
        <div class="message">
            The requested file / Directory could not be displayed because it does not exist.
        </div>
        <a href="{{ url_for('browse', path=parent_path) }}" class="back-link">← Back to Directory</a>
    </div>
</body>
</html>
"""
