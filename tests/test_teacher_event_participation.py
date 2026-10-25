from datetime import datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import TeacherEventParticipation
from app.models import (
    User, Student, Teacher, Venue, Event, Registration,
    TeacherEventParticipation,
    TeacherEventParticipation,
    TeacherEventParticipation,
)
from app.routes.events import event_is_full


@pytest.fixture()
def app():
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "teacher-event-tests-secret",
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


def make_teacher(verified=True):
    user = make_user("teacher@example.test", "teacher")
    teacher = Teacher(
        faculty_id="FAC-001",
        official_email="faculty@example.test",
        user_id=user.id,
        id_verified=verified,
    )
    db.session.add(teacher)
    db.session.flush()
    return user, teacher


def make_event(host_user, *, status="published", capacity=10):
    venue = Venue(
        name="Test Hall",
        location="Campus",
        capacity=100,
        is_active=True,
        is_event_venue=True,
    )
    db.session.add(venue)
    db.session.flush()

    start = datetime.utcnow() + timedelta(days=2)
    event = Event(
        event_code="TEST-EVENT-001",
        title="Test Campus Event",
        description="Test event",
        event_type="general",
        venue_id=venue.id,
        host_user_id=host_user.id,
        start_time=start,
        end_time=start + timedelta(hours=2),
        max_participants=capacity,
        status=status,
        is_public=True,
    )
    db.session.add(event)
    db.session.commit()
    return event


def login_as(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def post_action(client, event_id, action):
    return client.post(
        "/academic/teacher/events",
        data={"event_id": str(event_id), "action": action},
        follow_redirects=False,
    )


def test_verified_teacher_can_view_events_and_register(client, app):
    with app.app_context():
        user, teacher = make_teacher()
        event = make_event(user)
        user_id, event_id, teacher_id = user.id, event.id, teacher.id

    login_as(client, user_id)
    page = client.get("/academic/teacher/events")
    assert page.status_code == 200
    assert b"Test Campus Event" in page.data

    response = post_action(client, event_id, "register")
    assert response.status_code == 302

    with app.app_context():
        record = TeacherEventParticipation.query.filter_by(
            event_id=event_id, teacher_id=teacher_id
        ).first()
        assert record is not None
        assert record.status == "registered"


def test_duplicate_registration_does_not_create_another_record(client, app):
    with app.app_context():
        user, teacher = make_teacher()
        event = make_event(user)
        user_id, event_id, teacher_id = user.id, event.id, teacher.id

    login_as(client, user_id)
    post_action(client, event_id, "register")
    post_action(client, event_id, "register")

    with app.app_context():
        assert TeacherEventParticipation.query.filter_by(
            event_id=event_id, teacher_id=teacher_id,
            status="registered",
        ).count() == 1


def test_teacher_can_withdraw_and_re_register(client, app):
    with app.app_context():
        user, teacher = make_teacher()
        event = make_event(user)
        user_id, event_id, teacher_id = user.id, event.id, teacher.id

    login_as(client, user_id)
    post_action(client, event_id, "register")
    post_action(client, event_id, "withdraw")

    with app.app_context():
        record = TeacherEventParticipation.query.filter_by(
            event_id=event_id, teacher_id=teacher_id
        ).first()
        assert record.status == "withdrawn"

    post_action(client, event_id, "register")
    with app.app_context():
        record = TeacherEventParticipation.query.filter_by(
            event_id=event_id, teacher_id=teacher_id
        ).first()
        assert record.status == "registered"


def test_unverified_teacher_is_forbidden(client, app):
    with app.app_context():
        user, _ = make_teacher(verified=False)
        event = make_event(user)
        user_id, event_id = user.id, event.id

    login_as(client, user_id)
    assert client.get("/academic/teacher/events").status_code == 403
    assert post_action(client, event_id, "register").status_code == 403

    with app.app_context():
        assert TeacherEventParticipation.query.filter_by(
            event_id=event_id
        ).count() == 0


def test_teacher_cannot_register_for_unpublished_event(client, app):
    with app.app_context():
        user, teacher = make_teacher()
        event = make_event(user, status="draft")
        user_id, event_id, teacher_id = user.id, event.id, teacher.id

    login_as(client, user_id)
    response = post_action(client, event_id, "register")
    assert response.status_code == 302

    with app.app_context():
        assert TeacherEventParticipation.query.filter_by(
            event_id=event_id
        ).first() is None


def test_teacher_registration_respects_existing_student_capacity(client, app):
    with app.app_context():
        user, teacher = make_teacher()
        event = make_event(user, capacity=1)

        student_user = make_user("student@example.test", "student")
        student = Student(
            user_id=student_user.id,
            campus_id="CAMP-001",
            college_id="COLL-001",
            id_verified=False,
            campus_id_active=True,
        )
        db.session.add(student)
        db.session.flush()
        db.session.add(Registration(
            event_id=event.id,
            student_id=student.id,
            status="registered",
        ))
        db.session.commit()
        user_id, event_id, teacher_id = user.id, event.id, teacher.id

    login_as(client, user_id)
    post_action(client, event_id, "register")

    with app.app_context():
        assert TeacherEventParticipation.query.filter_by(
            event_id=event_id
        ).first() is None


def test_shared_capacity_counts_students_and_teachers(app):
    with app.app_context():
        user, teacher = make_teacher()
        event = make_event(user, capacity=2)

        student_user = make_user("student@example.test", "student")
        student = Student(
            user_id=student_user.id,
            campus_id="CAMP-002",
            college_id="COLL-002",
            id_verified=False,
            campus_id_active=True,
        )
        db.session.add(student)
        db.session.flush()

        db.session.add(Registration(
            event_id=event.id,
            student_id=student.id,
            status="registered",
        ))
        db.session.add(TeacherEventParticipation(
            event_id=event.id,
            teacher_id=teacher.id,
            status="registered",
        ))
        db.session.commit()

        assert event_is_full(event) is True


