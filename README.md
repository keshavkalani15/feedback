# FeedBack Project

A comprehensive, role-based academic feedback system built with Flask, SQLAlchemy, and MySQL. This application facilitates student feedback collection, teacher evaluation, and administrative reporting across four distinct roles: **Admin**, **HOD**, **Teacher**, and **Student**.

## Features

- **Multi-Role Authentication**: Dedicated portals for Admins, HODs, Teachers, and Students.
- **Dynamic Feedback Forms**: Automatically generated forms based on student class and elective subjects.
- **Anonymous Feedback**: Token-based submission system ensures complete student anonymity.
- **Class & Subject Management**: Bulk CSV upload support for importing students, teachers, and subjects.
- **Automated Reporting**: Real-time generation of feedback scores and subjective comments for HOD review.
- **Production-Ready Security**: Global CSRF protection, PBKDF2 password hashing, and role-based route locking.

## Prerequisites

Before running the application, ensure you have the following installed:

1. **Python 3.8+**
2. **MySQL Server** (XAMPP/WAMP or native installation)
3. **pip** (Python package installer)

---

## 🚀 Installation & Setup

### 1. Clone the Repository
```bash
git clone <your-repository-url>
cd FeedBack_Project
```

### 2. Create a Virtual Environment (Recommended)
```bash
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Database Setup
Create a `.env` file in the root directory of the project and add your MySQL database credentials. The app will automatically create the database and tables on startup if they don't exist.

```env
DB_HOST=localhost
DB_USERNAME=root
DB_PASSWORD=your_mysql_password
DB_NAME=feedback_db
SECRET_KEY=generate_a_strong_random_secret_key
```
*(Note: If your local MySQL doesn't use a password, leave `DB_PASSWORD=` blank)*

---

## 🛠️ Usage

### Development Server (For Testing)
If you want to run the application in debug mode for development:
```bash
python run.py
```
*Access the app at: `http://127.0.0.1:5000`*

### Production Server (For Local Deployment)
For actual deployment or allowing multiple students to access the app concurrently over your local network:
```bash
python serve.py
```
*Access the app at: `http://0.0.0.0:80` (or `5000` depending on port availability). You can share your computer's IP address (e.g., `http://192.168.x.x`) with students to access the portal.*

---

## 🔐 Default Credentials

To get started, the system requires an initial **HOD (Head of Department)** or **Admin**.

You can run the `create_hod.py` script to generate the root user:
```bash
python create_hod.py
```
*(Make sure to update the script with your desired HOD credentials before running).*

Once the HOD is created, they can log into the **Management Portal** to create Admins. Admins can then create Teachers and Subjects.

### Important Routes
- **Main Portal**: `http://localhost/login` (For Admins, Teachers, and Students)
- **HOD Portal**: `http://localhost/management_login` (Strictly for HODs)

---

## 📂 Project Structure

```text
FeedBack_Project/
├── app/
│   ├── routes/              # Route controllers (admin, hod, student, teacher)
│   ├── templates/           # Jinja2 HTML templates
│   ├── __init__.py          # Flask app application factory & CSRF setup
│   ├── models.py            # SQLAlchemy Database Models
│   └── utils.py             # Helper logic for loading feedback JSON questions
├── feedback_questions.json  # Configurable feedback questions for the forms
├── config.py                # Environment and Database configuration
├── run.py                   # Development server entry point
├── serve.py                 # Production Waitress WSGI server entry point
└── requirements.txt         # Python dependencies
```

## Security Notes
- **Do not commit `.env` to version control.**
- **Default Passwords**: When Admins create Teachers, the default password is `{EmpID}@123` (e.g., `T101@123`). Force users to change this upon first login.
- **Destructive Actions**: Deleting subjects or teachers cascades to delete historical feedback data. These actions are locked behind mandatory Admin password prompts.
