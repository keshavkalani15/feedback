import os, re

templates_dir = r'c:\Users\Keshav Kalani\Desktop\FeedBack_Project\app\templates'

# Files we've already handled manually
done = {'login.html', 'management_login.html', 'student.html', 
        'admin\\manage_teachers.html', 'admin\\manage_subjects.html'}

csrf_tag = '<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">'

count = 0
for root, dirs, files in os.walk(templates_dir):
    for f in files:
        if not f.endswith('.html'): continue
        rel = os.path.relpath(os.path.join(root, f), templates_dir)
        if rel in done: continue
        
        full = os.path.join(root, f)
        with open(full, 'r', encoding='utf-8') as fh:
            content = fh.read()
        
        if csrf_tag in content:
            continue  # already has it
        
        # Match form tags with method=POST (case-insensitive)
        pattern = r'(<form[^>]*method=["\']POST["\'][^>]*>)'
        matches = list(re.finditer(pattern, content, re.IGNORECASE))
        
        if not matches:
            continue
        
        # Insert csrf_tag after each form opening tag (from end to preserve positions)
        for m in reversed(matches):
            insert_pos = m.end()
            # Figure out indentation
            line_start = content.rfind('\n', 0, m.start()) + 1
            indent = ''
            for ch in content[line_start:]:
                if ch in ' \t': indent += ch
                else: break
            content = content[:insert_pos] + '\n' + indent + '    ' + csrf_tag + content[insert_pos:]
            count += 1
        
        with open(full, 'w', encoding='utf-8') as fh:
            fh.write(content)
        
        print(f'Updated: {rel} ({len(matches)} forms)')

print(f'\nTotal forms updated: {count}')
