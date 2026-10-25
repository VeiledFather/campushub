import os
from google import genai
import json
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import current_app, Blueprint, abort, jsonify, request, render_template, flash, redirect, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.models import Event, Venue

evai_bp = Blueprint("evai", __name__, url_prefix="/evai")

IST = ZoneInfo("Asia/Kolkata")
ADMIN_ROLES = {"admin", "super_admin", "developer"}
PLANNER_ROLES = ADMIN_ROLES | {"organizer", "teacher"}


def planner_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role not in PLANNER_ROLES:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def parse_ist(value):
    if not value:
        raise ValueError("Both start and end times are required.")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


@evai_bp.post("/clashes")
@planner_required
def clashes():
    try:
        venue_id = int(request.form.get("venue_id", ""))
        start = parse_ist(request.form.get("start_time", ""))
        end = parse_ist(request.form.get("end_time", ""))
    except (ValueError, TypeError, OverflowError):
        return jsonify({
            "ok": False,
            "error": "Choose a venue and enter valid start and end times."
        }), 400

    if end <= start:
        return jsonify({
            "ok": False,
            "error": "The end time must be later than the start time."
        }), 400

    venue = db.session.get(Venue, venue_id)
    if venue is None or not venue.is_active or not venue.is_event_venue:
        return jsonify({
            "ok": False,
            "error": "Choose an active event venue."
        }), 400

    # Find events overlapping the proposed time. Ignore cancelled events.
    overlapping = Event.query.filter(
        Event.status != "cancelled",
        Event.start_time < end,
        Event.end_time > start,
        or_(
            Event.venue_id == venue_id,
            Event.host_user_id == current_user.id,
        ),
    ).order_by(Event.start_time.asc()).all()

    conflicts = []
    for event in overlapping:
        same_venue = event.venue_id == venue_id
        same_host = event.host_user_id == current_user.id

        kinds = []
        if same_venue:
            kinds.append("venue")
        if same_host:
            kinds.append("organizer")

        conflicts.append({
            "title": event.title,
            "start_time": event.start_time.isoformat() if event.start_time else None,
            "end_time": event.end_time.isoformat() if event.end_time else None,
            "venue": event.venue.name if event.venue else "Unknown venue",
            "status": event.status,
            "conflicts": kinds,
        })

    return jsonify({
        "ok": True,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "message": (
            "Schedule clashes found. Review them before creating this event."
            if conflicts else
            "No venue or organizer schedule clashes found."
        ),
    })


