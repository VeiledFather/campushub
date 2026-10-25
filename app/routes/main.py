from pathlib import Path
from uuid import uuid4
from flask import Blueprint, render_template, current_app, abort, flash, redirect, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db

from app.models import (
    Certificate,
    Announcement,
    Event,
    Registration,
    Review,
    Student,
    Ticket,
    User,
    VolunteerApplication,
)

main_bp = Blueprint("main", __name__)

ADMIN_ROLES = {"admin", "super_admin", "developer"}
MANAGER_ROLES = ADMIN_ROLES | {"organizer", "teacher"}


@main_bp.get("/")
def home():
    events = (
        Event.query.filter_by(status="published", is_public=True)
        .order_by(Event.created_at.desc())
        .limit(6)
        .all()
    )
    announcements = (
        Announcement.query.order_by(Announcement.created_at.desc())
        .limit(3)
        .all()
    )
    return render_template(
        "home.html", events=events, announcements=announcements
    )




@main_bp.get("/hall-of-fame")
@login_required
def hall_of_fame():
    from sqlalchemy import func, or_

    # Count verified check-ins and distinct events attended per student.
    attendance = (
        db.session.query(
            Registration.student_id.label("student_id"),
            func.count(Ticket.id).label("check_ins"),
            func.count(
                func.distinct(Registration.event_id)
            ).label("events_attended"),
        )
        .join(Ticket, Ticket.registration_id == Registration.id)
        .filter(
            Ticket.checked_in_at.isnot(None),
            Registration.status != "cancelled",
        )
        .group_by(Registration.student_id)
        .subquery()
    )

    # Count approved volunteer assignments only for completed events.
    volunteering = (
        db.session.query(
            Student.id.label("student_id"),
            func.count(VolunteerApplication.id).label(
                "volunteer_contributions"
            ),
        )
        .join(
            VolunteerApplication,
            VolunteerApplication.user_id == Student.user_id,
        )
        .join(Event, Event.id == VolunteerApplication.event_id)
        .filter(
            VolunteerApplication.status == "approved",
            Event.status == "completed",
        )
        .group_by(Student.id)
        .subquery()
    )

    # Count certificates actually issued.
    certificates = (
        db.session.query(
            Certificate.student_id.label("student_id"),
            func.count(Certificate.id).label("certificates_earned"),
        )
        .group_by(Certificate.student_id)
        .subquery()
    )

    check_ins = func.coalesce(attendance.c.check_ins, 0)
    events_attended = func.coalesce(attendance.c.events_attended, 0)
    volunteer_contributions = func.coalesce(
        volunteering.c.volunteer_contributions, 0
    )
    certificates_earned = func.coalesce(
        certificates.c.certificates_earned, 0
    )

    rankings = (
        db.session.query(
            Student.id.label("student_id"),
            User.full_name.label("student_name"),
            check_ins.label("check_ins"),
            events_attended.label("events_attended"),
            volunteer_contributions.label("volunteer_contributions"),
            certificates_earned.label("certificates_earned"),
        )
        .join(User, User.id == Student.user_id)
        .outerjoin(attendance, attendance.c.student_id == Student.id)
        .outerjoin(volunteering, volunteering.c.student_id == Student.id)
        .outerjoin(certificates, certificates.c.student_id == Student.id)
        .filter(
            or_(
                check_ins > 0,
                volunteer_contributions > 0,
                certificates_earned > 0,
            )
        )
        .order_by(
            check_ins.desc(),
            events_attended.desc(),
            volunteer_contributions.desc(),
            certificates_earned.desc(),
            User.full_name.asc(),
        )
        .limit(100)
        .all()
    )

    return render_template("hall_of_fame.html", rankings=rankings)



def _certificate_pdf_path(certificate):
    folder = Path(current_app.instance_path) / "certificates"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{certificate.certificate_code}.pdf"


