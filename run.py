from app import create_app, db
from config import Config
from create_hod import create_hod_account
import pymysql

# 1. DB Creation Check (Runs once on startup)
def create_database_if_not_exists():
    try:
        conn = pymysql.connect(
            host=Config.DB_HOST,
            user=Config.DB_USERNAME,
            password=Config.DB_PASSWORD
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {Config.DB_NAME}")
        conn.close()
        print(f"✅ Database '{Config.DB_NAME}' checked/ready.")
    except Exception as e:
        print(f"❌ Database Setup Error: {e}")

# 2. Start App
if __name__ == '__main__':
    create_database_if_not_exists()
    
    app = create_app()
    
    with app.app_context():
        db.create_all()
        print("✅ Tables checked/created.")
        create_hod_account()
        
    app.run(host='0.0.0.0', port=5000, debug=True)