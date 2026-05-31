from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime
from functools import wraps

from config import Config
from models import db, User, Student, Group, Subject, Lecture, Attendance

# ──────────────────────────────────────────
#  Само  приложение
# ──────────────────────────────────────────

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# ──────────────────────────────────────────
#  
# ──────────────────────────────────────────


WEEKDAYS_RU = {
    0: 'Понедельник',
    1: 'Вторник',
    2: 'Среда',
    3: 'Четверг',
    4: 'Пятница',
    5: 'Суббота',
}

def group_by_weekday(lectures):
    """
    Возвращает OrderedDict:
    { 0: {'name': 'Понедельник', 'lectures': [...]}, ... }
    Только дни у которых есть хотя бы одна лекция, пн→сб.
    """
    from collections import OrderedDict
    result = OrderedDict()
    for lec in lectures:
        wd = lec.date.weekday()   # 0=пн, 5=сб, 6=вс
        if wd == 6:               # воскресенье пропускаем
            continue
        if wd not in result:
            result[wd] = {'name': WEEKDAYS_RU[wd], 'lectures': []}
        result[wd]['lectures'].append(lec)
    # Сортируем по номеру дня
    return OrderedDict(sorted(result.items()))


login_manager = LoginManager(app)
login_manager.login_view    = 'login'
login_manager.login_message = 'Войдите в систему'

# ──────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНЫЕ ДЕКОРАТОРЫ
# ──────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def admin_required(f):
    """Только администратор."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return decorated


def teacher_or_admin(f):
    """Преподаватель или администратор."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(403)
        if current_user.role not in ('teacher', 'admin'):
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ──────────────────────────────────────────
#  АУТЕНТИФИКАЦИЯ
# ──────────────────────────────────────────

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Неверный логин или пароль', 'error')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    groups   = Group.query.all()
    students = Student.query.filter_by(active=True).all()

    if request.method == 'POST':
        username  = request.form.get('username', '').strip()
        password  = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        full_name = request.form.get('full_name', '').strip()
        role      = request.form.get('role', 'student')

        # Валидация
        if not all([username, password, full_name]):
            flash('Заполните все обязательные поля', 'error')
            return render_template('register.html', groups=groups, students=students)

        if password != password2:
            flash('Пароли не совпадают', 'error')
            return render_template('register.html', groups=groups, students=students)

        if len(password) < 6:
            flash('Пароль должен быть не менее 6 символов', 'error')
            return render_template('register.html', groups=groups, students=students)

        if User.query.filter_by(username=username).first():
            flash('Пользователь с таким логином уже существует', 'error')
            return render_template('register.html', groups=groups, students=students)

        # Роль может быть только student или teacher при самостоятельной регистрации
        if role not in ('student', 'teacher'):
            role = 'student'

        user = User(username=username, full_name=full_name, role=role, approved=True)
        user.set_password(password)

        # Для студента — привязываем к записи Student по номеру зачётки
        if role == 'student':
            student_id = request.form.get('student_id', type=int)
            if student_id:
                student_rec = Student.query.get(student_id)
                if student_rec and student_rec.user is None:
                    user.student_id = student_rec.id
                else:
                    flash('Эта запись студента уже привязана к другому аккаунту', 'error')
                    return render_template('register.html', groups=groups, students=students)

        db.session.add(user)
        db.session.commit()
        flash('Регистрация прошла успешно! Войдите в систему.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', groups=groups, students=students)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ──────────────────────────────────────────
#  ДАШБОРД — общая точка входа
# ──────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    """Перенаправляет на нужную страницу в зависимости от роли."""
    if current_user.is_admin():
        return redirect(url_for('admin_panel'))
    if current_user.is_teacher():
        return redirect(url_for('teacher_dashboard'))
    # student
    return redirect(url_for('student_schedule'))


# ──────────────────────────────────────────
#  ПРЕПОДАВАТЕЛЬ
# ──────────────────────────────────────────

