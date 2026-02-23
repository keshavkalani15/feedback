from app import create_app
from app.models import db, User
from werkzeug.security import generate_password_hash

# Initialize the Flask app so we can talk to the database
app = create_app()

with app.app_context():
    # 1. Check if the HOD already exists so we don't accidentally create duplicates
    existing_hod = User.query.filter_by(prn_empID='HOD123', role='HOD').first()
    
    if existing_hod:
        print("⚠️ HOD user 'HOD123' already exists in the database!")
    else:
        # 2. Securely hash the requested password
        hashed_password = generate_password_hash('HOD123', method='pbkdf2:sha256')
        
        # 3. Create the new User object
        new_hod = User(
            prn_empID='HOD123',
            name='Head of Department',
            password=hashed_password,
            role='HOD' # This matches the new role you added to models.py!
        )
        
        # 4. Save it to the database
        try:
            db.session.add(new_hod)
            db.session.commit()
            print("✅ Success! HOD user 'HOD123' has been created.")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error creating HOD: {e}")