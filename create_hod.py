from app import create_app
from app.models import db, User
from werkzeug.security import generate_password_hash

def create_hod_account():
    # 1. Check if the HOD already exists so we don't accidentally create duplicates
    existing_hod = User.query.filter_by(prn_empID='HOD101', role='HOD').first()
    
    if existing_hod:
        print("⚠️ HOD user 'HOD101' already exists in the database!")
    else:
        # 2. Securely hash the requested password
        hashed_password = generate_password_hash('HOD@123', method='pbkdf2:sha256')
        
        # 3. Create the new User object
        new_hod = User(
            prn_empID='HOD101',
            name='Head of Department',
            password=hashed_password,
            role='HOD' # This matches the new role you added to models.py!
        )
        
        # 4. Save it to the database
        try:
            db.session.add(new_hod)
            db.session.commit()
            print("✅ Success! HOD user 'HOD101' has been created.")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error creating HOD: {e}")

if __name__ == '__main__':
    # Initialize the Flask app so we can talk to the database
    app = create_app()
    with app.app_context():
        create_hod_account()