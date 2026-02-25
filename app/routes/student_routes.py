from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from app.models import StudentElective, Subject, db, User, Session, Allocation, TokenLog, ValidToken, ActiveTokenMap, FeedbackResult, FeedbackComment
from sqlalchemy import or_
import string
import random
from app.utils import load_questions

# Define the Blueprint
student_bp = Blueprint('student', __name__)

# --- DASHBOARD ---

@student_bp.route('/dashboard')
def student_dashboard():
    if 'user_id' not in session or session['role'] != 'student': 
        return redirect(url_for('auth.login'))
    
    user = User.query.get(session['user_id'])
    student_electives = StudentElective.query.filter_by(studentPRN=user.prn_empID).all()
    elec_subject_ids = [e.subjectID for e in student_electives]
    
    # Build an elective lookup for quick div/batch matching
    elec_lookup = {}
    for e in student_electives:
        elec_lookup[e.subjectID] = e
    
    # =========================================================
    # OPTIMIZED: Bulk fetch all allocations relevant to this student
    # across ALL sessions in one go, then group by sessionID in Python
    # =========================================================
    
    # 1. Bulk fetch core allocations for this student's semester/division
    core_allocs = Allocation.query.join(Subject).filter(
        Allocation.targetSemester == user.semester,
        Allocation.targetDivision == str(user.division),
        or_(Allocation.targetBatch == 'All', Allocation.targetBatch == user.batch),
        Subject.is_elective == False
    ).all()
    
    # Group core allocations by sessionID
    core_session_ids = set()
    for a in core_allocs:
        core_session_ids.add(a.sessionID)
    
    # 2. Bulk fetch elective allocations for this student's specific electives
    elec_session_ids = set()
    if elec_subject_ids:
        elec_allocs = Allocation.query.join(Subject).filter(
            Allocation.subjectID.in_(elec_subject_ids),
            Subject.is_elective == True
        ).all()
        
        for a in elec_allocs:
            elec_info = elec_lookup.get(a.subjectID)
            if elec_info:
                div_match = (a.targetDivision == elec_info.elective_div.strip())
                batch_match = (a.targetBatch == 'All' or a.targetBatch == elec_info.elective_batch.strip())
                if div_match and batch_match:
                    elec_session_ids.add(a.sessionID)
    
    # Combined: sessions that have forms for this student
    sessions_with_forms = core_session_ids | elec_session_ids
    
    # 3. Bulk fetch all TokenLogs for this student
    all_token_logs = TokenLog.query.filter_by(studentID=user.userID).all()
    token_log_map = {tl.sessionID: tl for tl in all_token_logs}
    
    # 4. Bulk fetch all ActiveTokenMaps for this student
    all_active_maps = ActiveTokenMap.query.filter_by(studentID=user.userID).all()
    active_map_dict = {am.sessionID: am.tokenCode for am in all_active_maps}
    
    # --- PART A: ACTIVE SESSIONS ---
    all_active_sessions = Session.query.filter_by(status=1).all()
    dashboard_data = []
    
    for s in all_active_sessions:
        if s.sessionID not in sessions_with_forms:
            continue
        
        t_log = token_log_map.get(s.sessionID)
        status = 'new'
        token_code = None
        
        if t_log:
            if t_log.is_submitted: status = 'submitted'
            elif t_log.has_generated:
                status = 'pending'
                token_code = active_map_dict.get(s.sessionID)

        dashboard_data.append({'session': s, 'status': status, 'token': token_code})

    # --- PART B: HISTORY ---
    raw_history = Session.query.filter_by(status=2).order_by(Session.sessionID.desc()).all()
    history_data = []

    for s in raw_history:
        if s.sessionID not in sessions_with_forms:
            continue

        t_log = token_log_map.get(s.sessionID)
        status = 'completed' if (t_log and t_log.is_submitted) else 'missed'
        history_data.append({'session': s, 'status': status})

    # UI Name Cleanup for Elective
    display_elective_name = None
    if student_electives:
        first_sub = Subject.query.get(student_electives[0].subjectID)
        if first_sub:
            clean_name = first_sub.subjectName.replace('Theory', '').replace('Practical', '').replace('()', '').replace('-', '').strip()
            display_elective_name = clean_name

    return render_template('student.html', 
                           user=user, 
                           dashboard_data=dashboard_data, 
                           history_data=history_data, 
                           elective_name=display_elective_name,
                           elective_data=student_electives[0] if student_electives else None) # <--- ADD THIS


