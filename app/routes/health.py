from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)

@health_bp.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "application": "CampusHub Official",
        "assistant": "EvAi",
    }), 200
