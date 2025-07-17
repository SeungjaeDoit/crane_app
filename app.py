from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.permanent_session_lifetime = timedelta(days=7)

users = {
    "boss": {"password": "1234", "role": "boss", "company": "default"},
    "crane1": {"password": "1111", "role": "worker", "company": "default"},
    "crane2": {"password": "2222", "role": "worker", "company": "default"},
}

jobs = {"default": []}
workers = {"default": []}
machines = {"default": []}
clients = {"default": []}

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if username in users and users[username]['password'] == password:
            session.permanent = True
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            error = '아이디 또는 비밀번호가 틀렸습니다.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    role = users[username]['role']

    if role == 'boss':
        return render_template('dashboard.html', username=username)
    else:
        return render_template('worker_dashboard.html', username=username)

@app.route('/create_job', methods=['GET', 'POST'])
def create_job():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    company = users[username]['company']

    if request.method == 'POST':
        date = request.form.get('date')
        hour = request.form.get('hour')
        minute = request.form.get('minute')
        time_str = f"{date} {hour}시 {minute}분"

        worker = request.form.get('worker_input') or request.form.get('worker_select')
        machine = request.form.get('machine_input') or request.form.get('machine_select')
        client = request.form.get('client_input') or request.form.get('client_select')

        if client and client not in clients[company]:
            clients[company].append(client)

        job = {
            'date': date,
            'time': time_str,
            'worker': worker,
            'machine': machine,
            'client': client,
            'location': request.form.get('location'),
            'note': request.form.get('note')
        }
        jobs[company].append(job)
        return redirect(url_for('list_jobs'))

    return render_template('create_job.html', workers=workers[company], machines=machines[company], clients=clients[company], range=range)

@app.route('/jobs')
def list_jobs():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    company = users[username]['company']
    return render_template('jobs.html', jobs=jobs[company])

@app.route('/delete_job/<int:job_index>', methods=['POST'])
def delete_job(job_index):
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    company = users[username]['company']

    if 0 <= job_index < len(jobs[company]):
        del jobs[company][job_index]
    return redirect(url_for('list_jobs'))

@app.route('/edit_job/<int:job_index>', methods=['GET', 'POST'])
def edit_job(job_index):
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    company = users[username]['company']

    if job_index < 0 or job_index >= len(jobs[company]):
        return redirect(url_for('list_jobs'))

    job = jobs[company][job_index]

    if request.method == 'POST':
        job['date'] = request.form.get('date')
        hour = request.form.get('hour')
        minute = request.form.get('minute')
        job['time'] = f"{job['date']} {hour}시 {minute}분"
        job['worker'] = request.form.get('worker_input') or request.form.get('worker_select')
        job['machine'] = request.form.get('machine_input') or request.form.get('machine_select')
        job['client'] = request.form.get('client_input') or request.form.get('client_select')
        job['location'] = request.form.get('location')
        job['note'] = request.form.get('note')

        if job['client'] and job['client'] not in clients[company]:
            clients[company].append(job['client'])

        return redirect(url_for('list_jobs'))

    return render_template('edit_job.html', job=job, job_index=job_index,
                           workers=workers[company], machines=machines[company], clients=clients[company], range=range)

@app.route('/add_worker', methods=['GET', 'POST'])
def add_worker():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    company = users[username]['company']

    if request.method == 'POST':
        name = request.form.get('name')
        if name and name not in workers[company]:
            workers[company].append(name)
            return redirect(url_for('add_worker'))

    return render_template('add_worker.html', workers=workers[company])

@app.route('/add_machine', methods=['GET', 'POST'])
def add_machine():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    company = users[username]['company']

    if request.method == 'POST':
        machine = request.form.get('machine')
        if machine and machine not in machines[company]:
            machines[company].append(machine)
            return redirect(url_for('add_machine'))

    return render_template('add_machine.html', machines=machines[company])

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None

    if request.method == 'POST':
        company = request.form.get('company')
        username = request.form.get('username')
        password = request.form.get('password')

        if username in users:
            error = '이미 존재하는 아이디입니다.'
        else:
            users[username] = {
                'password': password,
                'role': 'boss',
                'company': company
            }

            if company not in jobs:
                jobs[company] = []
                workers[company] = []
                machines[company] = []
                clients[company] = []

            return redirect(url_for('login'))

    return render_template('register.html', error=error)

if __name__ == '__main__':
    app.run(debug=True)