def _generate_certificate_pdf(certificate):
    """Generate a print-ready, college-branded landscape certificate."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    from reportlab.graphics.barcode import qr
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderPDF
    from flask import request, url_for
    from xml.sax.saxutils import escape

    path = _certificate_pdf_path(certificate)
    event = certificate.event
    student_name = certificate.student.user.full_name or "Student"
    college_name = (
        "Rayat Shikshan Sanstha's"
        "\nKarmaveer Bhaurao Patil College, Vashi"
        "\n(Empowered Autonomous)"
    )

    page_size = landscape(A4)
    width, height = page_size
    maroon = colors.HexColor("#A50021")
    deep_maroon = colors.HexColor("#760019")
    gold = colors.HexColor("#C6A45B")
    ivory = colors.HexColor("#FFFDF6")
    ink = colors.HexColor("#282329")
    muted = colors.HexColor("#6F6870")

    pdf = canvas.Canvas(str(path), pagesize=page_size)
    pdf.setTitle(f"Certificate - {certificate.certificate_code}")
    pdf.setAuthor("CampusHub | Karmaveer Bhaurao Patil College, Vashi")

    # Ivory paper with a double maroon-and-gold frame.
    pdf.setFillColor(ivory)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setStrokeColor(maroon)
    pdf.setLineWidth(5)
    pdf.rect(20, 20, width - 40, height - 40, fill=0, stroke=1)
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.5)
    pdf.rect(30, 30, width - 60, height - 60, fill=0, stroke=1)

    # Decorative header band.
    pdf.setFillColor(deep_maroon)
    pdf.rect(32, height - 108, width - 64, 74, fill=1, stroke=0)

    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawCentredString(width / 2, height - 56,
                          "RAYAT SHIKSHAN SANSTHA'S")

    pdf.setFillColor(gold)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawCentredString(
        width / 2, height - 79,
        "KARMAVEER BHAURAO PATIL COLLEGE, VASHI"
    )

    pdf.setFillColor(maroon)
    pdf.setFont("Helvetica-Bold", 27)
    pdf.drawCentredString(width / 2, height - 158,
                          "CERTIFICATE OF PARTICIPATION")

    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.5)
    pdf.line(width * 0.29, height - 174, width * 0.71, height - 174)

    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 13)
    pdf.drawCentredString(width / 2, height - 207,
                          "This certificate is proudly presented to")

    pdf.setFillColor(deep_maroon)
    pdf.setFont("Helvetica-Bold", 26)
    pdf.drawCentredString(width / 2, height - 250, student_name[:90])

    pdf.setStrokeColor(gold)
    pdf.line(width * 0.25, height - 261, width * 0.75, height - 261)

    pdf.setFillColor(ink)
    pdf.setFont("Helvetica", 13)
    pdf.drawCentredString(width / 2, height - 291,
                          "in recognition of participation in")

    pdf.setFillColor(maroon)
    pdf.setFont("Helvetica-Bold", 19)
    pdf.drawCentredString(width / 2, height - 322, event.title[:100])

    completed = (
        getattr(event, "completed_at", None)
        or getattr(event, "end_time", None)
    )
    completed_text = (
        completed.strftime("%d %B %Y") if completed else "Event date on record"
    )

    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(
        width / 2, 91, f"Event date: {completed_text}"
    )
    pdf.drawCentredString(
        width / 2, 73,
        f"Certificate ID: {certificate.certificate_code}"
    )

    pdf.setFillColor(deep_maroon)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawCentredString(width / 2, 53, "CAMPUSHUB · OFFICIAL EVENT RECORD")

    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(
        width / 2, 39,
        "Issued digitally by CampusHub for Karmaveer Bhaurao Patil College, Vashi"
    )

    # Generate a QR code pointing to the public certificate verification page.
    verification_path = url_for(
        "main.verify_certificate",
        certificate_code=certificate.certificate_code,
        _external=False,
    )
    verification_url = request.url_root.rstrip("/") + verification_path

    qr_code = qr.QrCodeWidget(verification_url)
    bounds = qr_code.getBounds()
    qr_size = 54
    qr_drawing = Drawing(
        qr_size, qr_size,
        transform=[
            qr_size / (bounds[2] - bounds[0]), 0, 0,
            qr_size / (bounds[3] - bounds[1]),
            -bounds[0] * qr_size / (bounds[2] - bounds[0]),
            -bounds[1] * qr_size / (bounds[3] - bounds[1]),
        ],
    )
    qr_drawing.add(qr_code)
    renderPDF.draw(qr_drawing, pdf, width - 105, 48)

    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 7)
    pdf.drawCentredString(width - 78, 39, "SCAN TO VERIFY")

    pdf.showPage()
    pdf.save()
    return path


@main_bp.get("/certificates")
@login_required
def certificates():
    if current_user.role != "student":
        abort(403)

    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        abort(403)

    earned = (
        Certificate.query
        .filter_by(student_id=student.id)
        .order_by(Certificate.issued_at.desc())
        .all()
    )

    existing_event_ids = (
        db.session.query(Certificate.event_id)
        .filter_by(student_id=student.id)
    )

    eligible_events = (
        Event.query
        .join(Registration, Registration.event_id == Event.id)
        .join(Ticket, Ticket.registration_id == Registration.id)
        .filter(
            Registration.student_id == student.id,
            Registration.status != "cancelled",
            Ticket.checked_in_at.isnot(None),
            Event.status == "completed",
            ~Event.id.in_(existing_event_ids),
        )
        .order_by(Event.completed_at.desc(), Event.end_time.desc())
        .all()
    )

    return render_template(
        "certificates.html",
        certificates=earned,
        eligible_events=eligible_events,
    )


@main_bp.post("/certificates/events/<int:event_id>/claim")
@login_required
def claim_certificate(event_id):
    if current_user.role != "student":
        abort(403)

    student = Student.query.filter_by(user_id=current_user.id).first()
    event = db.session.get(Event, event_id)

    if not student or not event:
        abort(404)

    if event.status != "completed":
        flash("Certificates are available after an event is completed.", "error")
        return redirect(url_for("main.certificates"))

    attended = (
        Registration.query
        .join(Ticket, Ticket.registration_id == Registration.id)
        .filter(
            Registration.event_id == event.id,
            Registration.student_id == student.id,
            Registration.status != "cancelled",
            Ticket.checked_in_at.isnot(None),
        )
        .first()
    )

    if not attended:
        abort(403)

    certificate = Certificate.query.filter_by(
        event_id=event.id,
        student_id=student.id,
    ).first()

    if certificate is None:
        certificate = Certificate(
            certificate_code=f"CH-{uuid4().hex[:16].upper()}",
            event_id=event.id,
            student_id=student.id,
        )
        db.session.add(certificate)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            certificate = Certificate.query.filter_by(
                event_id=event.id,
                student_id=student.id,
            ).first()
            if certificate is None:
                current_app.logger.exception("Certificate issuance failed")
                flash("Certificate could not be issued right now.", "error")
                return redirect(url_for("main.certificates"))

    return redirect(
        url_for("main.download_certificate", certificate_id=certificate.id)
    )


@main_bp.get("/certificates/<int:certificate_id>/download")
@login_required
def download_certificate(certificate_id):
    certificate = db.session.get(Certificate, certificate_id)
    if not certificate:
        abort(404)

    is_owner = (
        current_user.role == "student"
        and certificate.student.user_id == current_user.id
    )
    is_admin = current_user.role in ADMIN_ROLES
    if not (is_owner or is_admin):
        abort(403)

    path = _certificate_pdf_path(certificate)
    if not path.is_file():
        _generate_certificate_pdf(certificate)

    return send_file(
        path,
        as_attachment=True,
        download_name=f"CampusHub-{certificate.certificate_code}.pdf",
        mimetype="application/pdf",
    )


@main_bp.get("/analytics")
@login_required
def event_analytics():
    from sqlalchemy import func
    from flask import abort

    is_admin = current_user.role in ADMIN_ROLES
    if not is_admin and current_user.role not in {"organizer", "teacher"}:
        abort(403)

    # Admins see platform-wide data. Organizers and teachers see only
    # events for which they are the recorded host.
    event_query = Event.query
    if not is_admin:
        event_query = event_query.filter_by(host_user_id=current_user.id)

    events = event_query.order_by(Event.start_time.desc()).all()

    total_events = len(events)
    published_events = sum(event.status == "published" for event in events)
    pending_events = sum(
        event.status in {"pending_approval", "pending"} for event in events
    )
    cancelled_events = sum(event.status == "cancelled" for event in events)

    total_registrations = 0
    total_checkins = 0
    total_reviews = 0
    total_feedback = 0
    all_ratings = []
    event_rows = []

    for event in events:
        registrations = Registration.query.filter(
            Registration.event_id == event.id,
            Registration.status != "cancelled",
        ).count()

        checkins = (
            Ticket.query.join(Ticket.registration)
            .filter(
                Registration.event_id == event.id,
                Registration.status != "cancelled",
                Ticket.checked_in_at.isnot(None),
            )
            .count()
        )

        reviews = Review.query.filter_by(event_id=event.id).all()
        ratings = [review.rating for review in reviews]
        feedback_count = sum(
            bool((review.feedback or "").strip()) for review in reviews
        )
        average_rating = round(sum(ratings) / len(ratings), 1) if ratings else None

        total_registrations += registrations
        total_checkins += checkins
        total_reviews += len(reviews)
        total_feedback += feedback_count
        all_ratings.extend(ratings)

        event_rows.append((
            event,
            registrations,
            checkins,
            average_rating,
            len(reviews),
            feedback_count,
        ))

    attendance_rate = (
        round(total_checkins / total_registrations * 100, 1)
        if total_registrations else 0
    )
    average_rating = (
        round(sum(all_ratings) / len(all_ratings), 1)
        if all_ratings else None
    )

    return render_template(
        "analytics/events.html",
        total_events=total_events,
        published_events=published_events,
        pending_events=pending_events,
        cancelled_events=cancelled_events,
        total_registrations=total_registrations,
        total_checkins=total_checkins,
        attendance_rate=attendance_rate,
        total_reviews=total_reviews,
        total_feedback=total_feedback,
        average_rating=average_rating,
        event_rows=event_rows,
    )

@main_bp.get("/dashboard")
@login_required
def dashboard():
    user_role = current_user.role

    stats = {
        "users": User.query.count() if user_role in ADMIN_ROLES else None,
        "events": Event.query.count(),
        "registrations": Registration.query.join(
            Registration.student
        ).filter(
            Registration.student.has(user_id=current_user.id)
        ).filter(
            Registration.status != "cancelled"
        ).count(),
    }

    event_rows = []
    operations = None

    if user_role in ADMIN_ROLES:
        managed_events = Event.query.order_by(Event.start_time.asc()).all()
    elif user_role in {"organizer", "teacher"}:
        managed_events = (
            Event.query.filter_by(host_user_id=current_user.id)
            .order_by(Event.start_time.asc())
            .all()
        )
    else:
        managed_events = []

    if user_role in MANAGER_ROLES:
        operations = {
            "events": len(managed_events),
            "registrations": 0,
            "checkins": 0,
            "volunteers": 0,
            "pending_volunteers": 0,
            "remaining_capacity": 0,
            "unlimited_capacity_events": 0,
        }

        for event in managed_events:
            active_registrations = Registration.query.filter_by(
                event_id=event.id
            ).filter(Registration.status != "cancelled").count()

            checkins = (
                Ticket.query.join(Ticket.registration)
                .filter(
                    Registration.event_id == event.id,
                    Ticket.checked_in_at.isnot(None),
                )
                .count()
            )

            volunteer_count = VolunteerApplication.query.filter_by(
                event_id=event.id
            ).count()

            pending_count = VolunteerApplication.query.filter_by(
                event_id=event.id,
                status="pending",
            ).count()

            if event.max_participants is None:
                remaining = None
                operations["unlimited_capacity_events"] += 1
            else:
                remaining = max(
                    0, event.max_participants - active_registrations
                )
                operations["remaining_capacity"] += remaining

            operations["registrations"] += active_registrations
            operations["checkins"] += checkins
            operations["volunteers"] += volunteer_count
            operations["pending_volunteers"] += pending_count

            event_rows.append({
                "event": event,
                "registrations": active_registrations,
                "checkins": checkins,
                "volunteers": volunteer_count,
                "pending_volunteers": pending_count,
                "remaining_capacity": remaining,
            })

    volunteer_applications = []
    volunteer_stats = None

    if user_role == "student":
        volunteer_applications = (
            VolunteerApplication.query
            .filter_by(user_id=current_user.id)
            .order_by(VolunteerApplication.created_at.desc())
            .all()
        )
        volunteer_stats = {
            "total": len(volunteer_applications),
            "pending": sum(
                app.status == "pending" for app in volunteer_applications
            ),
            "approved": sum(
                app.status == "approved" for app in volunteer_applications
            ),
            "rejected": sum(
                app.status == "rejected" for app in volunteer_applications
            ),
        }

    return render_template(
        "dashboard.html",
        stats=stats,
        operations=operations,
        event_rows=event_rows,
        volunteer_applications=volunteer_applications,
        volunteer_stats=volunteer_stats,
    )


def _can_manage_event_certificates(event):
    """Allow administrators or the verified owner/organiser of this event."""
    role = (getattr(current_user, "role", "") or "").lower()
    if role in {"admin", "super_admin", "developer"}:
        return True
    if role not in {"organizer", "organiser", "teacher"}:
        return False

    user_id = current_user.id
    candidate_fields = (
        "organizer_id", "organiser_id", "created_by_id",
        "host_id", "owner_id", "user_id",
    )
    for field in candidate_fields:
        if hasattr(event, field) and getattr(event, field) == user_id:
            return True

    # Support an Event.organizer / Event.host relationship when present.
    for field in ("organizer", "organiser", "host", "created_by", "owner"):
        related = getattr(event, field, None)
        if related is None:
            continue
        if getattr(related, "user_id", None) == user_id:
            return True
        if getattr(related, "id", None) == user_id:
            return True

    return False


@main_bp.route("/certificates/manage", methods=["GET", "POST"])
@login_required
def organizer_certificate_manager():
    """Manage participation certificates for events the user is authorised to manage."""
    from flask import request

    role = (getattr(current_user, "role", "") or "").lower()
    if role not in {
        "organizer", "organiser", "teacher", "admin", "super_admin", "developer"
    }:
        abort(403)

    manageable_events = [
        event for event in Event.query.order_by(Event.id.desc()).all()
        if _can_manage_event_certificates(event)
    ]

    event_id = request.values.get("event_id", type=int)
    selected_event = next(
        (event for event in manageable_events if event.id == event_id), None
    )

    if request.method == "POST":
        if not selected_event:
            abort(404)

        selected_ids = {
            int(value) for value in request.form.getlist("student_ids")
            if value.isdigit()
        }
        if not selected_ids:
            flash("Select at least one participant.", "error")
            return redirect(url_for(
                "main.organizer_certificate_manager", event_id=selected_event.id
            ))

        registrations = Registration.query.filter_by(
            event_id=selected_event.id
        ).all()

        eligible_students = set()
        for registration in registrations:
            if getattr(registration, "status", "") == "cancelled":
                continue
            student_id = getattr(registration, "student_id", None)
            if student_id in selected_ids:
                eligible_students.add(student_id)

        issued = 0
        skipped = 0
        for student_id in eligible_students:
            existing = Certificate.query.filter_by(
                event_id=selected_event.id, student_id=student_id
            ).first()
            if existing:
                skipped += 1
                continue

            certificate = Certificate(
                certificate_code=f"CH-{uuid4().hex[:16].upper()}",
                event_id=selected_event.id,
                student_id=student_id,
            )
            db.session.add(certificate)
            issued += 1

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Bulk certificate issuance failed")
            flash("Issuance failed; no changes were saved. Please try again.", "error")
            return redirect(url_for(
                "main.organizer_certificate_manager", event_id=selected_event.id
            ))

        flash(
            f"Issued {issued} certificate(s). "
            f"{skipped} already-issued certificate(s) were skipped.",
            "success",
        )
        return redirect(url_for(
            "main.organizer_certificate_manager", event_id=selected_event.id
        ))

    participants = []
    existing_ids = set()
    if selected_event:
        registrations = Registration.query.filter_by(
            event_id=selected_event.id
        ).all()
        for registration in registrations:
            if getattr(registration, "status", "") == "cancelled":
                continue
            student = getattr(registration, "student", None)
            if student is None:
                student = db.session.get(Student, registration.student_id)
            if student is None:
                continue
            certificate = Certificate.query.filter_by(
                event_id=selected_event.id, student_id=student.id
            ).first()
            if certificate:
                existing_ids.add(student.id)
            participants.append({
                "student": student,
                "certificate": certificate,
            })

    return render_template(
        "organizer_certificates.html",
        events=manageable_events,
        selected_event=selected_event,
        participants=participants,
        existing_ids=existing_ids,
    )


@main_bp.get("/certificates/verify/<string:certificate_code>")
def verify_certificate(certificate_code):
    """Public, minimal certificate authenticity check."""
    certificate = Certificate.query.filter_by(
        certificate_code=certificate_code
    ).first()
    if certificate is None:
        return render_template(
            "verify_certificate.html", certificate=None
        ), 404
    return render_template(
        "verify_certificate.html", certificate=certificate
    )


