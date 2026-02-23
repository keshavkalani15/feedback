from app import create_app
from app.models import db, User
from werkzeug.security import generate_password_hash

app = create_app()

def create_initial_admin():
    with app.app_context():
        admin_id = "Admin123"
        
        # Check if exists
        existing = User.query.filter_by(prn_empID=admin_id).first()
        if existing:
            print("Admin already exists.")
            return

        # Password Hashing
        hashed_pw = generate_password_hash("Pass@123", method='pbkdf2:sha256')

        new_admin = User(
            prn_empID=admin_id,
            name="Admin",
            password=hashed_pw,
            role="admin",
            semester=None,  
            division=None,  
            batch=None      
        )

        db.session.add(new_admin)
        db.session.commit()
        print("✅ Admin 'Admin123' created with password 'Pass@123'")

if __name__ == "__main__":
    create_initial_admin()