@evai_bp.post("/plan")
@planner_required
def plan_event():
    """Generate event-planning suggestions using Gemini."""
    payload = request.get_json(silent=True) or {}

    title = str(payload.get("title", "")).strip()
    event_type = str(payload.get("event_type", "general")).strip()
    audience = str(payload.get("audience", "college students")).strip()
    goals = str(payload.get("goals", "")).strip()
    budget = str(payload.get("budget", "not specified")).strip()
    duration = str(payload.get("duration", "not specified")).strip()

    if not title:
        return jsonify({
            "ok": False,
            "error": "Enter an event idea or title first."
        }), 400

    if len(title) > 200 or len(event_type) > 80 or len(audience) > 200:
        return jsonify({
            "ok": False,
            "error": "One or more fields exceed the allowed length."
        }), 400

    if len(goals) > 2000 or len(budget) > 100 or len(duration) > 100:
        return jsonify({
            "ok": False,
            "error": "Please shorten the planning details and try again."
        }), 400

    api_key = current_app.config.get("GEMINI_API_KEY", "")
    model = os.environ.get("EVAI_MODEL") or current_app.config.get("EVAI_MODEL") or "gemini-3.5-flash-lite"

    if not api_key:
        return jsonify({
            "ok": False,
            "error": "EvAi AI planning is not configured yet. Add GEMINI_API_KEY to your local .env file."
        }), 503

    prompt = f"""
You are EvAi, the campus event-planning assistant for CampusHub.
Create a practical, realistic plan for this proposed college event.

Event idea: {title}
Event type: {event_type}
Intended audience: {audience}
Goals and special requirements: {goals or "Not specified"}
Budget: {budget}
Duration: {duration}

Return ONLY a valid JSON object with these keys:
"title" (string),
"description" (string, suitable for an event listing),
"objectives" (array of 3 to 5 strings),
"schedule" (array of objects with "time" and "activity" strings),
"equipment_requirements" (array of strings),
"food_requirements" (array of strings; mention when food may be unnecessary),
"estimated_attendance" (integer),
"planning_checklist" (array of 5 to 8 strings),
"risks" (array of objects with "risk" and "mitigation" strings).

Be clear when estimates are assumptions. Do not invent venue availability,
confirmed bookings, approvals, or actual prices. Do not claim the event
has been created, scheduled, approved, or published.
"""

    try:
        client = genai.Client(
            api_key=api_key,
            http_options={"timeout": 30000},
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"max_output_tokens": 4096},
        )
        text = (response.text or "").strip()

        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3].strip()
            if text.startswith("json"):
                text = text[4:].strip()

        plan = json.loads(text)
        required_keys = {
            "title", "description", "objectives", "schedule",
            "equipment_requirements", "food_requirements",
            "estimated_attendance", "planning_checklist", "risks",
        }
        if not isinstance(plan, dict) or not required_keys.issubset(plan):
            raise ValueError("The response did not contain the required plan fields.")

        return jsonify({"ok": True, "plan": plan})

    except Exception:
        current_app.logger.exception("EvAi event planning request failed")
        return jsonify({
            "ok": False,
            "error": "EvAi could not generate a plan right now. Check the API configuration and try again."
        }), 502


@evai_bp.get("/")
@planner_required
def planner_page():
    venues = Venue.query.filter_by(
        is_active=True,
        is_event_venue=True,
    ).order_by(Venue.name.asc()).all()

    return render_template("evai/planner.html", venues=venues)


@evai_bp.get("/saved")
@planner_required
def saved_plans():
    from app.models import EvAiSavedPlan

    plans = (
        EvAiSavedPlan.query
        .filter_by(user_id=current_user.id)
        .order_by(EvAiSavedPlan.updated_at.desc())
        .all()
    )

    return render_template("evai/saved.html", plans=plans)


@evai_bp.post("/saved")
@planner_required
def save_plan():
    from app.models import EvAiSavedPlan

    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    plan = payload.get("plan")

    if not name or len(name) > 200:
        return jsonify({
            "ok": False,
            "error": "Enter a plan name of up to 200 characters."
        }), 400

    required_keys = {
        "title", "description", "objectives", "schedule",
        "equipment_requirements", "food_requirements",
        "estimated_attendance", "planning_checklist", "risks",
    }

    if not isinstance(plan, dict) or not required_keys.issubset(plan):
        return jsonify({
            "ok": False,
            "error": "The supplied plan is incomplete or invalid."
        }), 400

    try:
        plan_json = json.dumps(plan, ensure_ascii=False)
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "error": "The plan could not be saved."
        }), 400

    if len(plan_json) > 100_000:
        return jsonify({
            "ok": False,
            "error": "This plan is too large to save."
        }), 400

    saved = EvAiSavedPlan(
        name=name,
        plan_json=plan_json,
        user_id=current_user.id,
    )
    db.session.add(saved)
    db.session.commit()

    return jsonify({
        "ok": True,
        "id": saved.id,
        "message": "Plan saved successfully."
    }), 201


@evai_bp.post("/saved/<int:plan_id>/delete")
@planner_required
def delete_saved_plan(plan_id):
    from app.models import EvAiSavedPlan

    saved = EvAiSavedPlan.query.filter_by(
        id=plan_id,
        user_id=current_user.id,
    ).first_or_404()

    db.session.delete(saved)
    db.session.commit()

    flash("Saved EvAi plan deleted.", "success")
    return redirect(url_for("evai.saved_plans"))


