import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

# Load variables from the .env file
load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'fallback_secret_key') 
    
    # Fetch Database Credentials from Environment
    DB_USERNAME = os.getenv('DB_USERNAME')
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    DB_HOST = os.getenv('DB_HOST')
    DB_NAME = os.getenv('DB_NAME')
    
    # Safe Encoding
    encoded_password = quote_plus(DB_PASSWORD) if DB_PASSWORD else ""
    
    # SQLAlchemy Config
    SQLALCHEMY_DATABASE_URI = f'mysql+pymysql://{DB_USERNAME}:{encoded_password}@{DB_HOST}/{DB_NAME}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_recycle': 280}