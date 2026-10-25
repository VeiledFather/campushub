from flask import g
import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import User, Student, Teacher, Department, Batch


@pytest.fixture()
def app():
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "teacher-tests-only-secret",
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


def make_batch():
    department = Department(name="Science", code="SCI")
    db.session.add(department)
    db.session.flush()

    batch = Batch(
        batch_code="SCI-2026-A",
        name="Batch A",
        academic_year="2026-2027",
        department_id=department.id,
        home_room="Room 1",
        is_active=True,
    )
    db.session.add(batch)
    db.session.flush()
    return batch


def make_teacher(*, verified=True, assigned_batch=True):
    user = make_user("teacher@example.test", "teacher")
    batch = make_batch() if assigned_batch else None
    teacher = Teacher(
        faculty_id="FAC-001",
        official_email="faculty@example.test",
        user_id=user.id,
        homeroom_batch_id=batch.id if batch else None,
        id_verified=verified,
    )
    db.session.add(teacher)
    db.session.commit()
    return user.id, batch.id if batch else None


def login_as(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True

    # Tests may share an application context, where Flask-Login caches
    # current_user on g. Clear that cache after switching identities.
    g.pop("_login_user", None)


def enrollment_form(**overrides):
    data = {
        "full_name": "New Student",
        "email": "new.student@example.test",
        "campus_id": "CAMP-NEW-001",
        "college_id": "COLL-NEW-001",
    }
    data.update(overrides)
    return data


def add_existing_student():
    user = make_user("existing.student@example.test", "student")
    student = Student(
        user_id=user.id,
        campus_id="CAMP-EXISTING",
        college_id="COLL-EXISTING",
        id_verified=False,
        campus_id_active=True,
    )
    db.session.add(student)
    db.session.commit()
    return user.id


def test_non_teacher_cannot_access_teacher_workspace(client, app):
    with app.app_context():
        user = make_user("student@example.test", "student")
        db.session.commit()
        user_id = user.id

    login_as(client, user_id)
    response = client.get("/academic/teacher")
    assert response.status_code == 403


def test_unverified_teacher_cannot_access_workspace_or_enroll(client, app):
    with app.app_context():
        teacher_id, batch_id = make_teacher(verified=False)

    login_as(client, teacher_id)
    response = client.post(
        "/academic/teacher",
        data=enrollment_form(),
    )
    assert response.status_code == 403

    with app.app_context():
        assert User.query.filter_by(
            email="new.student@example.test"
        ).first() is None


def test_teacher_without_assigned_batch_cannot_enroll(client, app):
    with app.app_context():
        teacher_id, _ = make_teacher(assigned_batch=False)

    login_as(client, teacher_id)
    response = client.post(
        "/academic/teacher",
        data=enrollment_form(),
    )
    assert response.status_code == 200

    with app.app_context():
        assert User.query.filter_by(
            email="new.student@example.test"
        ).first() is None


def test_verified_teacher_can_enroll_student_into_assigned_batch(
    client, app, monkeypatch
):
    monkeypatch.setattr(
        "app.routes.academic._send_teacher_enrolled_student_setup_email",
        lambda user: True,
    )

    with app.app_context():
        teacher_id, batch_id = make_teacher(verified=True)

    login_as(client, teacher_id)
    response = client.post(
        "/academic/teacher",
        data=enrollment_form(),
    )

    assert response.status_code == 302
    assert "/academic/teacher" in response.headers["Location"]

    with app.app_context():
        user = User.query.filter_by(
            email="new.student@example.test"
        ).first()
        assert user is not None
        assert user.role == "student"
        assert user.is_active is True
        assert user.is_suspended is False

        student = Student.query.filter_by(user_id=user.id).first()
        assert student is not None
        assert student.batch_id == batch_id
        assert student.campus_id == "CAMP-NEW-001"
        assert student.college_id == "COLL-NEW-001"
        assert student.id_verified is False
        assert student.campus_id_active is True


@pytest.mark.parametrize(
    ("campus_id", "college_id"),
    [
        ("CAMP-EXISTING", "COLL-UNIQUE"),
        ("CAMP-UNIQUE", "COLL-EXISTING"),
    ],
)
def test_duplicate_campus_or_college_id_is_rejected(
    client, app, campus_id, college_id
):
    with app.app_context():
        teacher_id, _ = make_teacher()
        add_existing_student()

    login_as(client, teacher_id)
    response = client.post(
        "/academic/teacher",
        data=enrollment_form(
            campus_id=campus_id,
            college_id=college_id,
        ),
    )

    assert response.status_code == 200

    with app.app_context():
        assert User.query.filter_by(
            email="new.student@example.test"
        ).first() is None
        assert Student.query.count() == 1


def test_duplicate_email_is_rejected(client, app):
    with app.app_context():
        teacher_id, _ = make_teacher()
        make_user("new.student@example.test", "student")
        db.session.commit()

    login_as(client, teacher_id)
    response = client.post(
        "/academic/teacher",
        data=enrollment_form(),
    )

    assert response.status_code == 200

    with app.app_context():
        assert Student.query.count() == 0
        assert User.query.filter_by(
            email="new.student@example.test"
        ).count() == 1
