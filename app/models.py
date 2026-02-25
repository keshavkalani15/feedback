from flask_sqlalchemy import SQLAlchemy

# Initialize the database object here
db = SQLAlchemy()

# --- MODElS ---

class User(db.Model):
    __tablename__ = 'users'
    userID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    prn_empID = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum('admin', 'teacher', 'student', 'HOD'), nullable=False, index=True) 
    semester = db.Column(db.Integer, index=True)
    division = db.Column(db.String(10), index=True)
    batch = db.Column(db.String(10))

class Session(db.Model):
    __tablename__ = 'sessions'
    sessionID = db.Column(db.Integer, primary_key=True) 
    sessionName = db.Column(db.String(100), nullable=False)    
    status = db.Column(db.Integer, default=0, index=True)
    
class Subject(db.Model):
    __tablename__ = 'subjects'
    subjectID = db.Column(db.Integer, primary_key=True)
    subjectName = db.Column(db.String(100), nullable=False)
    subjectType = db.Column(db.Enum('Theory', 'Practical'), nullable=False)
    is_elective = db.Column(db.Boolean, default=False, index=True) 
    semester = db.Column(db.Integer, nullable=False, index=True)
    linked_subject_id = db.Column(db.Integer, db.ForeignKey('subjects.subjectID', ondelete='SET NULL'), nullable=True)
    linked_subject = db.relationship('Subject', remote_side=[subjectID], backref='linked_by')

class StudentElective(db.Model):
    __tablename__ = 'student_electives'
    studentPRN = db.Column(db.String(50), db.ForeignKey('users.prn_empID', ondelete='CASCADE'), primary_key=True)
    subjectID = db.Column(db.Integer, db.ForeignKey('subjects.subjectID', ondelete='CASCADE'), primary_key=True)
    elective_div = db.Column(db.String(20), nullable=False)  
    elective_batch = db.Column(db.String(20), nullable=True) 

    subject = db.relationship('Subject', backref='elective_assignments')
    student = db.relationship('User', backref='elective_assignments')

class Allocation(db.Model):
    __tablename__ = 'allocations'
    allocationID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sessionID = db.Column(db.Integer, db.ForeignKey('sessions.sessionID', ondelete='CASCADE'), index=True)
    teacherID = db.Column(db.Integer, db.ForeignKey('users.userID', ondelete='CASCADE'), index=True)
    subjectID = db.Column(db.Integer, db.ForeignKey('subjects.subjectID', ondelete='CASCADE'), index=True)
    targetSemester = db.Column(db.Integer, nullable=False)
    targetDivision = db.Column(db.String(10), nullable=False)
    targetBatch = db.Column(db.String(10), nullable=False)
    
    subject = db.relationship('Subject')
    teacher = db.relationship('User')

class TokenLog(db.Model):
    __tablename__ = 'token_log'
    studentID = db.Column(db.Integer, db.ForeignKey('users.userID', ondelete='CASCADE'), primary_key=True)
    sessionID = db.Column(db.Integer, db.ForeignKey('sessions.sessionID', ondelete='CASCADE'), primary_key=True)
    has_generated = db.Column(db.Boolean, default=False)
    is_submitted = db.Column(db.Boolean, default=False, index=True)

class ValidToken(db.Model):
    __tablename__ = 'valid_tokens'
    tokenCode = db.Column(db.String(20), primary_key=True)
    is_used = db.Column(db.Boolean, default=False)

class ActiveTokenMap(db.Model):
    __tablename__ = 'active_token_map'
    studentID = db.Column(db.Integer, db.ForeignKey('users.userID', ondelete='CASCADE'), primary_key=True)
    sessionID = db.Column(db.Integer, db.ForeignKey('sessions.sessionID', ondelete='CASCADE'), primary_key=True)
    tokenCode = db.Column(db.String(20), db.ForeignKey('valid_tokens.tokenCode', ondelete='CASCADE'), unique=True, nullable=False)

class FeedbackResult(db.Model):
    __tablename__ = 'feedback_results'
    resultID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    allocationID = db.Column(db.Integer, db.ForeignKey('allocations.allocationID', ondelete='CASCADE'), index=True)
    sessionID = db.Column(db.Integer, db.ForeignKey('sessions.sessionID', ondelete='CASCADE'), index=True)    
    questionID = db.Column(db.Integer, nullable=False)    
    rating = db.Column(db.Integer, nullable=False)

class FeedbackComment(db.Model):
    __tablename__ = 'feedback_comments'
    commentID = db.Column(db.Integer, primary_key=True, autoincrement=True)    
    allocationID = db.Column(db.Integer, db.ForeignKey('allocations.allocationID', ondelete='CASCADE') , index=True)    
    sessionID = db.Column(db.Integer, db.ForeignKey('sessions.sessionID', ondelete='CASCADE'), index=True)    
    comment_text = db.Column(db.Text, nullable=True)
    
class ClassTeacherAllocation(db.Model):
    __tablename__ = 'class_teacher_allocations'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)    
    teacherID = db.Column(db.Integer, db.ForeignKey('users.userID', ondelete='CASCADE'), nullable=False, index=True)    
    semester = db.Column(db.Integer, nullable=False)
    division = db.Column(db.String(10), nullable=False) 
    teacher = db.relationship('User', backref='class_allocations')
    
class ReportApproval(db.Model):
    __tablename__ = 'report_approvals'
    __table_args__ = (
        db.UniqueConstraint('sessionID', 'teacherID', 'subjectID', 'allocationID', name='uq_report_approval'),
    )
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sessionID = db.Column(db.Integer, db.ForeignKey('sessions.sessionID', ondelete='CASCADE'), nullable=False, index=True)
    teacherID = db.Column(db.Integer, db.ForeignKey('users.userID', ondelete='CASCADE'), nullable=False, index=True)
    subjectID = db.Column(db.Integer, db.ForeignKey('subjects.subjectID', ondelete='CASCADE'), nullable=False)
    allocationID = db.Column(db.Integer, db.ForeignKey('allocations.allocationID', ondelete='CASCADE'), nullable=True, index=True)
    teacher_agreed = db.Column(db.Boolean, default=False)
    hod_approved = db.Column(db.Boolean, default=False)