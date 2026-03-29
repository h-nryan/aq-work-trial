from flask import Flask, jsonify
import json
import os

app = Flask(__name__)

# Load user data with syntax error
with open('./data/users.json', 'r') as file:
    users_data = json.load(file)

@app.route('/users', methods=['GET'])
def get_users():
    return jsonify(users_data)

@app.route('/users/<user_id>', methods=['GET'])
def get_user(user_id):
    # Bug: comparing string to integer
    user = next((u for u in users_data if u['id'] == user_id), None)

    if user:
        return jsonify(user)
    else:
        return jsonify({'error': 'User not found'}), 404

if __name__ == '__main__'
    # Missing colon - syntax error
    app.run(host='0.0.0.0', port=3000, debug=True)