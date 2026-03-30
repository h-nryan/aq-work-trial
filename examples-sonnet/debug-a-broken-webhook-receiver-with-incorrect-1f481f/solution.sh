#!/bin/bash

# Solution: restore the working versions of all source files
cat > requirements.txt << 'SOLUTION_EOF'
# No runtime dependencies required
# The webhook_receiver.py script uses only Python standard library modules
# Test dependencies are handled by run-tests.sh using uv with pinned versions:
# - pytest==8.4.1
# - requests==2.31.0

SOLUTION_EOF

cat > webhook_receiver.py << 'SOLUTION_EOF'
#!/usr/bin/env python3
import hmac
import hashlib
import time
import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

SECRET_KEY = b"my_webhook_secret"
REPLAY_WINDOW = 300
processed_requests = set()

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/webhook":
            self.send_error(404)
            return
        
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        signature = self.headers.get('X-Webhook-Signature', '')
        timestamp = self.headers.get('X-Webhook-Timestamp', '')
        request_id = self.headers.get('X-Request-ID', '')
        
        if not self.verify_signature(body, signature):
            self.send_error(401, "Invalid signature")
            return
        
        if not self.check_timestamp(timestamp):
            self.send_error(401, "Request too old")
            return
        
        if not self.check_replay(request_id):
            self.send_error(409, "Duplicate request")
            return
        
        try:
            payload = json.loads(body.decode('utf-8'))
            result = self.process_webhook(payload)
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode('utf-8'))
        except Exception as e:
            self.send_error(500, str(e))
    
    def verify_signature(self, body, signature):
        if not signature:
            return False
        expected = hmac.new(SECRET_KEY, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    
    def check_timestamp(self, timestamp):
        if not timestamp:
            return False
        try:
            ts = int(timestamp)
            current = int(time.time())
            return abs(current - ts) <= REPLAY_WINDOW
        except ValueError:
            return False
    
    def check_replay(self, request_id):
        if not request_id:
            return False
        if request_id in processed_requests:
            return False
        processed_requests.add(request_id)
        return True
    
    def process_webhook(self, payload):
        event_type = payload.get('event', 'unknown')
        data = payload.get('data', {})
        return {
            'status': 'processed',
            'event': event_type,
            'received_at': int(time.time())
        }
    
    def log_message(self, format, *args):
        pass

def run_server(port=8080):
    server = HTTPServer(('', port), WebhookHandler)
    server.serve_forever()

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)

SOLUTION_EOF
