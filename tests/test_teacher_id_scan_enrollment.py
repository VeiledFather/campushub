from io import BytesIO

from app.extensions import db
from app.models import Student, StudentIDVerificationRequest, Teacher
from tests.test_teacher_workspace import (
    app, client, make_teacher, make_user, add_existing_student, login_as,
)

PNG = bytes([137, 80, 78, 71, 13, 10, 26, 10]) + bytes(32)


def setup_student_in_batch():
    _, batch_id = make_teacher()
    teacher = Teacher.query.filter_by(homeroom_batch_id=batch_id).first()
    assert teacher is not None, "Teacher profile was not created"
    teacher_user_id = teacher.user_id
    assert teacher.user.role == "teacher", (
        f"Expected teacher account, got role={teacher.user.role!r}, "
        f"user_id={teacher_user_id}"
    )

    student_user_id = add_existing_student()
    student = Student.query.filter_by(user_id=student_user_id).first()
    student.batch_id = batch_id
    db.session.commit()
    return teacher_user_id, batch_id, student_user_id


def submit_request(client):
    return client.post(
        "/academic/student/id-verification",
        data={
            "scanned_id": "CAMP-EXISTING",
            "batch_code": "SCI-2026-A",
            "card_image": (BytesIO(PNG), "student-card.png"),
        },
        content_type="multipart/form-data",
    )


def test_student_can_submit_card_for_teacher_review(client, app):
    with app.app_context():
        teacher_id, batch_id, student_user_id = setup_student_in_batch()
        student = Student.query.filter_by(user_id=student_user_id).first()
        student_id = student.id
        student_user = student.user

    login_as(client, student_user_id)
    response = submit_request(client)
    if response.status_code == 403:
        print("DEBUG 403: user session and teacher authorization need inspection")
        print("Response:", response.get_data(as_text=True)[:500])
    assert response.status_code == 302, f"Unexpected response {response.status_code}: {response.get_data(as_text=True)[:1500]}"

    with app.app_context():
        record = StudentIDVerificationRequest.query.filter_by(
            student_id=student_id, status="pending"
        ).first()
        assert record is not None
        assert record.batch_id == batch_id
        assert record.scanned_id == "CAMP-EXISTING"
        assert record.card_image_path.startswith("id_verification/")
        assert Student.query.get(student_id).id_verified is False



def test_assigned_teacher_can_approve_matching_id(client, app):
    with app.app_context():
        teacher_id, batch_id, student_user_id = setup_student_in_batch()
        student = Student.query.filter_by(user_id=student_user_id).first()
        student_id = student.id

    student_client = app.test_client()
    login_as(student_client, student_user_id)
    assert submit_request(student_client).status_code == 302

    with app.app_context():
        record = StudentIDVerificationRequest.query.filter_by(
            student_id=student_id, status="pending"
        ).first()
        request_id = record.id

    teacher_client = app.test_client()
    login_as(teacher_client, teacher_id)
    with teacher_client.session_transaction() as session:
        print("AUTH_CHECK session _user_id =", session.get("_user_id"))
    with teacher_client:
        teacher_response = teacher_client.get("/academic/teacher/id-verification")
        print("AUTH_CHECK teacher GET status =", teacher_response.status_code)
        print("AUTH_CHECK teacher GET trace is shown in pytest output above")
    response = teacher_client.post(
        "/academic/teacher/id-verification",
        data={"request_id": request_id, "action": "approve"},
    )
    if response.status_code == 403:
        print("DEBUG 403: user session and teacher authorization need inspection")
        print("Response:", response.get_data(as_text=True)[:500])
    assert response.status_code == 302, f"Unexpected response {response.status_code}: {response.get_data(as_text=True)[:1500]}"

    with app.app_context():
        record = db.session.get(StudentIDVerificationRequest, request_id)
        student = db.session.get(Student, student_id)
        assert record.status == "approved"
        assert record.reviewed_by_teacher_id is not None
        assert student.id_verified is True


def test_assigned_teacher_can_reject_with_reason(client, app):
    with app.app_context():
        teacher_id, _, student_user_id = setup_student_in_batch()
        student_id = Student.query.filter_by(user_id=student_user_id).first().id

    student_client = app.test_client()
    login_as(student_client, student_user_id)
    submit_request(student_client)

    with app.app_context():
        record = StudentIDVerificationRequest.query.filter_by(
            student_id=student_id, status="pending"
        ).first()
        request_id = record.id

    teacher_client = app.test_client()
    login_as(teacher_client, teacher_id)
    with teacher_client.session_transaction() as session:
        print("AUTH_CHECK session _user_id =", session.get("_user_id"))
    with teacher_client:
        teacher_response = teacher_client.get("/academic/teacher/id-verification")
        print("AUTH_CHECK teacher GET status =", teacher_response.status_code)
        print("AUTH_CHECK teacher GET trace is shown in pytest output above")
    response = teacher_client.post(
        "/academic/teacher/id-verification",
        data={
            "request_id": request_id,
            "action": "reject",
            "reason": "The card photo is too blurry.",
        },
    )
    if response.status_code == 403:
        print("DEBUG 403: user session and teacher authorization need inspection")
        print("Response:", response.get_data(as_text=True)[:500])
    assert response.status_code == 302, f"Unexpected response {response.status_code}: {response.get_data(as_text=True)[:1500]}"

    with app.app_context():
        record = db.session.get(StudentIDVerificationRequest, request_id)
        student = db.session.get(Student, student_id)
        assert record.status == "rejected"
        assert record.review_reason == "The card photo is too blurry."
        assert student.id_verified is False


