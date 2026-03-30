#!/bin/bash

# Install curl

# Install uv


# Check if we're in a valid working directory
if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    exit 1
fi

uv init
uv add pytest==8.4.1

# Create test server script
cat > /tmp/test_server.py << 'EOF'
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import base64
import sys

class TestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/test":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {"status": "ok", "method": "GET"}
            self.wfile.write(json.dumps(response).encode())
        elif self.path == "/headers":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            headers = dict(self.headers)
            self.wfile.write(json.dumps(headers).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = {
            "status": "ok",
            "method": "POST",
            "data": body,
            "headers": dict(self.headers)
        }
        self.wfile.write(json.dumps(response).encode())
    
    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = HTTPServer(('', port), TestHandler)
    server.serve_forever()
EOF

# Run pytest
uv run pytest $TEST_DIR/test_outputs.py -rA
