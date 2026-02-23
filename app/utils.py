import json
import os
from flask import current_app

def load_questions(filename):
    """Global helper to load questions from JSON files."""
    try:
        path = os.path.join(current_app.root_path, 'data', filename)
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"DEBUG ERROR: Could not load {filename}. Reason: {e}")
        return ["Q1 (Fallback)", "Q2 (Fallback)", "Q3 (Fallback)", "Q4 (Fallback)", "Q5 (Fallback)"]