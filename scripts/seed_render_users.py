import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from app.extensions import db
from app.models import User

DEMO_USERS = [
    ("CampusHub Admin", "admin@campus.com", "admin"),
    ("Demo Student", "student@campus.com", "student"),
    ("Demo Teacher", "teacher@campus.com", "teacher"),
    ("Demo Organizer", "organizer@campus.com", "organizer"),
    ("Demo Volunteer", "volunteer@campus.com", "volunteer"),
]

DEMO_PASSWORD = "CampusHubDemo!2026"

app = create_app()

with app.app_context():
    try:
        for full_name, email, role in DEMO_USERS:
            user = User.query.filter_by(email=email).first()

            if user is None:
                user = User(
                    full_name=full_name,
                    email=email,
                    role=role,
                    is_active=True,
                    is_suspended=False,
                )
                user.set_password(DEMO_PASSWORD)
                db.session.add(user)
                print(f"Created: {email} ({role})")
            else:
                print(f"Already exists: {email}")

        db.session.commit()
        print("Demo-user seeding completed successfully.")

    except Exception:
        db.session.rollback()
        raise
