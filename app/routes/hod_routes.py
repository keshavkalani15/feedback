from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash
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
    for s in sessions:
        s.alloc_count = Allocation.query.filter_by(sessionID=s.sessionID).count()
    return render_template('hod/results_sessions.html', sessions=sessions)

@hod_bp.route('/results/session/<int:session_id>')
def session_teachers(session_id):
    if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))
    curr_session = Session.query.get_or_404(session_id)
    
    teacher_ids = db.session.query(Allocation.teacherID).filter_by(sessionID=session_id).distinct().all()
    teacher_ids = [t[0] for t in teacher_ids]
    teachers = User.query.filter(User.userID.in_(teacher_ids)).all()
    
    return render_template('hod/session_teachers.html', curr_session=curr_session, teachers=teachers)

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
        new_pass = request.form['password']
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