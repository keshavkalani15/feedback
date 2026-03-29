import re

with open('app/routes/admin_routes.py', 'r', encoding='utf-8') as f:
    text = f.read()

def get_f(name):
    match = re.search(r'(@admin_bp\.route[^@]+def ' + name + r'\(.*?(?=\n@|\Z))', text, re.DOTALL)
    if match: return match.group(1)
    return ''

funcs = [
    get_f('view_results'),
    get_f('session_teachers'),
    get_f('teacher_report'),
    get_f('subject_report')
]

out = "\n\n# --- HOD ANALYZE ROUTES (COPIED FROM ADMIN) ---\n\n"
for f in funcs:
    # 1. Base URL paths
    # @admin_bp.route('/results...') -> @hod_bp.route('/analyze...')
    f = f.replace("admin_bp.route('/results", "hod_bp.route('/analyze")
    f = f.replace("admin_bp.route('/results/", "hod_bp.route('/analyze/")
    
    # 2. Template extensions
    f = f.replace("'admin/results_sessions.html'", "'hod/analyze_sessions.html'")
    f = f.replace("'admin/session_teachers.html'", "'hod/analyze_session_teachers.html'")
    f = f.replace("'admin/teacher_report.html'", "'hod/analyze_teacher_report.html'")
    f = f.replace("'admin/subject_report.html'", "'hod/analyze_subject_report.html'")
    
    # 3. Auth
    f = f.replace("if session.get('role') != 'admin': return redirect(url_for('auth.login'))", "if session.get('role') != 'HOD': return redirect(url_for('auth.management_login'))")
    
    # 4. Function name renaming to avoid collisions
    f = f.replace("def view_results(", "def analyze(")
    f = f.replace("def session_teachers(", "def analyze_session_teachers(")
    f = f.replace("def teacher_report(", "def analyze_teacher_report(")
    f = f.replace("def subject_report(", "def analyze_subject_report(")
    
    out += f + "\n"

with open('app/routes/hod_routes.py', 'a', encoding='utf-8') as f:
    f.write(out)

print("Routes injected.")
