from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import db, User
import logging
import os
from datetime import datetime

# Define the Blueprint
auth_bp = Blueprint('auth', __name__)

# --- LOGIN AUDIT LOGGER ---
_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'logs')
os.makedirs(_log_dir, exist_ok=True)

login_logger = logging.getLogger('login_audit')
login_logger.setLevel(logging.INFO)
_handler = logging.FileHandler(os.path.join(_log_dir, 'login_audit.log'), encoding='utf-8')
_handler.setFormatter(logging.Formatter('%(message)s'))
login_logger.addHandler(_handler)
login_logger.propagate = False

def _short_browser(ua_string):
    """Extract short browser name from user agent string."""
    ua = ua_string.lower()
    if 'edg/' in ua:
        ver = ua.split('edg/')[-1].split(' ')[0].split('.')[0]
        return f'Edge {ver}'
    elif 'opr/' in ua or 'opera' in ua:
        ver = ua.split('opr/')[-1].split(' ')[0].split('.')[0] if 'opr/' in ua else ''
        return f'Opera {ver}'.strip()
    elif 'chrome/' in ua:
        ver = ua.split('chrome/')[-1].split(' ')[0].split('.')[0]
        return f'Chrome {ver}'
    elif 'firefox/' in ua:
        ver = ua.split('firefox/')[-1].split(' ')[0].split('.')[0]
        return f'Firefox {ver}'
    elif 'safari/' in ua and 'chrome' not in ua:
        return 'Safari'
    return ua_string[:30]

def log_login(prn, role, status, ip, user_agent):
    """Log a login attempt to the audit file."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Get real client IP (supports reverse proxy via X-Forwarded-For)
    real_ip = request.headers.get('X-Forwarded-For', ip).split(',')[0].strip()
    browser = _short_browser(user_agent)
    login_logger.info(
        f'{timestamp} | {status:<7} | {role:<8} | {prn:<15} | {real_ip:<15} | {browser}'
    )

@auth_bp.route('/')
def index():
    return redirect(url_for('auth.login'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        
        user = User.query.filter_by(prn_empID=username, role=role).first()
        
        if user and check_password_hash(user.password, password): 
            session['user_id'] = user.userID
            session['role'] = user.role
            session['name'] = user.prn_empID
            session['user_name'] = user.name
            session['user_empid'] = user.prn_empID
            
            log_login(username, role, 'SUCCESS', request.remote_addr, request.user_agent.string)
            
            # --- DEFAULT PASSWORD CHECK ---
            # Detect if user is still using their auto-assigned default password
            default_passwords = {
                'student': 'Pass@123',
                'admin':   'Admin@123',
                'teacher': f'{user.prn_empID}@123',  # e.g. T101@123
            }
            default_pass = default_passwords.get(role)
            if default_pass and check_password_hash(user.password, default_pass):
                session['show_default_pass_warning'] = True
            
            if role == 'student': 
                return redirect(url_for('student.student_dashboard'))
            
            elif role == 'admin':
                return redirect(url_for('admin.dashboard'))
            
            elif role == 'teacher':
                return redirect(url_for('teacher.dashboard'))
            
        log_login(username, role, 'FAILED', request.remote_addr, request.user_agent.string)
        return render_template('login.html', error="Invalid Credentials")
    return render_template('login.html')


@auth_bp.route('/management_login', methods=['GET', 'POST'])
def management_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        
        user = User.query.filter_by(prn_empID=username, role='HOD').first()
        
        if user and check_password_hash(user.password, password): 
            session['user_id'] = user.userID
            session['role'] = user.role
            session['name'] = user.prn_empID
            session['user_name'] = user.name
            session['user_empid'] = user.prn_empID
            
            log_login(username, 'HOD', 'SUCCESS', request.remote_addr, request.user_agent.string)
            
            # --- DEFAULT PASSWORD CHECK FOR HOD ---
            if check_password_hash(user.password, 'HOD@123'):
                session['show_default_pass_warning'] = True
            
            return redirect(url_for('hod.dashboard'))
            
        log_login(username, 'HOD', 'FAILED', request.remote_addr, request.user_agent.string)
        return render_template('management_login.html', error="Invalid Credentials")
    return render_template('management_login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))

@auth_bp.route('/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    user = User.query.get(session['user_id'])
    current = request.form['current_password']
    new = request.form['new_password']
    confirm = request.form['confirm_password']
    
    # 1. Verification
    if not check_password_hash(user.password, current):
        flash("Incorrect Current Password", "danger") 
        return redirect(request.referrer)
        
    if new != confirm:
        flash("New passwords do not match", "warning")
        return redirect(request.referrer)
        
    # 2. Update Password
    user.password = generate_password_hash(new, method='pbkdf2:sha256')
    db.session.commit()
    
    flash("Password updated successfully! Please login again.", "success")
    session.clear() 
    return redirect(url_for('auth.login'))