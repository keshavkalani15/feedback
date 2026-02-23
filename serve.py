from app import create_app, db
from run import create_database_if_not_exists
from waitress import serve
import sys
import logging
from paste.translogger import TransLogger

def start_production_server():
    print("========================================")
    print("   Starting FeedBack App (Production)   ")
    print("========================================")
    
    # 1. Initialize Database
    try:
        create_database_if_not_exists()
    except Exception as e:
        print(f"Warning: DB Creation step skipped or failed: {e}")

    # 2. Create App Context
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
            print("✅ Database tables checked/created.")
        except Exception as e:
            print(f"❌ Error creating tables: {e}")
            sys.exit(1)
            
    # 3. Start Waitress Server
    print("✅ Starting Waitress WSGI server...")
    print("   Listening on http://0.0.0.0:80")
    print("   (Access via localhost or your machine's IP address)")
    print("   Press Ctrl+C to stop.")
    
    # Wrap app with TransLogger to restore access logs
    app_logged = TransLogger(app, setup_console_handler=False)
    
    # Configure logging for waitress and translogger
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logger = logging.getLogger('waitress')
    logger.setLevel(logging.INFO)
    
    try:
        # Port 80 is standard HTTP. If it requires admin privileges and fails,
        # users can change this to 5000 or 8080.
        serve(app_logged, host='0.0.0.0', port=80, threads=6)
    except OSError as e:
        print(f"\n❌ Port 80 is already in use or requires Administrator privileges.")
        print(f"   Falling back to port 5000...")
        serve(app_logged, host='0.0.0.0', port=5000, threads=6)

if __name__ == '__main__':
    start_production_server()
