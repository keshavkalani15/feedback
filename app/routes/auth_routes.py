from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import db, User

# Define the Blueprint
auth_bp = Blueprint('auth', __name__)

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
            
            if role == 'student': 
                return redirect(url_for('student.student_dashboard'))
            
            elif role == 'admin':
                return redirect(url_for('admin.dashboard'))
            
            elif role == 'teacher':
                return redirect(url_for('teacher.dashboard'))
            
            # Placeholder for admin/teacher later
            return "Login Successful (Teacher/Admin dashboard not ready)"
            
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
            return redirect(url_for('hod.dashboard'))
            
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