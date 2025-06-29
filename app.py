import eventlet
eventlet.monkey_patch()
from flask import Flask, request, jsonify
from flask import send_from_directory
from flask_socketio import SocketIO
from flask_cors import CORS
import pandas as pd
import os
from test_manager import TestManager
from io import BytesIO
from openpyxl import load_workbook

app = Flask(__name__)
app.json.sort_keys = False
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")  # Enable WebSockets

test_manager = TestManager(socketio)
SCRIPTS_DIR = "test_scripts"

# Serve images out of a local "images/" directory at /images/<filename>
@app.route("/images/<path:filename>")
def serve_image(filename):
    # the "images" folder is assumed to be sibling to this file (app.py)
    return send_from_directory("images", filename)

@app.route("/scripts", methods=["GET"])
def list_scripts():
    scripts = [f.replace(".py", "") for f in os.listdir(SCRIPTS_DIR) if f.endswith(".py")]
    return jsonify({"scripts": scripts})

@app.route("/script_tests", methods=["POST"])
def get_tests_for_script():
    data = request.json
    script_name = data.get("script")
    if not script_name:
        return jsonify({"error": "Script name is required", "tests": {}}), 400
    available_tests = test_manager.get_tests(script_name)
    max_units = test_manager.get_max_unit_support(script_name)
    return jsonify({
        "tests": available_tests,
        "multiUnitSupportedNumber": max_units
    })

@app.route("/start", methods=["POST"])
def start_test():
    data = request.json
    script_name = data.get("script")
    selected_tests = data.get("tests", [])
    details = data.get("details", {})
    selected_units = data.get("selectedUnitNumbers", [])
    if test_manager.is_running():
        return jsonify({"status": "error", "message": "A test is already running."}), 400
    socketio.start_background_task(
        test_manager.run_tests,
        script_name,
        selected_tests,
        details,
        selected_units,
    )
    return jsonify({"status": "success", "message": "Test started."})

@app.route("/stop", methods=["POST"])
def stop_test():
    test_manager.stop_test()
    return jsonify({"status": "success", "message": "Test stopped."})


@app.route("/results/upload", methods=["POST"])
def upload_results_file():
    # Expect a multipart/form-data with one file field named 'file'
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    raw = request.files["file"].read()
    try:
        # Load every sheet into a dict of DataFrames
        df_map = pd.read_excel(BytesIO(raw), sheet_name=None)
        wb = load_workbook(filename=BytesIO(raw), data_only=True)
        # Delegate parsing to TestManager
        metadata, results = test_manager.parse_results(df_map, wb)
        return jsonify({'metadata': metadata, 'results': results}), 200
    except Exception as e:
        print(e)
        return jsonify({'error': str(e)}), 500


@socketio.on("connect")
def handle_connect():
    print("A client connected:", request.sid)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)