from flask import Blueprint, render_template, session, redirect, url_for, flash, request, Response
from app.models import FeedbackResult, db, User, Session, Allocation, ClassTeacherAllocation, StudentElective, Subject, ReportApproval, FeedbackComment
from werkzeug.security import generate_password_hash
import csv
import io
import re
from sqlalchemy import func
from app.utils import load_questions

teacher_bp = Blueprint('teacher', __name__)

# ==========================================
# 1. DASHBOARD & PROFILE
# ==========================================

# --- HELPER FUNCTION FOR TWIN SUBJECTS ---
def assign_twin_electives(prn, base_subject_id, elec_div, elec_batch):
    """
    Assigns the selected elective AND its twin (Theory/Practical) to the student.
    It checks both 'linked_subject_id' (forward link) and 'linked_by' (reverse link).
    """
    base_sub = Subject.query.get(base_subject_id)
    if not base_sub: return

    # 1. Add the Base Subject (The one selected/uploaded)
    db.session.add(StudentElective(
        studentPRN=prn, subjectID=base_sub.subjectID, 
        elective_div=elec_div, elective_batch=elec_batch
    ))
    
    # 2. Find the Twin (Theory <-> Practical)
    linked_id = None
    
    # Check Forward Link (Did this subject point to another?)
    if base_sub.linked_subject_id:
        linked_id = base_sub.linked_subject_id
    
    # Check Reverse Link (Did another subject point to this one?)
    else:
        # We search for a subject where 'linked_subject_id' equals our ID
        reverse_link = Subject.query.filter_by(linked_subject_id=base_sub.subjectID).first()
        if reverse_link:
            linked_id = reverse_link.subjectID
            
    # 3. Add the Twin if found
    if linked_id:
        # Check if we already added it (prevent duplicates if data is messy)
        exists = StudentElective.query.filter_by(studentPRN=prn, subjectID=linked_id).first()
        if not exists:
            db.session.add(StudentElective(
                studentPRN=prn, subjectID=linked_id, 
                elective_div=elec_div, elective_batch=elec_batch
            ))

@teacher_bp.route('/dashboard')
def dashboard():
    if session.get('role') != 'teacher': return redirect(url_for('auth.login'))
    
    user = User.query.get(session['user_id'])
    session['user_name'] = user.name
    session['user_id_str'] = user.prn_empID
    
    my_class = ClassTeacherAllocation.query.filter_by(teacherID=user.userID).first()
    class_student_count = 0
    if my_class:
        class_student_count = User.query.filter_by(
            semester=my_class.semester, 
            division=my_class.division, 
            role='student'
        ).count()

    active_sessions = Session.query.filter_by(status=1).order_by(Session.sessionID.desc()).all()
    
    # OPTIMIZED: Batch count this teacher's allocations per session in one query
    my_alloc_counts = dict(
        db.session.query(Allocation.sessionID, func.count(Allocation.allocationID))
        .filter(Allocation.teacherID == user.userID)
        .group_by(Allocation.sessionID).all()
    )
    
    my_sessions_data = []
    for s in active_sessions:
        subject_count = my_alloc_counts.get(s.sessionID, 0)
        if subject_count > 0:
            my_sessions_data.append({
                'id': s.sessionID,
                'name': s.sessionName,
                'status': s.status, 
                'subjects': subject_count,
                'date': 'Active'
            })

    return render_template('teacher/dashboard.html', 
                           user=user, 
                           my_class=my_class,
                           student_count=class_student_count, 
                           sessions=my_sessions_data)

@teacher_bp.route('/profile')
def profile():
    if session.get('role') != 'teacher': return redirect(url_for('auth.login'))
    user = User.query.get(session['user_id'])
    return render_template('teacher/profile.html', user=user)

# ==========================================
# 2. MANAGE STUDENTS
# ==========================================

@teacher_bp.route('/manage_students')
def manage_students():
    if session.get('role') != 'teacher': return redirect(url_for('auth.login'))
    
    user = User.query.get(session['user_id'])
    allocation = ClassTeacherAllocation.query.filter_by(teacherID=user.userID).first()
    
    students = []
    if allocation:
        students = User.query.filter_by(
            semester=allocation.semester, 
            division=allocation.division, 
            role='student'
        ).order_by(User.prn_empID).all()
    
    elective_subjects = []
    if allocation:
        elective_subjects = Subject.query.filter_by(is_elective=True, subjectType='Theory', semester=allocation.semester).all()
    
    return render_template('teacher/manage_students.html', 
                           students=students, 
                           allocation=allocation, 
                           total_count=len(students),
                           elective_subjects=elective_subjects)

