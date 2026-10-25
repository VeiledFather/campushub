from datetime import datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import User, Venue, Event


@pytest.fixture()
def app():
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "analytics-tests-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "WTF_CSRF_ENABLED": False,
        "SERVER_NAME": "localhost",
    })
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def make_user(email, role):
    user = User(
        full_name=f"Test {role.title()}",
        email=email,
        password_hash=generate_password_hash("placeholder-password"),
        role=role,
        is_active=True,
        is_suspended=False,
    )
    db.session.add(user)
    db.session.flush()
    return user


def make_event(host, code, title):
    venue = Venue(
        name=f"Venue {code}",
        location="Campus",
        capacity=100,
        is_active=True,
        is_event_venue=True,
    )
    db.session.add(venue)
    db.session.flush()

    start = datetime.utcnow() + timedelta(days=2)
    event = Event(
        event_code=code,
        title=title,
        description="Analytics test event",
        event_type="general",
        venue_id=venue.id,
        host_user_id=host.id,
        start_time=start,
        end_time=start + timedelta(hours=2),
        max_participants=50,
        status="published",
        is_public=True,
    )
    db.session.add(event)
    db.session.commit()
    return event


def login_as(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_organizer_sees_only_their_own_events(client, app):
    with app.app_context():
        organizer_a = make_user("organizer-a@example.test", "organizer")
        organizer_b = make_user("organizer-b@example.test", "organizer")
        make_event(organizer_a, "ANALYTICS-A", "Organizer A Private Event")
        make_event(organizer_b, "ANALYTICS-B", "Organizer B Private Event")
        organizer_a_id = organizer_a.id

    login_as(client, organizer_a_id)
    response = client.get("/analytics")

    assert response.status_code == 200
    assert b"Organizer A Private Event" in response.data
    assert b"Organizer B Private Event" not in response.data
    assert b"Event Analytics" in response.data


def test_admin_sees_platform_wide_events(client, app):
    with app.app_context():
        organizer_a = make_user("admin-test-a@example.test", "organizer")
        organizer_b = make_user("admin-test-b@example.test", "organizer")
        admin = make_user("analytics-admin@example.test", "admin")
        make_event(organizer_a, "ANALYTICS-ADMIN-A", "First Platform Event")
        make_event(organizer_b, "ANALYTICS-ADMIN-B", "Second Platform Event")
        admin_id = admin.id

    login_as(client, admin_id)
    response = client.get("/analytics")

    assert response.status_code == 200
    assert b"First Platform Event" in response.data
    assert b"Second Platform Event" in response.data


def test_teacher_can_see_their_own_hosted_events(client, app):
    with app.app_context():
        teacher = make_user("analytics-teacher@example.test", "teacher")
        other_organizer = make_user("analytics-other@example.test", "organizer")
        make_event(teacher, "ANALYTICS-TEACHER", "Teacher Hosted Event")
        make_event(other_organizer, "ANALYTICS-OTHER", "Other Host Event")
        teacher_id = teacher.id

    login_as(client, teacher_id)
    response = client.get("/analytics")

    assert response.status_code == 200
    assert b"Teacher Hosted Event" in response.data
    assert b"Other Host Event" not in response.data


@pytest.mark.parametrize("role", ["student", "volunteer"])
def test_non_manager_roles_cannot_access_analytics(client, app, role):
    with app.app_context():
        user = make_user(f"{role}@example.test", role)
        user_id = user.id

    login_as(client, user_id)
    response = client.get("/analytics")

    assert response.status_code == 403
