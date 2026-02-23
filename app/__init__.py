from flask import Flask
from config import Config
from app.models import db
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    db.init_app(app)
    csrf.init_app(app)
    
    # --- REGISTER BLUEPRINTS ---
    from app.routes.auth_routes import auth_bp
    from app.routes.student_routes import student_bp
    from app.routes.admin_routes import admin_bp
    from app.routes.teacher_routes import teacher_bp  
    from app.routes.hod_routes import hod_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(teacher_bp, url_prefix='/teacher') 
    app.register_blueprint(hod_bp, url_prefix='/hod')
    return app