@teacher_bp.route('/add_student', methods=['POST'])
def add_student():
    if session.get('role') != 'teacher': return redirect(url_for('auth.login'))

    user = User.query.get(session['user_id'])
    allocation = ClassTeacherAllocation.query.filter_by(teacherID=user.userID).first()

    if not allocation:
        flash("Action Denied: You are not assigned as a Class Teacher.", "danger")
        return redirect(url_for('teacher.manage_students'))

    prn = request.form.get('prn')
    name = request.form.get('name')
    batch = request.form.get('batch') 

    # Parse Subject ID from "Subject Name (ID: 101)" string
    subject_raw = request.form.get('subject_search')
    subject_id = None
    if subject_raw and "(ID: " in subject_raw:
        match = re.search(r'\(ID:\s*(\d+)\)', subject_raw)
        if match: subject_id = int(match.group(1))

    elec_div = request.form.get('elective_div')
    elec_batch = request.form.get('elective_batch')

    if User.query.filter_by(prn_empID=prn).first():
        flash(f"Student {prn} already exists.", "danger")
    else:
        try:
            hashed = generate_password_hash("Pass@123", method='pbkdf2:sha256')
            new_student = User(
                prn_empID=prn, name=name, role='student', password=hashed,
                semester=str(allocation.semester), division=allocation.division, batch=batch
            )
            db.session.add(new_student)

            # --- UPDATED LOGIC START ---
            if subject_id:
                # Use our smart helper to assign both Theory and Practical
                assign_twin_electives(prn, subject_id, elec_div or allocation.division, elec_batch or batch)
            # --- UPDATED LOGIC END ---
        
            db.session.commit()
            flash(f"Student Registered & Elective Assigned.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {e}", "danger")

    return redirect(url_for('teacher.manage_students'))

@teacher_bp.route('/students/upload_csv', methods=['POST'])
def upload_students_csv():
    if session.get('role') != 'teacher': return redirect(url_for('auth.login'))
    if 'file' not in request.files: return redirect(url_for('teacher.manage_students'))
    
    file = request.files['file']
    user = User.query.get(session['user_id'])
    allocation = ClassTeacherAllocation.query.filter_by(teacherID=user.userID).first()
    
    if not allocation:
        flash("Permission Denied.", "danger")
        return redirect(url_for('teacher.manage_students'))

    try:
        stream = io.StringIO(file.stream.read().decode("UTF-8-SIG"), newline=None)
        csv_input = csv.DictReader(stream)
        
        count = 0
        # Pre-hash password once for performance
        default_pw_hash = generate_password_hash("Pass@123", method='pbkdf2:sha256')

        for row in csv_input:
            row_clean = {k.lower().strip(): v.strip() for k, v in row.items() if k}
            prn = row_clean.get('prn')
            name = row_clean.get('name')
            batch = row_clean.get('batch')
            elec_sub_name = row_clean.get('elective_subject') # Name from CSV (e.g. "Deep Learning")
            elec_div = row_clean.get('elective_div')
            elec_batch = row_clean.get('elective_batch')

            if not prn or not name: continue

            # 1. Create or Update Student
            student = User.query.filter_by(prn_empID=prn).first()
            
            if not student:
                # Student does not exist -> Create new
                student = User(
                    prn_empID=prn, name=name, role='student', password=default_pw_hash,
                    semester=str(allocation.semester), division=allocation.division, batch=batch
                )
                db.session.add(student)
            else:
                # Student exists -> Update their details!
                student.name = name
                student.batch = batch
                student.semester = str(allocation.semester)
                student.division = allocation.division
            
            # 2. Handle Elective Assignment
            if elec_sub_name:
                # Fuzzy search the subject name
                subject = Subject.query.filter(
                    Subject.subjectName.ilike(f"%{elec_sub_name}%"), 
                    Subject.is_elective == True,
                    Subject.semester == allocation.semester
                ).first()
                
                if subject:
                    # Clear ANY existing electives to avoid duplicates/conflicts
                    StudentElective.query.filter_by(studentPRN=prn).delete()
                    
                    # --- UPDATED LOGIC: Use Smart Helper ---
                    assign_twin_electives(
                        prn, 
                        subject.subjectID, 
                        elec_div or allocation.division, 
                        elec_batch or batch
                    )
            count += 1
        
        db.session.commit()
        flash(f"Processed {count} records successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"CSV Error: {str(e)}", "danger")

    return redirect(url_for('teacher.manage_students'))

# ==========================================
# DOWNLOAD SAMPLE CSV (TEACHER)
# ==========================================
@teacher_bp.route('/download_sample_students')
def download_sample_students():
    if session.get('role') != 'teacher': 
        return redirect(url_for('auth.login'))
    
    # Shows an example of a student with an elective, and one without
    csv_data = "PRN,Name,Batch,Elective_Subject,Elective_Div,Elective_Batch\nF23112001,Alice Johnson,B1,Deep Learning,2,EB1\nF23112002,Bob Smith,B2,,,\n"
    
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=sample_students.csv"}
    )
    
@teacher_bp.route('/edit_student/<int:user_id>', methods=['GET', 'POST'])
def edit_student(user_id):
    if session.get('role') != 'teacher': return redirect(url_for('auth.login'))
    
    student = User.query.get_or_404(user_id)
    user = User.query.get(session['user_id'])
    allocation = ClassTeacherAllocation.query.filter_by(teacherID=user.userID).first()
    
    # Only allow Class Teacher to edit their own students
    if not allocation or str(student.semester) != str(allocation.semester) or student.division != allocation.division:
        flash("Access Denied.", "danger")
        return redirect(url_for('teacher.manage_students'))

    current_elective = StudentElective.query.filter_by(studentPRN=student.prn_empID).first()

    if request.method == 'POST':
        batch = request.form.get('batch')
        if not batch:
            flash("Error: Core Batch is mandatory.", "danger")
            return redirect(url_for('teacher.edit_student', user_id=user_id))

        student.prn_empID = request.form['prn']
        student.name = request.form['name']
        student.batch = batch
        
        if request.form.get('password'):
            student.password = generate_password_hash(request.form['password'], method='pbkdf2:sha256')

        # Parse Subject
        subject_raw = request.form.get('subject_search')
        subject_id = None
        if subject_raw and "(ID: " in subject_raw:
            match = re.search(r'\(ID:\s*(\d+)\)', subject_raw)
            if match: subject_id = int(match.group(1))

        # --- UPDATED LOGIC START ---
        if subject_id:
            # 1. Remove all old electives for this student
            StudentElective.query.filter_by(studentPRN=student.prn_empID).delete()
            
            # 2. Assign the new Twin Pair
            assign_twin_electives(
                student.prn_empID, 
                subject_id, 
                request.form.get('elective_div'), 
                request.form.get('elective_batch')
            )
        elif not subject_raw: 
            # If the teacher CLEARED the search box, remove the elective
            StudentElective.query.filter_by(studentPRN=student.prn_empID).delete()
        # --- UPDATED LOGIC END ---

        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for('teacher.manage_students'))

    elective_subjects = Subject.query.filter_by(is_elective=True, subjectType='Theory', semester=allocation.semester).all()
    return render_template('teacher/edit_student.html', 
                           student=student, 
                           allocation=allocation, 
                           elective_subjects=elective_subjects,
                           current_elective=current_elective)

@teacher_bp.route('/delete_student/<int:user_id>', methods=['POST'])
def delete_student(user_id):
    if session.get('role') != 'teacher': return redirect(url_for('auth.login'))
    student = User.query.get_or_404(user_id)
    user = User.query.get(session['user_id'])
    allocation = ClassTeacherAllocation.query.filter_by(teacherID=user.userID).first()

    if allocation and str(student.semester) == str(allocation.semester) and student.division == allocation.division:
        try:
            StudentElective.query.filter_by(studentPRN=student.prn_empID).delete()
            db.session.delete(student)
            db.session.commit()
            flash("Student removed.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {e}", "danger")
    return redirect(url_for('teacher.manage_students'))

# ==========================================
# 3. SETTINGS & RESULTS
# ==========================================

@teacher_bp.route('/change_password', methods=['GET'])
def change_password():
    if session.get('role') != 'teacher': return redirect(url_for('auth.login'))
    return render_template('teacher/change_password.html')


@teacher_bp.route('/results')
def view_results():
    if session.get('role') != 'teacher': return redirect(url_for('auth.login'))
    user = User.query.get(session['user_id'])
    
    all_sessions = Session.query.order_by(Session.status.asc(), Session.sessionID.desc()).all()
    
    # OPTIMIZED: Batch count this teacher's allocations per session in one query
    my_alloc_counts = dict(
        db.session.query(Allocation.sessionID, func.count(Allocation.allocationID))
        .filter(Allocation.teacherID == user.userID)
        .group_by(Allocation.sessionID).all()
    )
    
    results_list = []
    for s in all_sessions:
        subject_count = my_alloc_counts.get(s.sessionID, 0)
        if subject_count > 0:
            results_list.append({
                'id': s.sessionID,
                'name': s.sessionName,
                'status': s.status, 
                'count': subject_count,
                'date': s.created_at.strftime('%Y-%m-%d') if hasattr(s, 'created_at') and s.created_at else 'N/A' 
            })
    
    # ALWAYS use results.html for the list view
    return render_template('teacher/results.html', sessions=results_list)


@teacher_bp.route('/results/session/<int:session_id>')
def session_report(session_id):
    if session.get('role') != 'teacher': 
        return redirect(url_for('auth.login'))
    
    user = User.query.get(session['user_id'])
    current_session = Session.query.get_or_404(session_id)
    
    allocations = Allocation.query.filter_by(teacherID=user.userID, sessionID=session_id).all()
    
    grouped = {}
    for a in allocations:
        if a.subjectID not in grouped:
            grouped[a.subjectID] = {
                'subject': a.subject,
                'allocations': [],
                'type': a.subject.subjectType
            }
        grouped[a.subjectID]['allocations'].append(a)

    reports = []
    
    for s_id, data in grouped.items():
        subject_obj = data['subject']
        
        subject_data = {
            'subjectID': subject_obj.subjectID,
            'subjectName': subject_obj.subjectName,
            'subjectType': subject_obj.subjectType,
            'is_elective': subject_obj.is_elective
        }
        
        # --- B. NEW COMMENT SORTING LOGIC ---
        all_alloc_ids = [x.allocationID for x in data['allocations']]
        comment_objs = FeedbackComment.query.filter(
            FeedbackComment.allocationID.in_(all_alloc_ids),
            FeedbackComment.sessionID == session_id,
            FeedbackComment.comment_text != None,
            FeedbackComment.comment_text != ''
        ).all()
        
        comments_by_alloc = {alloc_id: [] for alloc_id in all_alloc_ids}
        all_subject_comments = []
        
        for c in comment_objs:
            txt = c.comment_text.strip()
            if txt:
                comments_by_alloc[c.allocationID].append(txt)
                all_subject_comments.append(txt)
        # ------------------------------------
        
        questions = load_questions('theory_questions.json') if data['type'] == 'Theory' else load_questions('lab_questions.json')
        q_count = len(questions)
        
        tabs_data = []

        # --- C. CALCULATE "ALL CLASSES" STATS ---
        if all_alloc_ids:
            overall_stats = db.session.query(
                FeedbackResult.questionID, 
                func.avg(FeedbackResult.rating),
                func.count(FeedbackResult.rating)
            ).filter(
                FeedbackResult.allocationID.in_(all_alloc_ids)
            ).group_by(FeedbackResult.questionID).all()
            
            stats_map_all = {str(stat[0]): round(stat[1], 2) for stat in overall_stats}
            total_responses_all = (sum([stat[2] for stat in overall_stats]) // q_count) if (overall_stats and q_count > 0) else 0
        else:
            stats_map_all = {}
            total_responses_all = 0
        
        tabs_data.append({
            'id': 'all',
            'label': 'All Classes',
            'stats': stats_map_all,
            'count': total_responses_all,
            'comments': all_subject_comments # <-- Attached to Overall Tab
        })

        # --- D. CALCULATE PER-CLASS (DIV/BATCH) STATS ---
        for alloc in data['allocations']:
            class_stats_query = db.session.query(
                FeedbackResult.questionID, 
                func.avg(FeedbackResult.rating),
                func.count(FeedbackResult.rating)
            ).filter_by(allocationID=alloc.allocationID).group_by(FeedbackResult.questionID).all()
            
            stats_map_class = {str(stat[0]): round(stat[1], 2) for stat in class_stats_query}
            count_class = (class_stats_query[0][2]) if class_stats_query else 0
            
            label = f"Sem {alloc.targetSemester}-{alloc.targetDivision}"
            if alloc.targetBatch != 'All':
                label += f" ({alloc.targetBatch})"
                
            tabs_data.append({
                'id': alloc.allocationID,
                'label': label,
                'stats': stats_map_class,
                'count': count_class,
                'comments': comments_by_alloc[alloc.allocationID] # <-- Attached to Specific Class Tab
            })

        # --- E. ASSEMBLE FINAL REPORT ---
        reports.append({
            'subject': subject_data, 
            'questions': questions,
            'tabs': tabs_data
            # Removed the flat 'comments' list because it is inside the tabs now!
        })
    
    # --- APPROVAL FETCHING LOGIC ---
    teacher_id = session['user_id']
    raw_approvals = ReportApproval.query.filter_by(sessionID=session_id, teacherID=teacher_id).all()
        
    approval_dict = {}
    for app in raw_approvals:
        key_alloc = app.allocationID if app.allocationID else 'all'
        dict_key = f"{app.subjectID}_{key_alloc}"
        approval_dict[dict_key] = {
            'teacher_agreed': app.teacher_agreed,
            'hod_approved': app.hod_approved
        }
            
    return render_template('teacher/session_report.html', 
                           curr_session=current_session, 
                           reports=reports, 
                           approval_dict=approval_dict,
                           teacher=user)

@teacher_bp.route('/agree_report', methods=['POST'])
def agree_report():
    if session.get('role') != 'teacher': 
        return redirect(url_for('auth.login'))

    # Only allow agreement on TERMINATED sessions (status=2).
    # Active (status=1) and Stopped/Paused (status=0) sessions must be fully terminated first.
    session_id = request.form.get('session_id')
    sess_obj = Session.query.get(session_id)
    if sess_obj and sess_obj.status != 2:
        if sess_obj.status == 1:
            flash("You cannot agree to reports while the session is still active. Please wait for the admin to terminate it.", "danger")
        else:
            flash("You cannot agree to reports while the session is paused/stopped. Please wait for the admin to fully terminate it.", "danger")
        return redirect(request.referrer)

    teacher_id = session['user_id']
    subject_id = request.form.get('subject_id')
    allocation_id = request.form.get('allocation_id') # This will be 'all' for the overall tab

    # Convert 'all' to an actual None value for the database
    if not allocation_id or allocation_id == 'all' or allocation_id == 'None':
        db_alloc_id = None
    else:
        db_alloc_id = int(allocation_id)

    # 1. Check if they somehow already agreed (prevents duplicates)
    approval = ReportApproval.query.filter_by(
        sessionID=session_id,
        teacherID=teacher_id,
        subjectID=subject_id,
        allocationID=db_alloc_id
    ).first()

    # 2. If no record exists, create it and mark it agreed
    if not approval:
        approval = ReportApproval(
            sessionID=session_id,
            teacherID=teacher_id,
            subjectID=subject_id,
            allocationID=db_alloc_id,
            teacher_agreed=True
        )
        db.session.add(approval)
    else:
        # Just in case it existed but wasn't agreed yet
        approval.teacher_agreed = True

    # 3. CASCADE: if teacher agreed to the OVERALL tab (allocationID=None),
    #    automatically agree ALL individual subpart (per-class) records too.
    if db_alloc_id is None:
        # Fetch all individual allocation IDs for this teacher+subject+session
        child_alloc_ids = [
            row[0] for row in
            db.session.query(Allocation.allocationID)
                      .filter_by(teacherID=teacher_id,
                                 subjectID=subject_id,
                                 sessionID=session_id)
                      .all()
        ]
        for child_id in child_alloc_ids:
            child_approval = ReportApproval.query.filter_by(
                sessionID=session_id,
                teacherID=teacher_id,
                subjectID=subject_id,
                allocationID=child_id
            ).first()
            if child_approval:
                child_approval.teacher_agreed = True
            else:
                db.session.add(ReportApproval(
                    sessionID=session_id,
                    teacherID=teacher_id,
                    subjectID=subject_id,
                    allocationID=child_id,
                    teacher_agreed=True
                ))

    db.session.commit()
    flash("Report successfully signed and agreed.", "success")
    
    return redirect(request.referrer) # Bounces them right back to the report page