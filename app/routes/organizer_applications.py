from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user, login_required

from app.models import db, OrganizerApplication

organizer_applications_bp = Blueprint(
    "organizer_applications",
    __name__,
    url_prefix="/organizer-applications",
)


@organizer_applications_bp.route("/", methods=["GET", "POST"])
@login_required
def apply():
    if current_user.role != "student":
        flash("Only student accounts can apply for organizer privileges.", "warning")
        return redirect(url_for("main.dashboard"))

    existing = OrganizerApplication.query.filter_by(
        user_id=current_user.id, status="pending"
    ).first()

    if request.method == "POST":
        if existing:
            flash("You already have a pending application.", "info")
            return redirect(url_for("organizer_applications.apply"))

        try:
            cgpa = float(request.form.get("cgpa", ""))
            attendance = float(request.form.get("attendance", ""))
        except (TypeError, ValueError):
            flash("Enter valid CGPA and attendance values.", "danger")
            return render_template("organizer_application.html")

        if not 0 <= cgpa <= 10 or not 0 <= attendance <= 100:
            flash("CGPA must be 0–10 and attendance must be 0–100%.", "danger")
            return render_template("organizer_application.html")

        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("Please explain why you want to become an organizer.", "danger")
            return render_template("organizer_application.html")

        application = OrganizerApplication(
            user_id=current_user.id,
            cgpa=cgpa,
            attendance=attendance,
            experience=request.form.get("experience", "").strip(),
            reason=reason,
            status="pending",
        )
        db.session.add(application)
        db.session.commit()
        flash("Your organizer application has been submitted.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("organizer_application.html")


@organizer_applications_bp.route("/admin")
@login_required
def admin_list():
    if current_user.role not in {"admin", "super_admin", "developer"}:
        abort(403)

    applications = OrganizerApplication.query.order_by(
        OrganizerApplication.created_at.desc()
    ).all()
    return render_template(
        "admin_organizer_applications.html",
        applications=applications,
    )


@organizer_applications_bp.route("/admin/<int:application_id>/review", methods=["POST"])
@login_required
def review(application_id):
    if current_user.role not in {"admin", "super_admin", "developer"}:
        abort(403)

    application = db.session.get(OrganizerApplication, application_id)
    if application is None:
        abort(404)

    decision = request.form.get("decision", "").strip().lower()
    if decision not in {"approved", "rejected"}:
        flash("Invalid application decision.", "danger")
        return redirect(url_for("organizer_applications.admin_list"))

    application.status = decision
    application.admin_notes = request.form.get("admin_notes", "").strip()
    application.reviewed_by = current_user.id
    application.reviewed_at = datetime.utcnow()
    db.session.commit()

    flash(f"Application {decision}.", "success")
    return redirect(url_for("organizer_applications.admin_list"))
