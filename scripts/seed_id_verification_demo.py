"""Create repeatable demo accounts and a pending student ID review."""
from app import create_app
from app.extensions import db
from app.models import (
    User, Student, Teacher, Department, Batch, StudentIDVerificationRequest
)

app = create_app()

with app.app_context():
    department = Department.query.filter_by(code="IDDEMO").first()
    if not department:
        department = Department(name="ID Verification Demo", code="IDDEMO", is_active=True)
        db.session.add(department)
        db.session.flush()

    batch = Batch.query.filter_by(name="ID Verification Demo Batch").first()
    if not batch:
        batch = Batch(
            name="ID Verification Demo Batch",
            academic_year="2026-2027",
            department_id=department.id,
            home_room="Demo Room",
            is_active=True,
        )
        db.session.add(batch)
        db.session.flush()

    teacher_user = User.query.filter_by(email="id.demo.teacher@campus.com").first()
    if not teacher_user:
        teacher_user = User(
            full_name="Demo Homeroom Teacher",
            email="id.demo.teacher@campus.com",
            password_hash="!",
            role="teacher",
            is_active=True,
            is_suspended=False,
        )
        teacher_user.set_password("CampusHubDemo!2026")
        db.session.add(teacher_user)
        db.session.flush()

    teacher = Teacher.query.filter_by(user_id=teacher_user.id).first()
    if not teacher:
        teacher = Teacher(
            faculty_id="FAC-ID-DEMO",
            official_email="id.demo.teacher@campus.com",
            faculty_role="Homeroom Teacher",
            id_verified=True,
            user_id=teacher_user.id,
            homeroom_batch_id=batch.id,
        )
        db.session.add(teacher)
    else:
        teacher.id_verified = True
        teacher.homeroom_batch_id = batch.id

    student_user = User.query.filter_by(email="id.demo.student@campus.com").first()
    if not student_user:
        student_user = User(
            full_name="Demo Student",
            email="id.demo.student@campus.com",
            password_hash="!",
            role="student",
            is_active=True,
            is_suspended=False,
        )
        student_user.set_password("CampusHubDemo!2026")
        db.session.add(student_user)
        db.session.flush()

    student = Student.query.filter_by(user_id=student_user.id).first()
    if not student:
        student = Student(
            user_id=student_user.id,
            campus_id="CAMP-DEMO-001",
            college_id="COLL-DEMO-001",
            id_verified=False,
            campus_id_active=True,
            batch_id=batch.id,
        )
        db.session.add(student)
    else:
        student.batch_id = batch.id
        student.campus_id_active = True

    db.session.flush()

    demo_image = "demo/id-verification-sample.svg"
    request_record = StudentIDVerificationRequest.query.filter_by(
        student_id=student.id, status="pending"
    ).first()
    if not request_record:
        request_record = StudentIDVerificationRequest(
            student_id=student.id,
            batch_id=batch.id,
            scanned_id=student.campus_id,
            card_image_path=demo_image,
            status="pending",
        )
        db.session.add(request_record)

    db.session.commit()
    print("ID verification demo is ready.")
    print("Student: id.demo.student@campus.com / CampusHubDemo!2026")
    print("Teacher: id.demo.teacher@campus.com / CampusHubDemo!2026")
    print("Student page: /academic/student/id-verification")
    print("Teacher review: /academic/teacher/id-verification")