@student_bp.route('/feedback')
def student_feedback_view():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    user = User.query.get(session['user_id'])
    session_id = request.args.get('session_id')
    if not session_id: return redirect(url_for('student.student_dashboard'))

    active_map = ActiveTokenMap.query.filter_by(studentID=user.userID, sessionID=session_id).first()
    if not active_map:
        flash("Please generate a token first.")
        return redirect(url_for('student.student_dashboard'))

    student_elecs = StudentElective.query.filter_by(studentPRN=user.prn_empID).all()

    # 1. STRICT CHECK: GET REGULAR (CORE) SUBJECTS ONLY
    regular_allocations = Allocation.query.join(Subject).filter(
        Allocation.sessionID == session_id,
        Allocation.targetSemester == user.semester,
        Allocation.targetDivision == str(user.division),
        Subject.is_elective == False
    ).all()
    
    # 2. STRICT CHECK: GET ELECTIVE SUBJECTS FOR THIS STUDENT ONLY
    elective_allocations = []
    for elec in student_elecs:
        allocs = Allocation.query.join(Subject).filter(
            Allocation.sessionID == session_id,
            Subject.is_elective == True,
            Allocation.subjectID == elec.subjectID,
            Allocation.targetDivision == elec.elective_div.strip()
        ).all()
        elective_allocations.extend(allocs)

    # 3. FILTER BY CORE BATCH & ELECTIVE BATCH
    student_allocations = []
    
    for a in regular_allocations:
        if a.targetBatch == 'All' or a.targetBatch == user.batch:
            if a not in student_allocations: student_allocations.append(a)
            
    for a in elective_allocations:
        for elec in student_elecs:
            if a.subjectID == elec.subjectID and (a.targetBatch == 'All' or a.targetBatch == elec.elective_batch):
                if a not in student_allocations: student_allocations.append(a)
                break

    return render_template('feedback_form.html', 
                           user=user,
                           allocations=student_allocations,
                           theory_questions=load_questions('theory_questions.json'),
                           lab_questions=load_questions('lab_questions.json'),
                           current_session_id=session_id)

# --- GENERATE TOKEN ---
@student_bp.route('/generate_token', methods=['POST'])
def generate_token():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    user_id = session['user_id']
    session_id = int(request.form.get('session_id'))
    
    # --- NEW SECURITY CHECK START ---
    # We must check if the session is strictly ACTIVE (1).
    # If it is 0 (Inactive) or 2 (Terminated), we block it.
    current_session = Session.query.get(session_id)
    if not current_session or current_session.status != 1:
        flash("Cannot generate token. This session is closed or inactive.", "danger")
        return redirect(url_for('student.student_dashboard'))
    # --- NEW SECURITY CHECK END ---

    existing_log = TokenLog.query.filter_by(studentID=user_id, sessionID=session_id).first()
    if existing_log and existing_log.has_generated:
        flash("Token already generated.")
        return redirect(url_for('student.student_dashboard'))
        
    chars = string.ascii_uppercase + string.digits
    token_code = ''.join(random.choices(chars, k=8))
    
    try:
        new_valid = ValidToken(tokenCode=token_code, is_used=False)
        db.session.add(new_valid)
        
        if not existing_log:
            new_log = TokenLog(studentID=user_id, sessionID=session_id, has_generated=True, is_submitted=False)
            db.session.add(new_log)
        else:
            existing_log.has_generated = True

        # Remove old map for this session if exists
        old_map = ActiveTokenMap.query.filter_by(studentID=user_id, sessionID=session_id).first()
        if old_map: db.session.delete(old_map)
        
        new_map = ActiveTokenMap(studentID=user_id, sessionID=session_id, tokenCode=token_code)
        db.session.add(new_map)
        db.session.commit()
        
    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")
        flash("System Error.")

    return redirect(url_for('student.student_dashboard'))

    
# --- VERIFY GATE TOKEN (AJAX) ---
@student_bp.route('/verify_gate_token', methods=['POST'])
def verify_gate_token():
    if 'user_id' not in session: return jsonify({'status': 'error', 'message': 'Unauthorized'})
    
    data = request.json
    mapping = ActiveTokenMap.query.filter_by(
        studentID=session['user_id'], 
        tokenCode=data.get('token'),
        sessionID=data.get('session_id')
    ).first()
    
    if mapping: return jsonify({'status': 'success'})
    else: return jsonify({'status': 'error', 'message': 'Invalid Token for this Session.'})

# --- SUBMIT FEEDBACK (AJAX) ---
@student_bp.route('/submit_feedback', methods=['POST'])
def submit_feedback():
    data = request.json
    token_code = data.get('token')
    feedbacks = data.get('feedbacks')

    try:
        active_map = ActiveTokenMap.query.filter_by(tokenCode=token_code).first()
        if not active_map: return jsonify({'status': 'error', 'message': 'Invalid Token'})

        student_id = active_map.studentID
        session_id = active_map.sessionID

        # --- NEW SECURITY CHECK START ---
        # Even if the token is valid, is the SESSION still open?
        # If Admin clicked "Pause" or "Terminate" 1 second ago, we must block this.
        current_session = Session.query.get(session_id)
        if not current_session or current_session.status != 1:
            return jsonify({'status': 'error', 'message': 'Submission Failed: This session has been closed by the Admin.'})
        # --- NEW SECURITY CHECK END ---

        # Vertical Loop Logic
        for item in feedbacks:
            alloc_id = item['allocationID']
            for key, value in item.items():
                if key.startswith('q') and key[1:].isdigit():
                    db.session.add(FeedbackResult(
                        allocationID=alloc_id,
                        sessionID=session_id,
                        questionID=int(key[1:]),
                        rating=int(value)
                    ))

            if item.get('comment'):
                db.session.add(FeedbackComment(
                    allocationID=alloc_id,
                    sessionID=session_id,
                    comment_text=item.get('comment')
                ))

        # Mark as Submitted
        log = TokenLog.query.filter_by(studentID=student_id, sessionID=session_id).first()
        if log: log.is_submitted = True
        
        db.session.delete(active_map)
        valid = ValidToken.query.filter_by(tokenCode=token_code).first()
        if valid: valid.is_used = True

        db.session.commit()
        return jsonify({'status': 'success'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)})