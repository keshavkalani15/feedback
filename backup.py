"""
Daily SQL Backup Script
-----------------------
- Dumps the MySQL database to a .sql file
- Stores backups in the 'backups/' folder
- File name format: backup_YYYY-MM-DD.sql
- Keeps only the last 7 days of backups (oldest auto-deleted)

Usage:
  - Run manually:    python backup.py
  - Auto-scheduled:  Called from serve.py on server startup + every 24 hours
"""

import os
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
MAX_BACKUPS = 7

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_USER = os.getenv('DB_USERNAME', 'root')
DB_PASS = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'feedback_db')


def run_backup():
    """Create a SQL dump and clean up old backups."""
    os.makedirs(BACKUP_DIR, exist_ok=True)

    today = datetime.now().strftime('%Y-%m-%d')
    filename = f'backup_{today}.sql'
    filepath = os.path.join(BACKUP_DIR, filename)

    # Skip if today's backup already exists
    if os.path.exists(filepath):
        print(f"📁 Backup already exists for today: {filename}")
        return True

    # --- 1. Run mysqldump ---
    cmd = [
        'mysqldump',
        f'--host={DB_HOST}',
        f'--user={DB_USER}',
        f'--password={DB_PASS}',
        '--single-transaction',
        '--routines',
        '--triggers',
        DB_NAME
    ]

    try:
        print(f"💾 Creating backup: {filename} ...")
        with open(filepath, 'w', encoding='utf-8') as f:
            result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, timeout=120)

        if result.returncode != 0:
            err = result.stderr.decode('utf-8', errors='replace').strip()
            # mysqldump password warning is not a real error
            if 'Using a password on the command line' in err:
                print(f"✅ Backup created: {filename}")
            else:
                print(f"❌ mysqldump error: {err}")
                # Remove empty/failed file
                if os.path.exists(filepath):
                    os.remove(filepath)
                return False
        else:
            print(f"✅ Backup created: {filename}")

    except FileNotFoundError:
        print("❌ 'mysqldump' not found! Make sure MySQL bin folder is in your system PATH.")
        print("   Typical path: C:\\Program Files\\MySQL\\MySQL Server 8.0\\bin")
        return False
    except subprocess.TimeoutExpired:
        print("❌ Backup timed out (>120 seconds).")
        return False
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return False

    # --- 2. Clean up old backups (keep only last 7) ---
    cleanup_old_backups()
    return True


def cleanup_old_backups():
    """Delete backup files older than MAX_BACKUPS days."""
    if not os.path.exists(BACKUP_DIR):
        return

    backup_files = []
    for f in os.listdir(BACKUP_DIR):
        if f.startswith('backup_') and f.endswith('.sql'):
            try:
                date_str = f.replace('backup_', '').replace('.sql', '')
                file_date = datetime.strptime(date_str, '%Y-%m-%d')
                backup_files.append((file_date, f))
            except ValueError:
                continue

    # Sort by date (newest first)
    backup_files.sort(key=lambda x: x[0], reverse=True)

    # Delete files beyond the retention limit
    for file_date, filename in backup_files[MAX_BACKUPS:]:
        path = os.path.join(BACKUP_DIR, filename)
        os.remove(path)
        print(f"🗑️  Deleted old backup: {filename}")


if __name__ == '__main__':
    print("=" * 40)
    print("   FeedBack App - Database Backup")
    print("=" * 40)
    run_backup()
