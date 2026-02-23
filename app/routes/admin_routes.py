from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response,jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import csv
from sqlalchemy.exc import IntegrityError
import io
from app.models import StudentElective, db, User, Session, Subject, Allocation, ClassTeacherAllocation, TokenLog, FeedbackResult
from sqlalchemy import func
from app.utils import load_questions
import re
from app.models import FeedbackComment # Make sure this is in your imports


admin_bp = Blueprint('admin', __name__)

# ==========================================
# 1. CLEAN DASHBOARD
# ==========================================
@admin_bp.route('/dashboard')
def dashboard():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    user = User.query.get(session['user_id'])
    session['user_name'] = user.name
    session['user_empid'] = user.prn_empID
    
    # 1. Stats
    stats = {
        'students': User.query.filter_by(role='student').count(),
        'teachers': User.query.filter_by(role='teacher').count()
    }
    
    # 2. Sessions (Show Active & Inactive, Hide Terminated)
    # Ordered by ID so newest is first
    sessions = Session.query.filter(Session.status != 2).order_by(Session.sessionID.desc()).all()
    
    return render_template('admin/dashboard.html', stats=stats, sessions=sessions)

# ==========================================
# 2. SESSION MANAGEMENT (New Menu Item)
# ==========================================
@admin_bp.route('/manage_sessions', methods=['GET'])
def manage_sessions():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    # Get all sessions
    all_sessions = Session.query.order_by(Session.sessionID.desc()).all()
    
    # LOGIC: Attach 'allocation_count' to each session object dynamically
    # This lets us hide the delete button in the HTML
    for s in all_sessions:
        s.alloc_count = Allocation.query.filter_by(sessionID=s.sessionID).count()

    return render_template('admin/manage_sessions.html', sessions=all_sessions)

@admin_bp.route('/session/add', methods=['POST'])
def add_session():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    # Get ID from form to use in the error message if needed
    s_id = request.form.get('session_id')
    
    try:
        new_s = Session(
            sessionID=int(s_id),
            sessionName=request.form['session_name'],
            status=0 # Default Inactive
        )
        db.session.add(new_s)
        db.session.commit()
        flash("Session Created Successfully.", "success")
        
    except IntegrityError:
        # This catches the "Duplicate entry" error
        db.session.rollback()
        flash(f"Error: Session ID '{s_id}' already exists. Please use a different ID.", "danger")
        
    except Exception as e:
        # This catches any other random errors
        db.session.rollback()
        flash("An unexpected error occurred. Please try again.", "danger")
        
    return redirect(url_for('admin.manage_sessions'))

@admin_bp.route('/session/action/<int:session_id>/<action>', methods=['POST'])
def session_action(session_id, action):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    s = Session.query.get(session_id)
    if not s: return redirect(url_for('admin.dashboard'))

    # ... (Activate/Deactivate logic remains the same) ...
    if action == 'activate':
        if s.status == 2:
            flash("Cannot activate a terminated session.", "danger")
        else:
            s.status = 1
            flash(f"Session '{s.sessionName}' is now LIVE.", "success")

    elif action == 'deactivate':
        s.status = 0
        flash(f"Session '{s.sessionName}' paused.", "warning")

    elif action == 'terminate':
        s.status = 2
        flash(f"Session '{s.sessionName}' permanently terminated.", "dark")
        
    # --- UPDATED DELETE LOGIC ---
    elif action == 'delete':
        has_allocs = Allocation.query.filter_by(sessionID=session_id).count() > 0
        # Only terminated sessions or empty inactive sessions can be deleted
        if s.status == 1:
            flash("Cannot delete a LIVE session. Pause or terminate it first.", "danger")
        elif s.status == 0 and has_allocs:
            flash("Cannot delete a stopped session with allocations. Terminate it first or remove allocations.", "danger")
        
        # 2. Verify admin password
        else:
            admin_password = request.form.get('admin_password', '')
            admin_user = User.query.get(session['user_id'])
            if not admin_password or not check_password_hash(admin_user.password, admin_password):
                flash("Incorrect password. Delete cancelled.", "danger")
            else:
                # Delete all related data first
                Allocation.query.filter_by(sessionID=session_id).delete()
                db.session.delete(s)
                flash("Session and all related data deleted successfully.", "success")

    db.session.commit()
    return redirect(request.referrer)

