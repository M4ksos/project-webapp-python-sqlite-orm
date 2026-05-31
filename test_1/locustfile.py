from locust import HttpUser, task, between

class TeacherUser(HttpUser):
    """
    Имитирует преподавателя:
    входит в систему и смотрит лекции.
    """
    wait_time = between(1, 3)  # пауза между действиями 1-3 сек

    def on_start(self):
        """Вызывается один раз при старте — вход в систему."""
        self.client.post('/login', data={
            'username': 'ivanov',
            'password': 'teacher123'
        })

    @task(3)
    def view_lectures(self):
        """Открыть список лекций (чаще всего)."""
        self.client.get('/teacher')

    @task(2)
    def view_schedule(self):
        """Открыть расписание."""
        self.client.get('/schedule')

    @task(1)
    def view_lecture_detail(self):
        """Открыть детали лекции."""
        self.client.get('/lecture/1')

    def on_stop(self):
        """Выйти из системы."""
        self.client.get('/logout')


class StudentUser(HttpUser):
    """
    Имитирует студента:
    входит и смотрит расписание.
    """
    wait_time = between(2, 5)

    def on_start(self):
        self.client.post('/login', data={
            'username': 'alekseev',
            'password': 'student123'
        })

    @task
    def view_schedule(self):
        self.client.get('/schedule')

    def on_stop(self):
        self.client.get('/logout')


class AdminUser(HttpUser):
    """
    Имитирует администратора:
    заходит в панель управления.
    """
    wait_time = between(3, 6)

    def on_start(self):
        self.client.post('/login', data={
            'username': 'admin',
            'password': 'admin123'
        })

    @task
    def view_admin_panel(self):
        self.client.get('/admin')

    def on_stop(self):
        self.client.get('/logout')