@app.route('/teacher')
@login_required
@teacher_or_admin
def teacher_dashboard():
    """Список лекций преподавателя."""
    if current_user.is_admin():
        lectures = Lecture.query.order_by(Lecture.date.desc()).limit(30).all()
    else:
        subject_ids = [s.id for s in current_user.subjects]
        lectures = (Lecture.query
                    .filter(Lecture.subject_id.in_(subject_ids))
                    .order_by(Lecture.date.desc())
                    .limit(30).all())

    groups   = Group.query.all()
    subjects = Subject.query.all() if current_user.is_admin() else current_user.subjects
    return render_template('teacher_dashboard.html',
                           lectures=lectures, groups=groups, subjects=subjects)


@app.route('/lecture/<int:lecture_id>')
@login_required
@teacher_or_admin
def lecture_detail(lecture_id):
    """Кто пришёл / кто нет. Ручная отметка пропусков."""
    lecture     = Lecture.query.get_or_404(lecture_id)
    all_students = Student.query.filter_by(group_id=lecture.group_id, active=True).all()
    attended_ids = {a.student_id for a in lecture.attendances}
    present      = [s for s in all_students if s.id in attended_ids]
    absent       = [s for s in all_students if s.id not in attended_ids]
    attendance_map = {a.student_id: a for a in lecture.attendances}

    return render_template('lecture_detail.html',
                           lecture=lecture,
                           present=present,
                           absent=absent,
                           attendance_map=attendance_map,
                           total=len(all_students))


@app.route('/attendance/manual', methods=['POST'])
@login_required
@teacher_or_admin
def manual_attendance():
    """Преподаватель вручную ставит отметку или пропуск."""
    lecture_id = request.form.get('lecture_id', type=int)
    student_id = request.form.get('student_id', type=int)
    action     = request.form.get('action', 'add')   # add | remove | absent

    if action == 'add':
        existing = Attendance.query.filter_by(
            student_id=student_id, lecture_id=lecture_id).first()
        if not existing:
            db.session.add(Attendance(student_id=student_id,
                                      lecture_id=lecture_id, source='manual'))
            db.session.commit()
            flash('Посещение добавлено', 'success')
        else:
            flash('Студент уже отмечен', 'info')

    elif action == 'absent':
        # Пропуск — записываем с source='absent'
        existing = Attendance.query.filter_by(
            student_id=student_id, lecture_id=lecture_id).first()
        if existing:
            existing.source = 'absent'
        else:
            db.session.add(Attendance(student_id=student_id,
                                      lecture_id=lecture_id, source='absent'))
        db.session.commit()
        flash('Пропуск поставлен', 'info')

    elif action == 'remove':
        Attendance.query.filter_by(
            student_id=student_id, lecture_id=lecture_id).delete()
        db.session.commit()
        flash('Отметка удалена', 'info')

    return redirect(url_for('lecture_detail', lecture_id=lecture_id))


@app.route('/lecture/<int:lid>/toggle', methods=['POST'])
@login_required
@teacher_or_admin
def toggle_lecture(lid):
    lecture = Lecture.query.get_or_404(lid)
    lecture.is_open = not lecture.is_open
    db.session.commit()
    flash('Регистрация ' + ('открыта' if lecture.is_open else 'закрыта'), 'info')
    return redirect(url_for('lecture_detail', lecture_id=lid))


# ──────────────────────────────────────────
#  СТУДЕНТ — расписание и своя посещаемость
# ──────────────────────────────────────────