def test_student_cannot_open_teacher_review_queue(client, app):
    with app.app_context():
        student_user_id = add_existing_student()

    login_as(client, student_user_id)
    response = client.get("/academic/teacher/id-verification")
    assert response.status_code == 403


def test_teacher_cannot_review_request_from_another_batch(client, app):
    with app.app_context():
        teacher_id, _, student_user_id = setup_student_in_batch()
        student_id = Student.query.filter_by(user_id=student_user_id).first().id

    student_client = app.test_client()
    login_as(student_client, student_user_id)
    submit_request(student_client)

    with app.app_context():
        record = StudentIDVerificationRequest.query.filter_by(
            student_id=student_id, status="pending"
        ).first()
        request_id = record.id

        # Create a second teacher with unique account and faculty identifiers.
        from app.models import Department, Batch

        other_teacher_user = make_user(
            "other.teacher@example.test", "teacher"
        )
        department = Department.query.filter_by(code="SCI").first()
        other_batch = Batch(
            batch_code="SCI-OTHER-2026",
            name="Other ID Review Batch",
            academic_year="2026-2027",
            department_id=department.id,
            home_room="Room 9",
            is_active=True,
        )
        db.session.add(other_batch)
        db.session.flush()

        other_teacher = Teacher(
            faculty_id="FAC-OTHER-001",
            official_email="other.faculty@example.test",
            user_id=other_teacher_user.id,
            homeroom_batch_id=other_batch.id,
            id_verified=True,
        )
        db.session.add(other_teacher)
        db.session.commit()
        other_teacher_id = other_teacher_user.id

    teacher_client = app.test_client()
    login_as(teacher_client, other_teacher_id)
    response = teacher_client.post(
        "/academic/teacher/id-verification",
        data={"request_id": request_id, "action": "approve"},
    )
    assert response.status_code == 404, f"Unexpected response {response.status_code}: {response.get_data(as_text=True)[:1500]}"


def test_debug_teacher_authorization(client, app):
    with app.app_context():
        teacher_id, batch_id, student_user_id = setup_student_in_batch()
        teacher = Teacher.query.filter_by(user_id=teacher_id).first()
        user = db.session.get(__import__("app.models", fromlist=["User"]).User, teacher_id)
        print("DEBUG user role:", user.role if user else None)
        print("DEBUG teacher found:", teacher is not None)
        print("DEBUG teacher verified:", teacher.id_verified if teacher else None)
        print("DEBUG teacher batch:", teacher.homeroom_batch_id if teacher else None)
        print("DEBUG expected batch:", batch_id)
        print("DEBUG batch active:", teacher.homeroom_batch.is_active if teacher and teacher.homeroom_batch else None)

    login_as(client, teacher_id)
    response = client.get("/academic/teacher/id-verification")
    print("DEBUG review page GET:", response.status_code)


def test_student_submission_rejects_wrong_batch_code(client, app):
    with app.app_context():
        _, _, student_user_id = setup_student_in_batch()
        student_id = Student.query.filter_by(user_id=student_user_id).first().id

    login_as(client, student_user_id)
    response = client.post(
        "/academic/student/id-verification",
        data={
            "scanned_id": "CAMP-EXISTING",
            "batch_code": "WRONG-BATCH",
            "card_image": (BytesIO(PNG), "student-card.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302

    with app.app_context():
        assert StudentIDVerificationRequest.query.filter_by(
            student_id=student_id
        ).count() == 0


def test_student_submission_rejects_wrong_student_id(client, app):
    with app.app_context():
        _, _, student_user_id = setup_student_in_batch()
        student_id = Student.query.filter_by(user_id=student_user_id).first().id

    login_as(client, student_user_id)
    response = client.post(
        "/academic/student/id-verification",
        data={
            "scanned_id": "NOT-THE-STUDENT-ID",
            "batch_code": "SCI-2026-A",
            "card_image": (BytesIO(PNG), "student-card.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302

    with app.app_context():
        assert StudentIDVerificationRequest.query.filter_by(
            student_id=student_id
        ).count() == 0
