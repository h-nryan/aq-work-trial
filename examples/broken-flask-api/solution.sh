#!/bin/bash

# Fix the broken Python Flask service by fixing syntax errors and installing dependencies

# First, fix the requirements.txt (add missing Flask dependency)
cat > requirements.txt << 'EOF'
Flask==2.3.3
requests==2.31.0
EOF

# Fix the users.json syntax errors (add missing comma and closing bracket)
cat > data/users.json << 'EOF'
[
  {
    "id": 1,
    "name": "John Doe",
    "email": "john@example.com",
    "role": "admin"
  },
  {
    "id": 2,
    "name": "Jane Smith",
    "email": "jane@example.com",
    "role": "user"
  },
  {
    "id": 3,
    "name": "Bob Johnson",
    "email": "bob@example.com",
    "role": "user"
  },
  {
    "id": 4,
    "name": "Alice Brown",
    "email": "alice@example.com",
    "role": "moderator"
  }
]
EOF

# Fix the app.py syntax errors and logic issues
cat > app.py << 'EOF'
from flask import Flask, jsonify
import json
import os

app = Flask(__name__)

# Load user data
with open('./data/users.json', 'r') as file:
    users_data = json.load(file)

@app.route('/users', methods=['GET'])
def get_users():
    return jsonify(users_data)

@app.route('/users/<user_id>', methods=['GET'])
def get_user(user_id):
    # Fix: convert user_id to int for comparison
    try:
        user_id_int = int(user_id)
        user = next((u for u in users_data if u['id'] == user_id_int), None)

        if user:
            return jsonify(user)
        else:
            return jsonify({'error': 'User not found'}), 404
    except ValueError:
        return jsonify({'error': 'Invalid user ID'}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=True)
EOF

# Install the required dependencies
pip3 install --break-system-packages -r requirements.txt

# Start the Flask server in the background
python3 app.py &

# Wait for the server to start up properly
sleep 2

# The server should now be running and accessible on port 3000