@app.route('/schedule')
@login_required
def student_schedule():
    now = datetime.now()

    # ── Преподаватель ──
    if current_user.is_teacher():
        # current_user.subjects — это предметы где teacher_id = current_user.id
        subject_ids = [s.id for s in current_user.subjects]
        if subject_ids:
            lectures = (Lecture.query
                        .filter(Lecture.subject_id.in_(subject_ids))
                        .order_by(Lecture.date.asc()).all())
        else:
            lectures = []
        return render_template('schedule.html',
                               schedule=group_by_weekday(lectures),
                               student_record=None,
                               attendance_ids=set(),
                               now=now)

    # ── Администратор ──
    if current_user.is_admin():
        lectures = Lecture.query.order_by(Lecture.date.asc()).all()
        return render_template('schedule.html',
                               schedule=group_by_weekday(lectures),
                               student_record=None,
                               attendance_ids=set(),
                               now=now)

    # ── Студент ──
    student_rec = getattr(current_user, 'student_record', None)
    if student_rec:
        lectures = (Lecture.query
                    .filter_by(group_id=student_rec.group_id)
                    .order_by(Lecture.date.asc()).all())
        attendance_ids = {a.lecture_id for a in student_rec.attendances}
    else:
        lectures      = []
        attendance_ids = set()

    return render_template('schedule.html',
                           schedule=group_by_weekday(lectures),
                           student_record=student_rec,
                           attendance_ids=attendance_ids,
                           now=now)

@app.route('/schedule/table')
@login_required
def schedule_table():

    if not current_user.is_student():
        return render_template('schedule_table.html')

    return render_template('schedule_table.html')


# ──────────────────────────────────────────
#  АДМИНИСТРАТОР
# ──────────────────────────────────────────

@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    users    = User.query.order_by(User.approved, User.role).all()
    students = Student.query.order_by(Student.full_name).all()
    groups   = Group.query.all()
    subjects = Subject.query.all()
    lectures = Lecture.query.order_by(Lecture.date.desc()).all()
    teachers = User.query.filter_by(role='teacher', approved=True).all()
    return render_template('admin.html',
                           users=users, students=students, groups=groups,
                           subjects=subjects, lectures=lectures, teachers=teachers)


# --- Управление пользователями ---

