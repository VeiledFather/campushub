from datetime import date
from urllib.parse import urlparse, urljoin

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import User

auth_bp = Blueprint("auth", __name__)

def safe_next_url(target):
    if not target:
        return None
    host = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, target))
    if candidate.scheme in ("http", "https") and candidate.netloc == host.netloc:
        return target
    return None

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        dob_raw = request.form.get("date_of_birth", "").strip()
        course = request.form.get("course", "").strip()
        academic_year = request.form.get("academic_year", "").strip()

        try:
            dob = date.fromisoformat(dob_raw)
            if dob >= date.today():
                raise ValueError
        except ValueError:
            dob = None
            flash("Enter a valid date of birth in the past.", "error")

        if not full_name or len(full_name) > 160:
            flash("Enter your full name (up to 160 characters).", "error")
        elif dob is None:
            pass
        elif not course or len(course) > 120:
            flash("Enter your course (up to 120 characters).", "error")
        elif not academic_year or len(academic_year) > 30:
            flash("Enter your academic year.", "error")
        elif "@" not in email or len(email) > 255:
            flash("Enter a valid email address.", "error")
        elif len(password) < 12:
            flash("Your password must contain at least 12 characters.", "error")
        elif password != confirm:
            flash("The passwords do not match.", "error")
        elif User.query.filter(func.lower(User.email) == email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(
                full_name=full_name,
                email=email,
                password_hash=generate_password_hash(password),
                role="student",
                is_active=True,
                is_suspended=False,
                date_of_birth=dob,
                course=course,
                academic_year=academic_year,
            )
            db.session.add(user)
            try:
                db.session.flush()

                from app.models import Student

                first_name = full_name.split()[0].lower()
                first_name = "".join(ch for ch in first_name if ch.isalnum())
                if not first_name:
                    raise ValueError("Could not generate a student ID from the name.")

                campus_id = f"{first_name}{dob.strftime('%d%m%y')}s"
                if Student.query.filter_by(campus_id=campus_id).first():
                    campus_id = f"{campus_id}{user.id}"

                student = Student(
                    user_id=user.id,
                    campus_id=campus_id,
                    college_id=f"CHC-{user.id:06d}",
                    id_verified=False,
                    campus_id_active=True,
                )
                db.session.add(student)
                db.session.commit()
            except Exception:
                db.session.rollback()
                flash("Account creation failed. Please try again.", "error")
            else:
                login_user(user)
                flash("Welcome to CampusHub!", "success")
                return redirect(url_for("main.dashboard"))

    return render_template("register.html")

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(func.lower(User.email) == email).first()

        if (
            user
            and user.password_hash
            and check_password_hash(user.password_hash, password)
            and user.is_active
            and not user.is_suspended
        ):
            login_user(user)
            flash("You are now logged in.", "success")
            return redirect(
                safe_next_url(request.args.get("next"))
                or url_for("main.dashboard")
            )

        flash("Invalid credentials, inactive account, or suspended account.", "error")

    return render_template("login.html")

@auth_bp.post("/logout")
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.home"))


@auth_bp.route("/password-setup/<token>", methods=["GET", "POST"])
def password_setup(token):
    import base64
    import binascii
    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
    from flask import current_app

    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        # Reject malformed or non-canonical signatures before verification.
        parts = token.rsplit(".", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise BadSignature("Malformed password setup token")

        signature = parts[1]
        padded_signature = signature + "=" * (-len(signature) % 4)
        decoded_signature = base64.b64decode(
            padded_signature.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        canonical_signature = base64.urlsafe_b64encode(
            decoded_signature
        ).rstrip(b"=").decode("ascii")

        if canonical_signature != signature:
            raise BadSignature("Non-canonical token signature")

        payload = serializer.loads(
            token,
            salt="campushub-student-password-setup",
            max_age=3600,
        )
        user_id = payload.get("user_id")
    except (
        BadSignature,
        SignatureExpired,
        ValueError,
        UnicodeError,
        binascii.Error,
    ):
        flash(
            "This password setup link is invalid or has expired. "
            "Ask an administrator for a new link.",
            "error",
        )
        return redirect(url_for("auth.login"))

    expected_hash = payload.get("password_hash")
    user = db.session.get(User, user_id) if isinstance(user_id, int) else None
    if (
        user is None
        or user.role != "student"
        or user.student is None
        or not user.is_active
        or user.is_suspended
        or not expected_hash
        or user.password_hash != expected_hash
    ):
        flash("This password setup link is invalid or has already been used.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")

        if len(password) < 12:
            flash("Choose a password with at least 12 characters.", "error")
        elif password != confirmation:
            flash("The passwords do not match.", "error")
        else:
            user.set_password(password)
            db.session.commit()
            flash("Password created successfully. You can now sign in.", "success")
            return redirect(url_for("auth.login"))

    return render_template("password_setup.html")
