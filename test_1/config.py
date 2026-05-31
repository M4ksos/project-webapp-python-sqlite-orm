import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-change-in-production')
    # Для SQLite (простой старт):
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///attendance.db')
    # Для PostgreSQL раскомментируй:
    # SQLALCHEMY_DATABASE_URI = 'postgresql://user:password@localhost/attendance_db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ESP_API_KEY = os.getenv('ESP_API_KEY', 'esp-secret-key-123')  # ключ для ESP32
