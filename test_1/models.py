from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name     = db.Column(db.String(100), nullable=False)
    role          = db.Column(db.String(20), nullable=False, default='student')
    approved      = db.Column(db.Boolean, default=False)
    student_id    = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=True)

    # subjects добавляется автоматически через backref в Subject.teacher

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):    return self.role == 'admin'
    def is_teacher(self):  return self.role == 'teacher'
    def is_student(self):  return self.role == 'student'

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class Group(db.Model):
    __tablename__ = 'groups'

    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(30), unique=True, nullable=False)
    students = db.relationship('Student', backref='group', lazy=True)

    def __repr__(self):
        return f'<Group {self.name}>'


class Student(db.Model):
    __tablename__ = 'students'

    id             = db.Column(db.Integer, primary_key=True)
    rfid_uid       = db.Column(db.String(50), unique=True, nullable=False)
    full_name      = db.Column(db.String(100), nullable=False)
    student_number = db.Column(db.String(20), unique=True, nullable=False)
    group_id       = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    active         = db.Column(db.Boolean, default=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # один студент — один пользователь
    user = db.relationship(
        'User',
        foreign_keys=[user_id],
        backref=db.backref('student_record', uselist=False)
    )

    attendances = db.relationship('Attendance', backref='student', lazy=True)

    def __repr__(self):
        return f'<Student {self.full_name}>'


class Subject(db.Model):
    __tablename__ = 'subjects'

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # через backref='subjects' создаёт user.subjects автоматически
    teacher  = db.relationship(
        'User',
        foreign_keys=[teacher_id],
        backref=db.backref('subjects', lazy=True)
    )
    lectures = db.relationship('Lecture', backref='subject', lazy=True)

    def __repr__(self):
        return f'<Subject {self.name}>'


class Lecture(db.Model):
    __tablename__ = 'lectures'

    id         = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    group_id   = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    date       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    room       = db.Column(db.String(20))
    is_open    = db.Column(db.Boolean, default=True)

    group       = db.relationship('Group', backref='lectures')
    attendances = db.relationship('Attendance', backref='lecture', lazy=True)

    def attended_count(self):
        return sum(1 for a in self.attendances if a.source != 'absent')

    def __repr__(self):
        return f'<Lecture {self.subject.name} {self.date}>'


class Attendance(db.Model):
    __tablename__ = 'attendance'

    id         = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    lecture_id = db.Column(db.Integer, db.ForeignKey('lectures.id'), nullable=False)
    timestamp  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    source     = db.Column(db.String(20), default='manual')
    # source: 'manual' — вручную, 'absent' — пропуск, 'rfid' — от ESP32

    __table_args__ = (
        db.UniqueConstraint('student_id', 'lecture_id', name='unique_attendance'),
    )

    def __repr__(self):
        return f'<Attendance student={self.student_id} lecture={self.lecture_id}>'