# ==========================================
# 3. MANAGE TEACHERS (Teachers Only)
# ==========================================
@admin_bp.route('/manage_teachers', methods=['GET'])
def manage_teachers():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    teachers = User.query.filter_by(role='teacher').all()
    return render_template('admin/manage_teachers.html', teachers=teachers)

@admin_bp.route('/add_teacher', methods=['POST'])
def add_teacher():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))

    prn = request.form.get('prn')
    name = request.form.get('name')

    if not prn or not name:
        flash("All fields are required.", "danger")
        return redirect(url_for('admin.manage_teachers'))

    # Check if exists
    if User.query.filter_by(prn_empID=prn).first():
        flash("Teacher with this Emp ID already exists.", "warning")
        return redirect(url_for('admin.manage_teachers'))

    try:
        # --- PASSWORD LOGIC ---
        # Pattern: EMP101 -> EMP101@123
        default_password = f"{prn}@123" 
        hashed_password = generate_password_hash(default_password, method='pbkdf2:sha256')

        new_teacher = User(
            prn_empID=prn, 
            name=name, 
            password=hashed_password, 
            role='teacher'
        )
        db.session.add(new_teacher)
        db.session.commit()
        flash(f"Teacher added. Default Password: {default_password}", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {e}", "danger")

    return redirect(url_for('admin.manage_teachers'))

# ==========================================
# 4. CLASS GUARDIANS (With Search Fix)
# ==========================================
@admin_bp.route('/assign_class_teacher', methods=['GET', 'POST'])
def assign_class_teacher():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        # 1. Resolve Teacher by EmpID (String) instead of ID (Int)
        raw_emp_id = request.form.get('teacher_emp_id')
        emp_id = raw_emp_id.split(' - ')[0] 
        teacher = User.query.filter_by(prn_empID=emp_id, role='teacher').first()
        
        if not teacher:
            flash("Invalid Employee ID. Teacher not found.", "danger")
            return redirect(url_for('admin.assign_class_teacher'))

        semester = request.form['semester']
        division = request.form['division']
        
        # Check Exists
        exists = ClassTeacherAllocation.query.filter_by(teacherID=teacher.userID, semester=semester, division=division).first()
        if not exists:
            db.session.add(ClassTeacherAllocation(teacherID=teacher.userID, semester=semester, division=division))
            db.session.commit()
            flash(f"Assigned {teacher.name} to Sem {semester}-{division}", "success")
        else:
            flash("This assignment already exists.", "warning")
            
        return redirect(url_for('admin.assign_class_teacher'))

    assignments = ClassTeacherAllocation.query.all()
    teachers = User.query.filter_by(role='teacher').all()
    return render_template('admin/assign_class_teacher.html', assignments=assignments, teachers=teachers)

# --- CLASS GUARDIAN EDIT ---
@admin_bp.route('/assign_class_teacher/edit/<int:assign_id>', methods=['GET', 'POST'])
def edit_class_teacher(assign_id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    assignment = ClassTeacherAllocation.query.get_or_404(assign_id)
    
    if request.method == 'POST':
        # Resolve Teacher
        emp_id = request.form['teacher_emp_id']
        teacher = User.query.filter_by(prn_empID=emp_id, role='teacher').first()
        if not teacher:
            flash("Teacher not found.", "danger")
            return redirect(url_for('admin.edit_class_teacher', assign_id=assign_id))

        # Update Fields
        assignment.teacherID = teacher.userID
        assignment.semester = request.form['semester']
        assignment.division = request.form['division']
        
        try:
            db.session.commit()
            flash("Guardian assignment updated.", "success")
            return redirect(url_for('admin.assign_class_teacher'))
        except Exception as e:
            db.session.rollback()
            flash("Error updating.", "danger")

    teachers = User.query.filter_by(role='teacher').all()
    return render_template('admin/edit_class_teacher.html', assignment=assignment, teachers=teachers)

# Add the Delete Route
@admin_bp.route('/assign_class_teacher/delete/<int:assign_id>', methods=['POST'])
def delete_class_teacher(assign_id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    assign = ClassTeacherAllocation.query.get(assign_id)
    if assign:
        db.session.delete(assign)
        db.session.commit()
        flash("Guardian removed.", "success")
    return redirect(url_for('admin.assign_class_teacher'))

# ==========================================
# 5. SEMESTER INCREMENT (Promote)
# ==========================================
@admin_bp.route('/promote', methods=['GET', 'POST'])
def promote_students():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        admin_password = request.form.get('admin_password', '')
        admin_user = User.query.get(session['user_id'])
        
        if not check_password_hash(admin_user.password, admin_password):
            flash("Incorrect password. Promotion cancelled.", "danger")
        elif request.form.get('confirm') == 'CONFIRM':
            try:
                # Delete Sem 8
                User.query.filter(User.role=='student', User.semester >= 8).delete()
                # Promote others
                db.session.execute(db.text("UPDATE users SET semester = semester + 1 WHERE role = 'student'"))
                db.session.commit()
                flash("Students promoted successfully.", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"Error: {e}", "danger")
        else:
            flash("Type CONFIRM to proceed.", "warning")
    
    return render_template('admin/promote.html')


# --- NEW API ROUTE FOR CASCADING DROPDOWN ---
@admin_bp.route('/api/subjects/<int:sem>')
def get_subjects_by_sem(sem):
    if session.get('role') != 'admin': return jsonify({'error': 'Unauthorized'}), 401
    
    subs = Subject.query.filter_by(semester=sem).order_by(Subject.subjectName).all()
    result = []
    for sub in subs:
        result.append({
            'subjectID': sub.subjectID,
            'subjectName': sub.subjectName,
            'subjectType': sub.subjectType,
            'is_elective': sub.is_elective
        })
    return jsonify(result)

# --- UPDATED ALLOCATIONS ROUTE ---
@admin_bp.route('/allocations', methods=['GET', 'POST'])
def allocations():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))

    if request.method == 'POST':
        raw_teacher = request.form.get('teacher_emp_id')
        teacher_emp = raw_teacher.split(' - ')[0] 
        teacher = User.query.filter_by(prn_empID=teacher_emp, role='teacher').first()
        
        if not teacher:
            flash("Teacher not found.", "danger")
            return redirect(url_for('admin.allocations'))
            
        s_id = request.form['session_id']
        raw_subject = request.form['subject_id_input']
        sub_id = raw_subject.split(' - ')[0]
        
        subject = Subject.query.get(sub_id)
        if not subject:
            flash("Invalid Subject.", "danger")
            return redirect(url_for('admin.allocations'))

        # Logic: Elective vs Regular
        if subject.is_elective:
            target_sem = 0 # Keep as 0 for backward compatibility with reports
            target_div = request.form.get('division_manual', '').strip() or "NA"
            target_batch = request.form.get('batch_manual', '').strip() or "All"
        else:
            target_sem = request.form['semester']
            target_div = request.form.get('division_select')
            target_batch = request.form.get('batch_select')
        
        existing_alloc = Allocation.query.filter_by(
            sessionID=s_id,
            teacherID=teacher.userID,
            subjectID=sub_id,
            targetSemester=target_sem,
            targetDivision=target_div,
            targetBatch=target_batch
        ).first()

        if existing_alloc:
            flash(f"Duplicate Error: This exact allocation already exists for {subject.subjectName} (Div {target_div}, Batch {target_batch}).", "danger")
            return redirect(url_for('admin.allocations'))

        try:
            new_alloc = Allocation(
                sessionID=s_id, 
                teacherID=teacher.userID, 
                subjectID=sub_id,
                targetSemester=target_sem,  
                targetDivision=target_div,
                targetBatch=target_batch
            )
            db.session.add(new_alloc)
            db.session.commit()
            flash(f"Allocated: {subject.subjectName} -> {target_div}", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {e}", "danger")
        
        return redirect(url_for('admin.allocations'))

    sessions = Session.query.filter(Session.status != 2).order_by(Session.sessionID.desc()).all()
    teachers = User.query.filter_by(role='teacher').all()
    
    raw_allocations = Allocation.query.join(Session).filter(Session.status != 2).order_by(Allocation.allocationID.desc()).all()
    allocations_data = []
    
    for a in raw_allocations:
        subj = Subject.query.get(a.subjectID)
        is_elec = subj.is_elective if subj else False

        if is_elec:
            elec_query = StudentElective.query.filter_by(subjectID=a.subjectID, elective_div=a.targetDivision)
            if a.targetBatch != 'All':
                elec_query = elec_query.filter_by(elective_batch=a.targetBatch)
                
            total_students = elec_query.count()
            
            submitted_count = db.session.query(TokenLog).join(User, TokenLog.studentID == User.userID)\
                .join(StudentElective, User.prn_empID == StudentElective.studentPRN)\
                .filter(
                    TokenLog.sessionID == a.sessionID,
                    TokenLog.is_submitted == True,
                    StudentElective.subjectID == a.subjectID,
                    StudentElective.elective_div == a.targetDivision
                )
            if a.targetBatch != 'All':
                submitted_count = submitted_count.filter(StudentElective.elective_batch == a.targetBatch)
            submitted_count = submitted_count.count()

        else:
            student_query = User.query.filter_by(role='student', semester=a.targetSemester, division=str(a.targetDivision))
            if a.targetBatch != 'All':
                student_query = student_query.filter_by(batch=a.targetBatch)
            total_students = student_query.count()

            submitted_query = db.session.query(TokenLog).join(User, TokenLog.studentID == User.userID).filter(
                TokenLog.sessionID == a.sessionID,
                TokenLog.is_submitted == True,
                User.semester == a.targetSemester,
                User.division == str(a.targetDivision)
            )
            if a.targetBatch != 'All':
                submitted_query = submitted_query.filter(User.batch == a.targetBatch)
            submitted_count = submitted_query.count()
        
        allocations_data.append({
            'obj': a, 'total': total_students, 'submitted': submitted_count, 'is_elective': is_elec 
        })

    # Note: We don't pass 'subjects=subjects' to the template anymore, JS handles it!
    return render_template('admin/allocations.html', sessions=sessions, teachers=teachers, allocations=allocations_data)


@admin_bp.route('/allocations/delete/<int:alloc_id>', methods=['POST'])
def delete_allocation(alloc_id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    a = Allocation.query.get(alloc_id)
    if a:
        db.session.delete(a)
        db.session.commit()
        flash("Allocation removed.", "success")
    return redirect(url_for('admin.allocations'))

# ==========================================
# 5. SUBJECT MANAGEMENT (NEW)
# ==========================================
# In app/routes/admin_routes.py

# app/routes/admin_routes.py

@admin_bp.route('/manage_subjects', methods=['GET', 'POST'])
def manage_subjects():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))

    if request.method == 'POST':
        try:
            s_id = int(request.form['subject_id'])
            s_sem = int(request.form['semester']) # <-- NEW: Capture Semester
        except ValueError:
            flash("Subject ID and Semester must be numbers.", "danger")
            return redirect(url_for('admin.manage_subjects'))

        s_name = request.form['name']
        s_type = request.form['type'] 
        is_elec = True if request.form.get('is_elective') else False

        if Subject.query.get(s_id):
            flash(f"Error: Subject ID {s_id} already exists.", "danger")
            return redirect(url_for('admin.manage_subjects'))

        try:
            new_sub = Subject(
                subjectID=s_id,
                subjectName=s_name, 
                subjectType=s_type,
                is_elective=is_elec,
                semester=s_sem # <-- NEW: Save Semester to DB
            )
            db.session.add(new_sub)
            db.session.commit() 
            
            # --- THE AUTO-LINK MAGIC ---
            if is_elec:
                clean_name = re.sub(r'(?i)\b(theory|practical|lab|elective|th|pr)\b', '', s_name)
                clean_name = re.sub(r'[^a-zA-Z0-9]', '', clean_name).lower()

                all_electives = Subject.query.filter(Subject.is_elective == True, Subject.subjectID != s_id).all()
                for other_sub in all_electives:
                    other_clean = re.sub(r'(?i)\b(theory|practical|lab|elective|th|pr)\b', '', other_sub.subjectName)
                    other_clean = re.sub(r'[^a-zA-Z0-9]', '', other_clean).lower()
                    
                    if clean_name == other_clean and clean_name != '':
                        new_sub.linked_subject_id = other_sub.subjectID
                        other_sub.linked_subject_id = new_sub.subjectID
                        db.session.commit()
                        break 
                        
            flash(f"Subject '{s_name}' added successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {e}", "danger")
            
        return redirect(url_for('admin.manage_subjects'))

    subjects = Subject.query.order_by(Subject.semester, Subject.subjectID).all() # Sorted by Sem now!
    return render_template('admin/manage_subjects.html', subjects=subjects)

# --- NEW EDIT FUNCTION ---
@admin_bp.route('/edit_subject/<int:sub_id>', methods=['POST'])
def edit_subject(sub_id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    subject = Subject.query.get_or_404(sub_id)
    try:
        subject.subjectName = request.form['name']
        subject.subjectType = request.form['type']
        subject.semester = int(request.form['semester']) # Update Semester
        subject.is_elective = True if request.form.get('is_elective') else False
        db.session.commit()
        flash(f"Subject {sub_id} updated successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error updating subject: {e}", "danger")
        
    return redirect(url_for('admin.manage_subjects'))

@admin_bp.route('/subjects/upload_csv', methods=['POST'])
def upload_subjects_csv():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    if 'file' not in request.files: return redirect(url_for('admin.manage_subjects'))
    
    file = request.files['file']
    
    try:
        stream = io.StringIO(file.stream.read().decode("UTF-8-SIG"), newline=None)
        csv_input = csv.DictReader(stream)
        
        headers = [h.lower().strip() for h in csv_input.fieldnames]
        # <-- NEW: Mandate the 'Semester' column in CSV
        if 'id' not in headers or 'name' not in headers or 'type' not in headers or 'semester' not in headers:
            flash("CSV Error: Columns must be: ID, Name, Type, Elective, Semester", "danger")
            return redirect(url_for('admin.manage_subjects'))

        count, updated = 0, 0
        skipped_rows = []
        new_elective_ids = []

        for i, row in enumerate(csv_input, start=1):
            row_clean = {k.lower().strip(): v.strip() for k, v in row.items() if k}
            s_id = row_clean.get('id')
            name = row_clean.get('name')
            s_type = row_clean.get('type')
            sem_raw = row_clean.get('semester', '0') # <-- NEW: Read Semester
            
            raw_elec = row_clean.get('elective', '').lower()
            is_elec = True if raw_elec in ['yes', 'true', '1'] else False

            if not s_id or not name or not s_type or not s_id.isdigit() or not sem_raw.isdigit():
                skipped_rows.append(f"Row {i}")
                continue
                
            s_id = int(s_id)
            s_sem = int(sem_raw) # <-- NEW: Convert to int
            final_type = 'Practical' if s_type.lower() == 'practical' else 'Theory'

            existing = Subject.query.get(s_id)
            if existing:
                existing.subjectName = name
                existing.subjectType = final_type
                existing.is_elective = is_elec
                existing.semester = s_sem # <-- NEW: Update Sem
                updated += 1
            else:
                db.session.add(Subject(subjectID=s_id, subjectName=name, subjectType=final_type, is_elective=is_elec, semester=s_sem))
                count += 1
            
            if is_elec: new_elective_ids.append(s_id)
        
        db.session.commit()
        
        # --- THE AUTO-LINK MAGIC (CSV) ---
        for elec_id in new_elective_ids:
            sub = Subject.query.get(elec_id)
            if not sub or sub.linked_subject_id: continue 
            
            clean_name = re.sub(r'(?i)\b(theory|practical|lab|elective|th|pr)\b', '', sub.subjectName)
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', clean_name).lower()

            all_electives = Subject.query.filter(Subject.is_elective == True, Subject.subjectID != elec_id).all()
            for other_sub in all_electives:
                other_clean = re.sub(r'(?i)\b(theory|practical|lab|elective|th|pr)\b', '', other_sub.subjectName)
                other_clean = re.sub(r'[^a-zA-Z0-9]', '', other_clean).lower()
                
                if clean_name == other_clean and clean_name != '':
                    sub.linked_subject_id = other_sub.subjectID
                    other_sub.linked_subject_id = sub.subjectID
                    break
        
        db.session.commit()
        
        msg = f"Done: {count} Added, {updated} Updated."
        flash(msg + (f" Warnings: Skipped {len(skipped_rows)} rows." if skipped_rows else ""), "success" if not skipped_rows else "warning")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")

    return redirect(url_for('admin.manage_subjects'))


@admin_bp.route('/subjects/delete/<int:sub_id>', methods=['POST'])
def delete_subject(sub_id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    admin_password = request.form.get('admin_password', '')
    admin_user = User.query.get(session['user_id'])
    
    if not admin_password or not check_password_hash(admin_user.password, admin_password):
        flash("Incorrect admin password. Deletion cancelled.", "danger")
        return redirect(url_for('admin.manage_subjects'))
        
    sub = Subject.query.get(sub_id)
    if sub:
        db.session.delete(sub)
        db.session.commit()
        flash("Subject deleted.", "success")
    return redirect(url_for('admin.manage_subjects'))

@admin_bp.route('/teachers/edit/<int:user_id>')
def edit_teacher(user_id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    teacher = User.query.get_or_404(user_id)
    return render_template('admin/edit_teacher.html', teacher=teacher)

@admin_bp.route('/teachers/update/<int:user_id>', methods=['POST'])
def update_teacher(user_id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    teacher = User.query.get_or_404(user_id)
    
    teacher.prn_empID = request.form['prn']
    teacher.name = request.form['name']
    
    new_pass = request.form.get('password')
    if new_pass:
        teacher.password = generate_password_hash(new_pass, method='pbkdf2:sha256')
        
    db.session.commit()
    flash("Teacher updated successfully.", "success")
    return redirect(url_for('admin.manage_teachers'))

@admin_bp.route('/change_password', methods=['GET', 'POST'])
def admin_change_password():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        user = User.query.get(session['user_id'])
        current_pass = request.form.get('current_password', '')
        new_pass = request.form['password']
        
        if not check_password_hash(user.password, current_pass):
            flash("Incorrect current password.", "danger")
            return redirect(url_for('admin.admin_change_password'))
        
        user.password = generate_password_hash(new_pass, method='pbkdf2:sha256')
        db.session.commit()
        flash("Password changed.", "success")
        
    return render_template('admin/change_password.html')


@admin_bp.route('/teachers/delete/<int:user_id>', methods=['POST'])
def delete_teacher(user_id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    admin_password = request.form.get('admin_password', '')
    admin_user = User.query.get(session['user_id'])
    
    if not admin_password or not check_password_hash(admin_user.password, admin_password):
        flash("Incorrect admin password. Deletion cancelled.", "danger")
        return redirect(url_for('admin.manage_teachers'))
        
    user = User.query.get_or_404(user_id)
    if user.role == 'teacher':
        db.session.delete(user)
        db.session.commit()
        flash("Teacher deleted successfully.", "success")
    else:
        flash("Cannot delete non-teacher users via this route.", "danger")
        
    return redirect(url_for('admin.manage_teachers'))

# ==========================================
# BULK UPLOAD ROUTES
# ==========================================

# 1. UPLOAD TEACHERS
@admin_bp.route('/teachers/upload_csv', methods=['POST'])
def upload_teachers_csv():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))

    if 'file' not in request.files: return redirect(url_for('admin.manage_teachers'))
    file = request.files['file']
    if file.filename == '': return redirect(url_for('admin.manage_teachers'))

    try:
        # Decode file
        stream = io.StringIO(file.stream.read().decode("UTF-8-SIG"), newline=None)
        csv_input = csv.DictReader(stream)

        # 1. HEADER VALIDATION (Crucial Step)
        # Normalize headers to lowercase to fix case-sensitivity issues
        headers = [h.lower().strip() for h in csv_input.fieldnames]
        if 'emp id' not in headers or 'name' not in headers:
            flash("CSV Error: Columns must be 'Emp ID' and 'Name'. Please check your file headers.", "danger")
            return redirect(url_for('admin.manage_teachers'))

        success_count = 0
        updated_count = 0
        skipped_rows = [] # To track errors
        
        for i, row in enumerate(csv_input, start=1):
            # Safe Get (Case Insensitive Lookup attempt)
            # We look for keys regardless of case
            row_clean = {k.lower().strip(): v.strip() for k, v in row.items() if k}
            
            prn = row_clean.get('emp id')
            name = row_clean.get('name')

            if not prn or not name:
                skipped_rows.append(f"Row {i}: Missing Emp ID or Name")
                continue

            existing = User.query.filter_by(prn_empID=prn, role='teacher').first()
            
            if existing:
                existing.name = name
                updated_count += 1
            else:
                default_password = f"{prn}@123"
                hashed = generate_password_hash(default_password, method='pbkdf2:sha256')
                new_teacher = User(prn_empID=prn, name=name, password=hashed, role='teacher')
                db.session.add(new_teacher)
                success_count += 1
        
        db.session.commit()
        
        # 2. DETAILED REPORTING
        msg = f"Success: {success_count} Added, {updated_count} Updated."
        if skipped_rows:
            msg += f" (Skipped {len(skipped_rows)} rows: {', '.join(skipped_rows[:3])}...)"
            flash(msg, "warning")
        else:
            flash(msg, "success")

    except UnicodeDecodeError:
        flash("File Error: Please save your CSV as 'UTF-8' encoded.", "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"System Error: {str(e)}", "danger")

    return redirect(url_for('admin.manage_teachers'))


@admin_bp.route('/results')
def view_results():
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    sessions = Session.query.order_by(Session.sessionID.desc()).all()
        
    for s in sessions:
        s.alloc_count = Allocation.query.filter_by(sessionID=s.sessionID).count()
        
    return render_template('admin/results_sessions.html', sessions=sessions)

# --- 2. VIEW TEACHERS IN A SESSION ---
@admin_bp.route('/results/session/<int:session_id>')
def session_teachers(session_id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    curr_session = Session.query.get_or_404(session_id)
    
    # Get unique teachers who have allocations in this session
    teacher_ids = db.session.query(Allocation.teacherID).filter_by(sessionID=session_id).distinct().all()
    teacher_ids = [t[0] for t in teacher_ids]
    teachers = User.query.filter(User.userID.in_(teacher_ids)).all()
    
    return render_template('admin/session_teachers.html', curr_session=curr_session, teachers=teachers)
    
@admin_bp.route('/results/report/<int:session_id>/<int:teacher_id>')
def teacher_report(session_id, teacher_id):
    if session.get('role') != 'admin': return redirect(url_for('auth.login'))
    
    curr_session = Session.query.get_or_404(session_id)
    teacher = User.query.get_or_404(teacher_id)
    
    allocations = Allocation.query.filter_by(teacherID=teacher_id, sessionID=session_id).all()
    
    grouped = {}
    theory_qs = load_questions('theory_questions.json')
    lab_qs = load_questions('lab_questions.json')

    for a in allocations:
        if a.subjectID not in grouped:
            grouped[a.subjectID] = {'subject': a.subject, 'allocations': []}
        grouped[a.subjectID]['allocations'].append(a)

    reports = []
    for s_id, data in grouped.items():
        subject_obj = data['subject']
        questions = theory_qs if subject_obj.subjectType == 'Theory' else lab_qs
        q_count = len(questions) if len(questions) > 0 else 1
        
        subject_data = {
            'subjectID': subject_obj.subjectID,
            'subjectName': subject_obj.subjectName,
            'subjectType': subject_obj.subjectType,
            'is_elective': subject_obj.is_elective
        }
        
        tabs_data = []
        all_ids = [x.allocationID for x in data['allocations']]
        
        # ==========================================
        # 1. NEW COMMENT SORTING LOGIC
        # ==========================================
        raw_comments = FeedbackComment.query.filter(
            FeedbackComment.allocationID.in_(all_ids),
            FeedbackComment.sessionID == session_id,
            FeedbackComment.comment_text != None,
            FeedbackComment.comment_text != ''
        ).all()
        
        # Sort them into a dictionary by allocation ID
        comments_by_alloc = {alloc_id: [] for alloc_id in all_ids}
        all_subject_comments = []
        
        for c in raw_comments:
            txt = c.comment_text.strip()
            if txt:
                comments_by_alloc[c.allocationID].append(txt)
                all_subject_comments.append(txt)
        # ==========================================

        overall_stats = db.session.query(
            FeedbackResult.questionID, 
            func.avg(FeedbackResult.rating), 
            func.count(FeedbackResult.rating)
        ).filter(FeedbackResult.allocationID.in_(all_ids)).group_by(FeedbackResult.questionID).all()
        
        tabs_data.append({
            'id': 'all', 
            'label': 'All Class',
            'stats': {str(q[0]): round(q[1], 2) for q in overall_stats},
            'count': sum([q[2] for q in overall_stats]) // q_count if overall_stats else 0,
            'comments': all_subject_comments # <-- Attached to Overall Tab
        })

        for alloc in data['allocations']:
            c_query = db.session.query(
                FeedbackResult.questionID, 
                func.avg(FeedbackResult.rating), 
                func.count(FeedbackResult.rating)
            ).filter_by(allocationID=alloc.allocationID).group_by(FeedbackResult.questionID).all()
            
            tabs_data.append({
                'id': alloc.allocationID,
                'label': f"Sem {alloc.targetSemester}-{alloc.targetDivision} ({alloc.targetBatch})",
                'stats': {str(q[0]): round(q[1], 2) for q in c_query},
                'count': (sum([q[2] for q in c_query]) // q_count) if c_query else 0,
                'comments': comments_by_alloc[alloc.allocationID] # <-- Attached to Specific Class Tab
            })

        reports.append({'subject': subject_data, 'questions': questions, 'tabs': tabs_data})

    # Note: We no longer need to pass 'comments=comments' at the end because they are inside 'reports' now!
    return render_template('admin/teacher_report.html', curr_session=curr_session, teacher=teacher, reports=reports)


# ==========================================
# DOWNLOAD SAMPLE CSVs (ADMIN)
# ==========================================
@admin_bp.route('/download_sample/<file_type>')
def download_sample(file_type):
    if session.get('role') != 'admin': 
        return redirect(url_for('auth.login'))
    
    if file_type == 'subjects':
        # --- NEW: Added 'Semester' to the header and data rows! ---
        csv_data = "ID,Name,Type,Elective,Semester\n310250,Deep Learning,Theory,Yes,6\n310259,Deep Learning Lab,Practical,Yes,6\n310241,Database Management,Theory,No,5\n"
        filename = "sample_subjects.csv"
    elif file_type == 'teachers':
        csv_data = "Emp ID,Name\nT101,John Doe\nT102,Jane Smith\n"
        filename = "sample_teachers.csv"
    else:
        return "Invalid file type", 400

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )