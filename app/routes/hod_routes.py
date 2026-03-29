from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import db, User, Session, Allocation, Subject, FeedbackResult, FeedbackComment, ReportApproval
from sqlalchemy import func
from app.utils import load_questions

hod_bp = Blueprint('hod', __name__)

@hod_bp.route('/dashboard')
def dashboard():
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    
    stats = {
        'students': User.query.filter_by(role='student').count(),
        'teachers': User.query.filter_by(role='teacher').count()
    }
    # View-only sessions
    sessions = Session.query.order_by(Session.sessionID.desc()).all()
    
    return render_template('hod/dashboard.html', stats=stats, sessions=sessions)

@hod_bp.route('/results')
def view_results():
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    sessions = Session.query.order_by(Session.sessionID.desc()).all()
    
    # OPTIMIZED: Batch count allocations in one query instead of N queries
    alloc_counts = dict(
        db.session.query(Allocation.sessionID, func.count(Allocation.allocationID))
        .group_by(Allocation.sessionID).all()
    )
    for s in sessions:
        s.alloc_count = alloc_counts.get(s.sessionID, 0)
    return render_template('hod/results_sessions.html', sessions=sessions)

@hod_bp.route('/results/session/<int:session_id>')
def session_teachers(session_id):
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    curr_session = Session.query.get_or_404(session_id)

    teacher_ids = db.session.query(Allocation.teacherID).filter_by(sessionID=session_id).distinct().all()
    teacher_ids = [t[0] for t in teacher_ids]
    teachers = User.query.filter(User.userID.in_(teacher_ids)).all()

    # --- OPTIMIZED: Batch fetch subject counts per teacher in one query ---
    subject_counts_by_teacher = {}
    subject_count_rows = db.session.query(
        Allocation.teacherID, func.count(func.distinct(Allocation.subjectID))
    ).filter_by(sessionID=session_id).group_by(Allocation.teacherID).all()
    for row in subject_count_rows:
        subject_counts_by_teacher[row[0]] = row[1]

    # --- OPTIMIZED: Batch fetch ALL overall approvals for this session in one query ---
    all_approvals = ReportApproval.query.filter_by(
        sessionID=session_id,
        allocationID=None
    ).all()
    
    # Group approvals by teacherID
    approvals_by_teacher = {}
    for a in all_approvals:
        if a.teacherID not in approvals_by_teacher:
            approvals_by_teacher[a.teacherID] = []
        approvals_by_teacher[a.teacherID].append(a)

    # --- Compute per-teacher status for colour-coding ---
    teacher_info = []
    for t in teachers:
        total_subjects = subject_counts_by_teacher.get(t.userID, 0)
        
        teacher_approvals = approvals_by_teacher.get(t.userID, [])
        agreed_count   = sum(1 for a in teacher_approvals if a.teacher_agreed)
        approved_count = sum(1 for a in teacher_approvals if a.hod_approved)

        all_agreed       = (total_subjects > 0) and (agreed_count   >= total_subjects)
        all_hod_approved = (total_subjects > 0) and (approved_count >= total_subjects)
        # Subjects the teacher has signed but HOD hasn't yet approved
        agreed_pending_hod = max(0, agreed_count - approved_count)
        # Subjects the teacher still hasn't signed
        unagreed_count     = max(0, total_subjects - agreed_count)

        # Sort key: 0 = green  (all agreed, awaiting HOD)
        #           1 = yellow (some agreed awaiting HOD + some still unagreed — both need to act)
        #           2 = red    (ball is entirely in teacher's court — no pending HOD work)
        #           3 = white  (fully HOD-approved)
        if all_hod_approved:
            sort_key = 3
            card_status = 'approved'
        elif all_agreed:
            sort_key = 0
            card_status = 'agreed'
        elif agreed_pending_hod > 0 and unagreed_count > 0:
            # HOD can still approve some, teacher must also agree to rest → yellow
            sort_key = 1
            card_status = 'partial'
        else:
            # Nothing for HOD to do; all unagreed → only teacher can advance → red
            sort_key = 2
            card_status = 'pending'

        teacher_info.append({
            'teacher':    t,
            'status':     card_status,
            'sort_key':   sort_key,
        })

    # Sort: green → yellow → red → white
    teacher_info.sort(key=lambda x: x['sort_key'])

    # --- Build semester filter data ---
    semesters_raw = db.session.query(Allocation.targetSemester).filter_by(
        sessionID=session_id
    ).distinct().order_by(Allocation.targetSemester).all()
    semesters = sorted(set(s[0] for s in semesters_raw if s[0] != 0))

    # Map teacherID -> list of semesters they teach
    # For electives (targetSemester=0), fall back to the subject's own semester
    allocs_all = Allocation.query.filter_by(sessionID=session_id).all()
    teacher_sems = {}
    for a in allocs_all:
        if a.teacherID not in teacher_sems:
            teacher_sems[a.teacherID] = set()
        sem = a.targetSemester if a.targetSemester != 0 else (a.subject.semester if a.subject else 0)
        if sem != 0:
            teacher_sems[a.teacherID].add(sem)
    teacher_sems = {k: sorted(v) for k, v in teacher_sems.items()}

    return render_template('hod/session_teachers.html',
                           curr_session=curr_session,
                           teacher_info=teacher_info,
                           semesters=semesters,
                           teacher_sems=teacher_sems)

@hod_bp.route('/results/report/<int:session_id>/<int:teacher_id>')
def teacher_report(session_id, teacher_id):
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
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
        # NEW COMMENT SORTING LOGIC
        # ==========================================
        raw_comments = FeedbackComment.query.filter(
            FeedbackComment.allocationID.in_(all_ids),
            FeedbackComment.sessionID == session_id,
            FeedbackComment.comment_text != None,
            FeedbackComment.comment_text != ''
        ).all()
        
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

        def _sort_alloc(a):
            b_map = {'All': 0, 'P': 1, 'Q': 2, 'R': 3}
            b = b_map.get(a.targetBatch, 99)
            try: d = float(a.targetDivision)
            except (ValueError, TypeError): d = 999.0
            return (a.targetSemester, d, str(a.targetDivision), b, str(a.targetBatch))

        for alloc in sorted(data['allocations'], key=_sort_alloc):
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

    # --- APPROVAL FETCHING LOGIC ---
    raw_approvals = ReportApproval.query.filter_by(sessionID=session_id, teacherID=teacher_id).all()
    
    approval_dict = {}
    for app in raw_approvals:
        key_alloc = app.allocationID if app.allocationID else 'all'
        dict_key = f"{app.subjectID}_{key_alloc}"
        approval_dict[dict_key] = {
            'teacher_agreed': app.teacher_agreed,
            'hod_approved': app.hod_approved
        }

    return render_template('hod/teacher_report.html', 
                           curr_session=curr_session, 
                           teacher=teacher, 
                           reports=reports, 
                           approval_dict=approval_dict) # Removed the old 'comments=comments'
    

@hod_bp.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    
    if request.method == 'POST':
        user = User.query.get(session['user_id'])
        current_pass = request.form.get('current_password', '')
        new_pass = request.form['password']
        
        if not check_password_hash(user.password, current_pass):
            flash("Incorrect current password.", "danger")
            return redirect(url_for('hod.change_password'))
        
        user.password = generate_password_hash(new_pass, method='pbkdf2:sha256')
        db.session.commit()
        flash("Password changed.", "success")
        
    return render_template('hod/change_password.html')

# --- UPDATED HOD APPROVE ROUTE ---
@hod_bp.route('/approve_report', methods=['POST'])
def approve_report():
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))

    session_id = request.form.get('session_id')
    teacher_id = request.form.get('teacher_id')
    subject_id = request.form.get('subject_id')

    # Only allow HOD approval on TERMINATED sessions (status=2).
    # Active (status=1) and Stopped/Paused (status=0) sessions must be fully terminated first.
    sess_obj = Session.query.get(session_id)
    if sess_obj and sess_obj.status != 2:
        if sess_obj.status == 1:
            flash("You cannot approve reports while the session is still active. Please wait for the admin to terminate it.", "danger")
        else:
            flash("You cannot approve reports while the session is paused/stopped. Please wait for the admin to fully terminate it.", "danger")
        return redirect(request.referrer)

    
    # 1. Get the overall approval record
    overall_approval = ReportApproval.query.filter_by(
        sessionID=session_id,
        teacherID=teacher_id,
        subjectID=subject_id,
        allocationID=None
    ).first()
    
    if overall_approval and overall_approval.teacher_agreed:
        # 2. Mark the overall record as approved
        overall_approval.hod_approved = True
        
        # 3. CRUCIAL FIX: Fetch ALL individual class records for this subject and approve them too!
        child_approvals = ReportApproval.query.filter_by(
            sessionID=session_id,
            teacherID=teacher_id,
            subjectID=subject_id
        ).all()
        
        for child in child_approvals:
            child.hod_approved = True
            
        db.session.commit()
        flash("Subject report and all related classes officially approved.", "success")
    else:
        flash("Cannot approve. The teacher must agree to the overall report first.", "danger")
        
    return redirect(request.referrer)


# --- HOD APPROVE ALL ROUTE ---
@hod_bp.route('/approve_all', methods=['POST'])
def approve_all():
    """Approve all subjects for a teacher that the teacher has already agreed to."""
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))

    session_id = request.form.get('session_id')
    teacher_id = request.form.get('teacher_id')

    sess_obj = Session.query.get(session_id)
    if sess_obj and sess_obj.status != 2:
        flash("Cannot approve while the session is not yet terminated.", "danger")
        return redirect(request.referrer)

    # Find all overall approval records (allocationID=None) where teacher has agreed
    overall_approvals = ReportApproval.query.filter_by(
        sessionID=session_id,
        teacherID=teacher_id,
        allocationID=None,
    ).filter(ReportApproval.teacher_agreed == True).all()

    if not overall_approvals:
        flash("No agreed subjects found to approve.", "warning")
        return redirect(request.referrer)

    approved_count = 0
    for overall in overall_approvals:
        if not overall.hod_approved:
            overall.hod_approved = True
            approved_count += 1
            # Also approve all child (per-class) records for this subject
            child_approvals = ReportApproval.query.filter_by(
                sessionID=session_id,
                teacherID=teacher_id,
                subjectID=overall.subjectID
            ).all()
            for child in child_approvals:
                child.hod_approved = True

    db.session.commit()
    if approved_count:
        flash(f"Approved {approved_count} subject(s) successfully.", "success")
    else:
        flash("All agreed subjects were already approved.", "info")

    return redirect(request.referrer)

# ==========================================
# CREATE ADMIN (HOD Only)
# ==========================================
@hod_bp.route('/create_admin', methods=['GET', 'POST'])
def create_admin():
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    
    if request.method == 'POST':
        emp_id = request.form.get('emp_id', '').strip()
        name = request.form.get('name', '').strip()
        
        if not emp_id or not name:
            flash("Login ID and Name are required.", "danger")
            return redirect(url_for('hod.create_admin'))
        
        existing = User.query.filter_by(prn_empID=emp_id).first()
        if existing:
            flash(f"A user with ID '{emp_id}' already exists.", "warning")
            return redirect(url_for('hod.create_admin'))
        
        try:
            new_admin = User(
                prn_empID=emp_id,
                name=name,
                password=generate_password_hash('Admin@123', method='pbkdf2:sha256'),
                role='admin'
            )
            db.session.add(new_admin)
            db.session.commit()
            flash(f"Admin '{name}' created successfully. Default password: Admin@123", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {e}", "danger")
        
        return redirect(url_for('hod.create_admin'))
    
    admins = User.query.filter_by(role='admin').all()
    return render_template('hod/create_admin.html', admins=admins)

@hod_bp.route('/edit_admin/<int:user_id>')
def edit_admin(user_id):
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    admin = User.query.get_or_404(user_id)
    return render_template('hod/edit_admin.html', admin=admin)

@hod_bp.route('/update_admin/<int:user_id>', methods=['POST'])
def update_admin(user_id):
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    admin = User.query.get_or_404(user_id)
    
    admin.name = request.form['name']
    
    new_pass = request.form.get('password')
    if new_pass:
        admin.password = generate_password_hash(new_pass, method='pbkdf2:sha256')
    
    db.session.commit()
    flash("Admin updated successfully.", "success")
    return redirect(url_for('hod.create_admin'))

@hod_bp.route('/delete_admin/<int:user_id>', methods=['POST'])
def delete_admin(user_id):
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    
    user = User.query.get_or_404(user_id)
    if user.role != 'admin':
        flash("Cannot delete non-admin users via this route.", "danger")
        return redirect(url_for('hod.create_admin'))
    
    admin_count = User.query.filter_by(role='admin').count()
    if admin_count <= 1:
        flash("Cannot delete the last admin. At least one admin must exist.", "danger")
        return redirect(url_for('hod.create_admin'))
    
    db.session.delete(user)
    db.session.commit()
    flash(f"Admin '{user.name}' deleted.", "success")
    return redirect(url_for('hod.create_admin'))

# --- HOD ANALYZE ROUTES (COPIED FROM ADMIN) ---

@hod_bp.route('/analyze')
def analyze():
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    sessions = Session.query.order_by(Session.sessionID.desc()).all()
    
    # OPTIMIZED: Batch count allocations in one query instead of N queries
    alloc_counts = dict(
        db.session.query(Allocation.sessionID, func.count(Allocation.allocationID))
        .group_by(Allocation.sessionID).all()
    )
    for s in sessions:
        s.alloc_count = alloc_counts.get(s.sessionID, 0)
        
    return render_template('hod/analyze_sessions.html', sessions=sessions)

# --- 2. VIEW TEACHERS IN A SESSION ---
@hod_bp.route('/analyze/session/<int:session_id>')
def analyze_session_teachers(session_id):
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    curr_session = Session.query.get_or_404(session_id)
    
    # Get unique teachers who have allocations in this session
    teacher_ids = db.session.query(Allocation.teacherID).filter_by(sessionID=session_id).distinct().all()
    teacher_ids = [t[0] for t in teacher_ids]
    teachers = User.query.filter(User.userID.in_(teacher_ids)).all()
    
    # Get unique subjects in this session
    subject_ids = db.session.query(Allocation.subjectID).filter_by(sessionID=session_id).distinct().all()
    subject_ids = [s[0] for s in subject_ids]
    subjects = Subject.query.filter(Subject.subjectID.in_(subject_ids)).order_by(Subject.semester, Subject.subjectName).all()
    
    # Get distinct semesters from allocations (for filter)
    semesters = db.session.query(Allocation.targetSemester).filter_by(sessionID=session_id).distinct().order_by(Allocation.targetSemester).all()
    semesters = sorted(set([s[0] for s in semesters if s[0] != 0]))  # Exclude 0 (elective placeholder)
    
    # Build teacher -> semesters mapping for JS filtering
    teacher_sems = {}
    allocs_for_sems = Allocation.query.filter_by(sessionID=session_id).all()
    for a in allocs_for_sems:
        if a.teacherID not in teacher_sems:
            teacher_sems[a.teacherID] = set()
        if a.targetSemester != 0:
            teacher_sems[a.teacherID].add(a.targetSemester)
        else:
            # For electives, use subject semester
            teacher_sems[a.teacherID].add(a.subject.semester if a.subject else 0)
    teacher_sems = {k: list(v) for k, v in teacher_sems.items()}
    
    # Build subject -> semesters mapping for JS filtering
    subject_sems = {}
    for a in allocs_for_sems:
        if a.subjectID not in subject_sems:
            subject_sems[a.subjectID] = set()
        if a.targetSemester != 0:
            subject_sems[a.subjectID].add(a.targetSemester)
        else:
            subject_sems[a.subjectID].add(a.subject.semester if a.subject else 0)
    subject_sems = {k: list(v) for k, v in subject_sems.items()}
    
    return render_template('hod/analyze_session_teachers.html', 
        curr_session=curr_session, teachers=teachers, subjects=subjects,
        semesters=semesters, teacher_sems=teacher_sems, subject_sems=subject_sems)
    
@hod_bp.route('/analyze/report/<int:session_id>/<int:teacher_id>')
def analyze_teacher_report(session_id, teacher_id):
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    
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
        
        # Determine actual semesters this subject is taught in (handles electives where subject.semester is 0)
        active_sems = list(set([a.targetSemester if a.targetSemester != 0 else subject_obj.semester for a in data['allocations']]))
        
        subject_data = {
            'subjectID': subject_obj.subjectID,
            'subjectName': subject_obj.subjectName,
            'subjectType': subject_obj.subjectType,
            'is_elective': subject_obj.is_elective,
            'semesters': active_sems
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

        def _sort_alloc(a):
            b_map = {'All': 0, 'P': 1, 'Q': 2, 'R': 3}
            b = b_map.get(a.targetBatch, 99)
            try: d = float(a.targetDivision)
            except ValueError: d = 999.0
            return (a.targetSemester, d, str(a.targetDivision), b, str(a.targetBatch))

        for alloc in sorted(data['allocations'], key=_sort_alloc):
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
    return render_template('hod/analyze_teacher_report.html', curr_session=curr_session, teacher=teacher, reports=reports)


# --- 3. VIEW SUBJECT REPORT (Reverse of Teacher Report) ---
@hod_bp.route('/analyze/subject_report/<int:session_id>/<int:subject_id>')
def analyze_subject_report(session_id, subject_id):
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    
    curr_session = Session.query.get_or_404(session_id)
    subject = Subject.query.get_or_404(subject_id)
    
    allocations = Allocation.query.filter_by(subjectID=subject_id, sessionID=session_id).all()
    
    theory_qs = load_questions('theory_questions.json')
    lab_qs = load_questions('lab_questions.json')
    questions = theory_qs if subject.subjectType == 'Theory' else lab_qs
    q_count = len(questions) if len(questions) > 0 else 1
    
    # Group allocations by teacher
    grouped = {}
    for a in allocations:
        if a.teacherID not in grouped:
            grouped[a.teacherID] = {'teacher': a.teacher, 'allocations': []}
        grouped[a.teacherID]['allocations'].append(a)
    
    reports = []
    for t_id, data in grouped.items():
        teacher_obj = data['teacher']
        
        teacher_data = {
            'teacherID': teacher_obj.userID,
            'teacherName': teacher_obj.name,
            'teacherEmpID': teacher_obj.prn_empID
        }
        
        tabs_data = []
        all_ids = [x.allocationID for x in data['allocations']]
        
        # Comments
        raw_comments = FeedbackComment.query.filter(
            FeedbackComment.allocationID.in_(all_ids),
            FeedbackComment.sessionID == session_id,
            FeedbackComment.comment_text != None,
            FeedbackComment.comment_text != ''
        ).all()
        
        comments_by_alloc = {alloc_id: [] for alloc_id in all_ids}
        all_teacher_comments = []
        
        for c in raw_comments:
            txt = c.comment_text.strip()
            if txt:
                comments_by_alloc[c.allocationID].append(txt)
                all_teacher_comments.append(txt)
        
        # Overall stats for this teacher
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
            'comments': all_teacher_comments
        })
        
        def _sort_alloc(a):
            b_map = {'All': 0, 'P': 1, 'Q': 2, 'R': 3}
            b = b_map.get(a.targetBatch, 99)
            try: d = float(a.targetDivision)
            except ValueError: d = 999.0
            return (a.targetSemester, d, str(a.targetDivision), b, str(a.targetBatch))

        for alloc in sorted(data['allocations'], key=_sort_alloc):
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
                'comments': comments_by_alloc[alloc.allocationID]
            })
        
        reports.append({'teacher': teacher_data, 'questions': questions, 'tabs': tabs_data})
    
    subject_data = {
        'subjectID': subject.subjectID,
        'subjectName': subject.subjectName,
        'subjectType': subject.subjectType,
        'is_elective': subject.is_elective
    }
    
    return render_template('hod/analyze_subject_report.html', curr_session=curr_session, subject=subject_data, reports=reports)


# ==========================================
# SEMESTER ELECTIVE CONFIG
# ==========================================