@app.route('/admin/user/<int:uid>/approve', methods=['POST'])
@login_required
@admin_required
def approve_user(uid):
    user = User.query.get_or_404(uid)
    user.approved = True
    db.session.commit()
    flash(f'Пользователь {user.full_name} подтверждён', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/student/<int:sid>/profile')
@login_required
@admin_required
def student_profile(sid):
    student  = Student.query.get_or_404(sid)
    lectures = (Lecture.query
                .filter_by(group_id=student.group_id)
                .order_by(Lecture.date.desc()).all())

    # Карта: lecture_id → запись посещаемости
    att_map  = {a.lecture_id: a for a in student.attendances}

    total    = len(lectures)
    attended = sum(1 for l in lectures
                   if att_map.get(l.id) and att_map[l.id].source != 'absent')
    absent   = sum(1 for l in lectures
                   if att_map.get(l.id) and att_map[l.id].source == 'absent')
    unmarked = total - attended - absent
    pct      = int(attended / total * 100) if total > 0 else 0

    return render_template('student_profile.html',
                           student=student,
                           lectures=lectures,
                           att_map=att_map,
                           total=total,
                           attended=attended,
                           absent=absent,
                           unmarked=unmarked,
                           pct=pct)

@app.route('/admin/user/<int:uid>/role', methods=['POST'])
@login_required
@admin_required
def change_role(uid):
    user    = User.query.get_or_404(uid)
    new_role = request.form.get('role', 'student')
    if new_role not in ('admin', 'teacher', 'student'):
        flash('Неверная роль', 'error')
        return redirect(url_for('admin_panel'))
    if user.id == current_user.id:
        flash('Нельзя изменить свою роль', 'error')
        return redirect(url_for('admin_panel'))
    user.role = new_role
    db.session.commit()
    flash(f'Роль {user.full_name} изменена на «{new_role}»', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/user/<int:uid>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(uid):
    user = User.query.get_or_404(uid)
    if user.id == current_user.id:
        flash('Нельзя удалить себя', 'error')
        return redirect(url_for('admin_panel'))
    db.session.delete(user)
    db.session.commit()
    flash(f'Пользователь удалён', 'info')
    return redirect(url_for('admin_panel'))

@app.route('/admin/student/<int:sid>/change_group', methods=['POST'])
@login_required
@admin_required
def change_student_group(sid):
    student  = Student.query.get_or_404(sid)
    group_id = request.form.get('group_id', type=int)
    if not group_id:
        flash('Выберите группу', 'error')
        return redirect(url_for('admin_panel'))
    group = Group.query.get_or_404(group_id)
    old_group = student.group.name
    student.group_id = group_id
    db.session.commit()
    flash(f'{student.full_name} переведён из {old_group} в {group.name}', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/user/<int:uid>/link_student', methods=['POST'])
@login_required
@admin_required
def link_student(uid):
    user = User.query.get_or_404(uid)
    student_id = request.form.get('student_id', type=int)
    if not student_id:
        flash('Выберите студента', 'error')
        return redirect(url_for('admin_panel'))

    student = Student.query.get_or_404(student_id)

    # Убрать старую привязку если была
    old = Student.query.filter_by(user_id=user.id).first()
    if old:
        old.user_id = None

    student.user_id = user.id
    db.session.commit()
    flash(f'{student.full_name} привязан к {user.username}', 'success')
    return redirect(url_for('admin_panel'))


# --- Студенты ---

@app.route('/admin/student/add', methods=['POST'])
@login_required
@admin_required
def add_student():
    rfid     = request.form.get('rfid_uid', '').strip().upper()
    name     = request.form.get('full_name', '').strip()
    number   = request.form.get('student_number', '').strip()
    group_id = request.form.get('group_id', type=int)

    if not all([rfid, name, number, group_id]):
        flash('Заполните все поля', 'error')
        return redirect(url_for('admin_panel'))

    if Student.query.filter_by(rfid_uid=rfid).first():
        flash(f'Карта {rfid} уже зарегистрирована', 'error')
        return redirect(url_for('admin_panel'))

    db.session.add(Student(rfid_uid=rfid, full_name=name,
                           student_number=number, group_id=group_id))
    db.session.commit()
    flash(f'Студент {name} добавлен', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/student/<int:sid>/delete', methods=['POST'])
@login_required
@admin_required
def delete_student(sid):
    student = Student.query.get_or_404(sid)
    # Сначала удаляем все отметки посещаемости студента
    Attendance.query.filter_by(student_id=student.id).delete()
    # Если привязан аккаунт — отвязываем
    if student.user:
        student.user.student_id = None
    db.session.delete(student)
    db.session.commit()
    flash(f'Студент {student.full_name} удалён', 'info')
    return redirect(url_for('admin_panel'))


# --- Группы ---

@app.route('/admin/group/add', methods=['POST'])
@login_required
@admin_required
def add_group():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Введите название группы', 'error')
        return redirect(url_for('admin_panel'))
    if Group.query.filter_by(name=name).first():
        flash(f'Группа {name} уже существует', 'error')
        return redirect(url_for('admin_panel'))
    db.session.add(Group(name=name))
    db.session.commit()
    flash(f'Группа {name} создана', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/group/<int:gid>/delete', methods=['POST'])
@login_required
@admin_required
def delete_group(gid):
    group = Group.query.get_or_404(gid)
    # Нельзя удалить если есть студенты
    active_students = Student.query.filter_by(
        group_id=gid, active=True).count()
    if active_students > 0:
        flash(f'Нельзя удалить группу «{group.name}» — '
              f'в ней {active_students} студентов. '
              f'Сначала удалите или переведите студентов.', 'error')
        return redirect(url_for('admin_panel'))
    # Нельзя удалить если есть лекции
    lectures_count = Lecture.query.filter_by(group_id=gid).count()
    if lectures_count > 0:
        flash(f'Нельзя удалить группу «{group.name}» — '
              f'к ней привязаны лекции ({lectures_count} шт.).', 'error')
        return redirect(url_for('admin_panel'))
    db.session.delete(group)
    db.session.commit()
    flash(f'Группа «{group.name}» удалена', 'info')
    return redirect(url_for('admin_panel'))

# --- Предметы ---

@app.route('/admin/subject/add', methods=['POST'])
@login_required
@admin_required
def add_subject():
    name       = request.form.get('name', '').strip()
    teacher_id = request.form.get('teacher_id', type=int)
    if not name:
        flash('Введите название предмета', 'error')
        return redirect(url_for('admin_panel'))
    db.session.add(Subject(name=name, teacher_id=teacher_id or None))
    db.session.commit()
    flash(f'Предмет «{name}» добавлен', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/subject/<int:sid>/delete', methods=['POST'])
@login_required
@admin_required
def delete_subject(sid):
    subject = Subject.query.get_or_404(sid)
    # Проверяем — есть ли лекции по этому предмету
    if subject.lectures:
        flash(f'Нельзя удалить предмет «{subject.name}» — '
              f'к нему привязаны лекции ({len(subject.lectures)} шт.). '
              f'Сначала удалите лекции.', 'error')
        return redirect(url_for('admin_panel'))
    db.session.delete(subject)
    db.session.commit()
    flash(f'Предмет «{subject.name}» удалён', 'info')
    return redirect(url_for('admin_panel'))

# --- Лекции ---

@app.route('/admin/lecture/add', methods=['POST'])
@login_required
@admin_required
def add_lecture():
    subject_id = request.form.get('subject_id', type=int)
    group_id   = request.form.get('group_id', type=int)
    date_str   = request.form.get('date', '')
    time_str   = request.form.get('time', '')
    room       = request.form.get('room', '').strip()

    if not date_str or not time_str:
        flash('Укажите дату и время', 'error')
        return redirect(url_for('admin_panel'))

    try:
        date = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
    except ValueError:
        flash('Неверный формат даты или времени', 'error')
        return redirect(url_for('admin_panel'))

    db.session.add(Lecture(subject_id=subject_id, group_id=group_id,
                           date=date, room=room))
    db.session.commit()
    flash('Лекция создана', 'success')
    return redirect(url_for('admin_panel'))


# ──────────────────────────────────────────
#  REST API ДЛЯ ESP32
# ──────────────────────────────────────────

def require_esp_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.headers.get('X-ESP-Key', '') != app.config['ESP_API_KEY']:
            return jsonify({'error': 'unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


@app.route('/api/checkin', methods=['POST'])
@require_esp_key
def api_checkin():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'invalid json'}), 400

    rfid = data.get('rfid_uid', '').strip().upper()
    room = data.get('room', '').strip()

    student = Student.query.filter_by(rfid_uid=rfid, active=True).first()
    if not student:
        return jsonify({'status': 'unknown_card', 'rfid': rfid}), 404

    lecture = (Lecture.query
               .filter_by(group_id=student.group_id, is_open=True, room=room)
               .order_by(Lecture.date.desc()).first())
    if not lecture:
        return jsonify({'status': 'no_open_lecture',
                        'student': student.full_name}), 404

    existing = Attendance.query.filter_by(
        student_id=student.id, lecture_id=lecture.id).first()
    if existing:
        return jsonify({'status': 'already_checked',
                        'student': student.full_name,
                        'time': existing.timestamp.strftime('%H:%M')}), 200

    record = Attendance(student_id=student.id,
                        lecture_id=lecture.id, source='rfid')
    db.session.add(record)
    db.session.commit()

    return jsonify({'status': 'ok',
                    'student': student.full_name,
                    'group':   student.group.name,
                    'subject': lecture.subject.name,
                    'time':    record.timestamp.strftime('%H:%M')}), 200


@app.route('/api/status', methods=['GET'])
@require_esp_key
def api_status():
    room = request.args.get('room', '')
    lecture = (Lecture.query.filter_by(is_open=True, room=room)
               .order_by(Lecture.date.desc()).first())
    if lecture:
        return jsonify({'open': True, 'subject': lecture.subject.name,
                        'group': lecture.group.name,
                        'date':  lecture.date.strftime('%d.%m.%Y %H:%M')})
    return jsonify({'open': False})


# ──────────────────────────────────────────
#  ОБРАБОТЧИКИ ОШИБОК
# ──────────────────────────────────────────

@app.context_processor
def inject_globals():
    """Переменные доступные во всех шаблонах."""
    return {'now': datetime.now()}


@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403,
                           message='Доступ запрещён'), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404,
                           message='Страница не найдена'), 404


# ──────────────────────────────────────────
#  SEED — ТЕСТОВЫЕ ДАННЫЕ
# ──────────────────────────────────────────

def seed_database():
    if User.query.first():
        return

    # --- Пользователи ---

    admin = User(username='admin', full_name='Администратор',
                 role='admin', approved=True)
    admin.set_password('admin123')

    teacher = User(username='kovalev', full_name='Ковалёв Олег Фёдорович',
                   role='teacher', approved=True)
    teacher.set_password('kovalev123')

    db.session.add_all([admin, teacher])
    db.session.flush()

    # --- Группы ---
    
    g1 = Group(name='group-1')
    g2 = Group(name='group-2')
    g3 = Group(name='group-3')
    g4 = Group(name='group-4')
    db.session.add_all([g1, g2, g3, g4])
    db.session.flush()

    # --- Предмет ---

    subj = Subject(name='Базы данных', teacher_id=teacher.id)
    db.session.add(subj)
    db.session.flush()

    # --- Студенты ---
    
    students_data = [
        ('AA:BB:CC:01', 'Алексеев Антон Игоревич',    '2021001', g1.id),
        ('AA:BB:CC:02', 'Борисова Мария Сергеевна',   '2021002', g1.id),
        ('AA:BB:CC:03', 'Васильев Дмитрий Олегович',  '2021003', g2.id),
        ('AA:BB:CC:04', 'Григорьева Анна Павловна',   '2021004', g2.id),
        ('AA:BB:DD:01', 'Денисов Илья Андреевич',     '2022001', g3.id),
        ('AA:BB:DD:02', 'Егоров Кирилл Максимович',   '2022002', g3.id),
        ('AA:BB:DD:03', 'Жукова Полина Вячеславовна', '2022003', g4.id),
        ('AA:BB:DD:04', 'Жукова Полина Вячеславовна', '2022004', g4.id)
    ]
    student_objs = []
    for rfid, name, num, gid in students_data:
        s = Student(rfid_uid=rfid, full_name=name, student_number=num, group_id=gid)
        db.session.add(s)
        student_objs.append(s)
    db.session.flush()

    # --- Студент-пользователь (привязан к первому студенту) ---
    
    stu_user = User(username='alekseev', full_name='Алексеев Антон Игоревич',
                    role='student', approved=True, student_id=student_objs[0].id)
    stu_user.set_password('student123')
    db.session.add(stu_user)

    # --- Лекции ---
    lec1 = Lecture(subject_id=subj.id, group_id=g1.id,
                   date=datetime.now(), room='302', is_open=True)
    lec2 = Lecture(subject_id=subj.id, group_id=g1.id,
                   date=datetime(2025, 4, 28, 9, 0), room='302', is_open=False)
    db.session.add_all([lec1, lec2])
    db.session.flush()

    # --- Отметки ---
    for s in student_objs[:3]:
        db.session.add(Attendance(student_id=s.id,
                                  lecture_id=lec1.id, source='rfid'))
    # --- Пропуск у 4-го студента на прошлой лекции ---
    db.session.add(Attendance(student_id=student_objs[3].id,
                              lecture_id=lec2.id, source='absent'))

    db.session.commit()
    print('✓ База данных заполнена тестовыми данными')
    print('  admin / admin123')
    print('  ivanov / teacher123  (преподаватель)')
    print('  alekseev / student123  (студент)')

# ──────────────────────────────────────────
#  запуск приложение
#  создание бд и загрузка данных
#  задание параметров
# ──────────────────────────────────────────


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_database()
    app.run(debug=True, host='0.0.0.0', port=5000)