# CAMPUSHUB_EVAI_ASSISTANT_ENDPOINT
@evai_bp.route("/assistant/chat", methods=["POST"])
def assistant_chat():
    import json
    import os
    import urllib.error
    import urllib.request
    import socket as _evai_socket
    import http.client as _evai_http_client
    import ssl as _evai_ssl
    from datetime import datetime

    # EVAI_IPV4_GEMINI_FIX: avoid IPv6 timeouts on this network.
    class _EvAiIPv4Connection(_evai_http_client.HTTPSConnection):
        def __init__(self, host, **kwargs):
            kwargs.setdefault("context", _evai_ssl.create_default_context())
            super().__init__(host, **kwargs)

        def connect(self):
            addresses = _evai_socket.getaddrinfo(
                self.host,
                self.port or 443,
                _evai_socket.AF_INET,
                _evai_socket.SOCK_STREAM,
            )
            last_error = None

            for family, socktype, proto, _, address in addresses:
                sock = _evai_socket.socket(family, socktype, proto)
                try:
                    sock.settimeout(self.timeout)
                    sock.connect(address)
                    self.sock = self._context.wrap_socket(
                        sock, server_hostname=self.host
                    )
                    return
                except OSError as exc:
                    last_error = exc
                    sock.close()

            raise last_error or OSError("Gemini IPv4 connection failed")

    class _EvAiIPv4HTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(_EvAiIPv4Connection, req)

    from flask import current_app, jsonify, request
    from flask_login import current_user
    from app.models import Event, Venue, Registration, Review

    if not current_user.is_authenticated:
        return jsonify({"error": "Please log in to use EvAi."}), 401

    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip()

    if not message:
        return jsonify({"error": "Type a message first."}), 400
    if len(message) > 1200:
        return jsonify({"error": "Please keep messages under 1,200 characters."}), 400

    role = (getattr(current_user, "role", "student") or "student").lower()
    lower = message.lower()

    # Only public events are included in the campus-wide event context.
    public_events = (
        Event.query
        .filter(
            Event.is_public.is_(True),
            Event.status.in_(["published", "ongoing"]),
        )
        .order_by(Event.start_time.asc())
        .limit(30)
        .all()
    )

    active_venues = Venue.query.filter_by(
        is_active=True, is_event_venue=True
    ).order_by(Venue.name.asc()).limit(40).all()

    now = datetime.utcnow()
    upcoming = [e for e in public_events if e.start_time >= now]
    event_lines = []
    for event in public_events:
        venue_name = event.venue.name if event.venue else "Venue not listed"
        event_lines.append(
            f"- {event.title} | {event.event_type} | "
            f"{event.start_time.strftime('%d %b %Y, %I:%M %p')} to "
            f"{event.end_time.strftime('%d %b %Y, %I:%M %p')} | "
            f"{venue_name} | status: {event.status} | event ID: {event.id}"
        )

    venue_lines = [
        f"- {v.name} | {v.location or 'Location not listed'} | "
        f"capacity {v.capacity}"
        for v in active_venues
    ]

    # Provide only aggregate personal information, never other users' records.
    personal_context = ""
    try:
        student = getattr(current_user, "student", None)
        if student:
            own_registrations = Registration.query.filter_by(
                student_id=student.id
            ).count()
            personal_context += (
                f"\nThe current user's total event registrations: "
                f"{own_registrations}."
            )
    except Exception:
        pass

    context = (
        f"Current user role: {role}.\n"
        f"Public published/ongoing events: {len(public_events)}.\n"
        f"Upcoming public events: {len(upcoming)}.\n"
        "Public event data:\n"
        + ("\n".join(event_lines) or "- No public events are currently listed.")
        + "\nApproved active event venues:\n"
        + ("\n".join(venue_lines) or "- No active event venues are listed.")
        + "\nUseful CampusHub pages: /events, /hall-of-fame, /evai/."
        + personal_context
    )

    # Handle common campus questions deterministically, so these work even
    # when an AI API key is unavailable.
    if any(word in lower for word in ("hall of fame", "leaderboard", "top rated")):
        answer = (
            "You can explore CampusHub's Hall of Fame and rankings here: "
            "/hall-of-fame. Rankings depend on the site's available event "
            "and review data."
        )
        return jsonify({"answer": answer, "links": [
            {"label": "Open Hall of Fame", "url": "/hall-of-fame"}
        ]})

    if any(word in lower for word in ("plan an event", "event planner", "make an event plan", "plan my event")):
        return jsonify({
            "answer": (
                "For a full event plan, use the existing EvAi Event Planner. "
                "It helps create a plan and check venue and organizer schedule "
                "clashes before you finalize it."
            ),
            "links": [{"label": "Open EvAi Event Planner", "url": "/evai/"}],
        })

    if any(word in lower for word in ("venue", "venues", "auditorium", "location")):
        answer = "Here are the active venues currently available for events:\n"
        answer += "\n".join(venue_lines) if venue_lines else "No active venues are listed."
        return jsonify({"answer": answer, "links": [
            {"label": "Browse events", "url": "/events"}
        ]})

    if any(word in lower for word in ("upcoming event", "upcoming events", "what events", "list events", "show events", "events happening")):
        lines = []
        for event in upcoming[:12]:
            venue_name = event.venue.name if event.venue else "Venue not listed"
            lines.append(
                f"• {event.title} — "
                f"{event.start_time.strftime('%d %b %Y, %I:%M %p')} "
                f"at {venue_name} (event ID {event.id})"
            )
        answer = "\n".join(lines) if lines else (
            "There are no upcoming public events listed right now."
        )
        return jsonify({"answer": answer, "links": [
            {"label": "Browse events", "url": "/events"}
        ]})

    # Use Gemini when configured, grounded in current public database data.
    api_key = (
        current_app.config.get("GEMINI_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    )
    if api_key:
        prompt = (
            "You are EvAi, the helpful CampusHub website assistant. "
            "Answer the user's question clearly and conversationally. "
            "Use the supplied context as the source of truth for live campus "
            "data. Never invent events, venues, dates, capacities, features, "
            "or policies. If the context lacks an answer, say so. "
            "Do not reveal private records, secrets, credentials, or other "
            "users' personal information. The user role may affect what "
            "actions they can perform. For event planning, direct users to "
            "the existing planner at /evai/. Use plain text, with short lists "
            "when helpful.\n\n"
            f"CURRENT CAMPUSHUB CONTEXT:\n{context}\n\n"
            f"USER QUESTION:\n{message}"
        )
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 650,
            },
        }).encode("utf-8")
        model = (
            os.environ.get("EVAI_MODEL")
            or current_app.config.get("EVAI_MODEL")
            or "gemini-3.5-flash-lite"
        )
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + model
            + ":generateContent?key="
            + api_key
        )
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.build_opener(_EvAiIPv4HTTPSHandler()).open(req, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
            answer = result["candidates"][0]["content"]["parts"][0]["text"]
            return jsonify({"answer": answer.strip()})
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError):
            current_app.logger.exception("EvAi assistant model request failed")

    answer = (
        "I'm EvAi, your CampusHub assistant. I can help you find campus "
        "events and venues, explain site features, and direct you to the "
        "right page. For event planning and clash detection, open the "
        "existing planner at /evai/.\n\n"
        f"There are currently {len(upcoming)} upcoming public events and "
        f"{len(active_venues)} active event venues listed."
    )
    return jsonify({"answer": answer, "links": [
        {"label": "Browse events", "url": "/events"},
        {"label": "Hall of Fame", "url": "/hall-of-fame"},
        {"label": "Event Planner", "url": "/evai/"},
    ]})
