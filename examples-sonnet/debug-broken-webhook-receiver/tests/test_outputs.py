import pytest
import requests
import hmac
import hashlib
import time
import json
import subprocess
import signal
import os
from threading import Thread

SECRET_KEY = b"my_webhook_secret"
BASE_URL = "http://localhost:8080"

server_process = None

def setup_module(module):
    """Start the webhook server before running tests."""
    global server_process
    server_process = subprocess.Popen(
        ['python3', '/app/webhook_receiver.py', '8080'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)

def teardown_module(module):
    """Stop the webhook server after tests."""
    global server_process
    if server_process:
        server_process.terminate()
        server_process.wait(timeout=5)

def create_signature(body):
    """Create HMAC signature for webhook body."""
    return hmac.new(SECRET_KEY, body, hashlib.sha256).hexdigest()

def send_webhook(payload, signature=None, timestamp=None, request_id=None):
    """Send a webhook request with proper headers."""
    body = json.dumps(payload).encode('utf-8')
    
    if signature is None:
        signature = create_signature(body)
    if timestamp is None:
        timestamp = str(int(time.time()))
    if request_id is None:
        request_id = f"req_{int(time.time() * 1000)}"
    
    headers = {
        'Content-Type': 'application/json',
        'X-Webhook-Signature': signature,
        'X-Webhook-Timestamp': timestamp,
        'X-Request-ID': request_id
    }
    
    return requests.post(f"{BASE_URL}/webhook", data=body, headers=headers)

def test_valid_webhook_accepted():
    """Test that a valid webhook with correct signature is accepted."""
    payload = {'event': 'user.created', 'data': {'user_id': 123}}
    response = send_webhook(payload)
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data['status'] == 'processed'
    assert data['event'] == 'user.created'

def test_invalid_signature_rejected():
    """Test that webhooks with invalid signatures are rejected."""
    payload = {'event': 'user.created', 'data': {'user_id': 123}}
    response = send_webhook(payload, signature='invalid_signature')
    
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"

def test_missing_signature_rejected():
    """Test that webhooks without signatures are rejected."""
    payload = {'event': 'user.created', 'data': {'user_id': 123}}
    response = send_webhook(payload, signature='')
    
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"

def test_old_timestamp_rejected():
    """Test that webhooks with old timestamps are rejected for replay protection."""
    payload = {'event': 'user.created', 'data': {'user_id': 123}}
    old_timestamp = str(int(time.time()) - 400)
    response = send_webhook(payload, timestamp=old_timestamp)
    
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"

def test_future_timestamp_rejected():
    """Test that webhooks with future timestamps are rejected."""
    payload = {'event': 'user.created', 'data': {'user_id': 123}}
    future_timestamp = str(int(time.time()) + 400)
    response = send_webhook(payload, timestamp=future_timestamp)
    
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"

def test_duplicate_request_id_rejected():
    """Test that duplicate request IDs are rejected for replay protection."""
    payload = {'event': 'user.created', 'data': {'user_id': 123}}
    request_id = f"unique_req_{int(time.time() * 1000)}"
    
    response1 = send_webhook(payload, request_id=request_id)
    assert response1.status_code == 200, "First request should succeed"
    
    time.sleep(0.1)
    response2 = send_webhook(payload, request_id=request_id)
    assert response2.status_code == 409, f"Expected 409 for duplicate, got {response2.status_code}"

def test_different_request_ids_accepted():
    """Test that different request IDs are processed independently."""
    payload = {'event': 'user.created', 'data': {'user_id': 123}}
    
    response1 = send_webhook(payload, request_id="req_1")
    assert response1.status_code == 200
    
    time.sleep(0.1)
    response2 = send_webhook(payload, request_id="req_2")
    assert response2.status_code == 200
