import mimetypes
import os
import sys
from datetime import datetime

from flask import Flask, abort, render_template_string, send_file

from copilot_cli.common.file_browser.templates.file_view_template import FILE_VIEW_TEMPLATE
from copilot_cli.common.file_browser.templates.html_template import HTML_TEMPLATE
from copilot_cli.common.file_browser.templates.no_data import NO_DATA_TEMPLATE


class FileBrowserApp:

    def __init__(self, directory: str):
        """
        Initialize the File Browser Flask application

        Args:
            directory (str): The root directory to browse
        """
        self.directory = os.path.abspath(directory)
        self.app = Flask(__name__)
        self._setup_routes()

    def _setup_routes(self):
        """Setup all the Flask routes"""

        @self.app.route("/")
        @self.app.route("/<path:path>")
        def browse(path=None):
            if path is None:
                path = self.directory

            try:
                # Verify the path is within the root directory
                full_path = self.__get_and_verify_path(path)

                if not os.path.isdir(full_path):
                    abort(400, description="Not a directory")

                # Get parent path for navigation
                parent_path = None
                if path and path != self.directory:
                    # Get the parent directory path for the URL
                    parent_dir = os.path.dirname(path)
                    if parent_dir == "":
                        # We're at the first nested level, so parent should be root
                        # Use "root" as a special value to trigger back link to root in template
                        parent_path = "root"
                    else:
                        parent_path = parent_dir

                # List directory contents
                items = []
                for item_name in sorted(os.listdir(full_path)):
                    # For URL routing, construct the path relative to the root
                    if path == self.directory or path is None:
                        # At root level, use just the item name
                        item_path = item_name
                    else:
                        # For subdirectories, construct the path from root
                        item_path = os.path.join(path, item_name)

                    full_item_path = os.path.join(full_path, item_name)
                    modified = self._get_modified(full_item_path)

                    if os.path.isdir(full_item_path):
                        items.append(FileItem(item_name, item_path, True, "Directory", modified))
                    else:
                        size = self._get_file_size(full_item_path)
                        mimetype = self._get_mimetype(full_item_path)
                        items.append(FileItem(item_name, item_path, False, mimetype, modified, size))

                return render_template_string(HTML_TEMPLATE, items=items, current_path=full_path, parent_path=parent_path)

            except Exception as e:
                abort(500, description=str(e))

        @self.app.route("/view/<path:path>")
        def view(path):
            try:
                full_file_path = self.__get_and_verify_path(path)

                if os.path.isdir(full_file_path):
                    abort(400, description="Cannot view a directory")

                with open(full_file_path, "rb") as f:
                    file_content = f.read()

                # Determine if the file is binary
                is_binary = False
                if len(file_content) > 1024:  # Check first 1KB for binary characteristics
                    is_binary = any(byte >= 128 for byte in file_content[:1024])

                # Get file info
                file_path = os.path.abspath(full_file_path)
                file_size = self._get_file_size(file_path)
                mimetype = self._get_mimetype(file_path)
                file_type = os.path.splitext(full_file_path)[1].lower() if os.path.splitext(full_file_path)[1] else "Unknown"

                # Get parent path for back link
                parent_path = os.path.dirname(path)
                if parent_path == path:  # Handle root directory case
                    parent_path = None

                return render_template_string(
                    FILE_VIEW_TEMPLATE,
                    filename=os.path.basename(full_file_path),
                    file_path=file_path,
                    file_size=file_size,
                    file_type=file_type,
                    file_content=file_content.decode("utf-8", errors="ignore") if not is_binary else "Binary data",
                    parent_path=parent_path,
                    is_binary=is_binary,
                    mimetype=mimetype,
                )

            except Exception as e:
                abort(500, description=str(e))

        @self.app.route("/download/<path:path>")
        def download(path):
            try:
                full_file_path = self.__get_and_verify_path(path)

                if os.path.isdir(full_file_path):
                    abort(400, description="Cannot download a directory")

                return send_file(full_file_path, as_attachment=True)

            except Exception as e:
                abort(500, description=str(e))

    def _get_file_size(self, file_path):
        """Get human readable file size"""
        try:
            size = os.path.getsize(file_path)
            for unit in ["B", "KB", "MB", "GB"]:
                if size < 1024.0:
                    return f"{size:.1f} {unit}"
                size /= 1024.0
            return f"{size:.1f} TB"
        except (OSError, IOError):
            return "Unknown"

    def _get_mimetype(self, file_path):
        generic_mimetypes = frozenset(("application/octet-stream", None))

        mime, encoding = mimetypes.guess_type(file_path)
        if mime in generic_mimetypes:
            return None
        return "%s%s%s" % (mime or "application/octet-stream", "; " if encoding else "", encoding or "")

    def _get_modified(self, file_path):
        try:
            dt = datetime.fromtimestamp(os.stat(file_path).st_mtime)
            return dt.strftime("%Y.%m.%d %H:%M:%S")
        except OSError:
            return None

    def run(self, debug, host, port):
        """
        Run the Flask application

        Args:
            debug (bool): Enable debug mode
            host (str): Host to bind to
            port (int): Port to bind to
        """
        print(f"Starting File Browser for directory: {self.directory}")
        self.app.run(debug=debug, host=host, port=port)

    def get_app(self):
        """Get the Flask app instance for external use (e.g., with gunicorn)"""
        return self.app

    def __get_and_verify_path(self, path):
        if os.path.isabs(path):
            full_path = path
        else:
            full_path = os.path.join(self.directory, path)

        full_path = os.path.abspath(full_path)
        if not (full_path == self.directory or full_path.startswith(self.directory + os.sep)):
            abort(403)

        if not os.path.exists(full_path):
            return render_template_string(NO_DATA_TEMPLATE, parent_path=os.path.dirname(path))

        return full_path


class FileItem:
    """
    Represents a file or directory in the file browser
    """

    def __init__(self, name: str, path: str, is_dir: bool, type: str, modified, size=None):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.size = size
        self.type = type
        self.modified = modified


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Please provide a directory path as an argument")
        sys.exit(1)
    app = FileBrowserApp(sys.argv[1])
    app.run(debug=False, host="0.0.0.0", port=8080)  # nosec
