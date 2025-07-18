from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.permanent_session_lifetime = timedelta(days=7)

users = {
    "boss": {"password": "1234", "role": "boss", "company": "default"},
    "crane1": {"password": "1111", "role": "worker", "company": "default"},
    "crane2": {"password": "2222", "role": "worker", "company": "default"},
    "leesj2809": {"password": "비밀번호", "role": "boss", "company": "홍예"}
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

@app.route('/register/role', methods=['GET', 'POST'])
def choose_role():
    return render_template('choose_role.html')

@app.route('/register/boss', methods=['GET', 'POST'])
def register_boss():
    import datetime
    now = datetime.datetime.now()
    with open("register_log.txt", "a", encoding="utf-8") as f:
        f.write(f"[{now}] 📩 register_boss 함수 진입\n")

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        company = request.form['company']

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

        with open("register_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{now}] ✅ 가입됨 → {username}, 회사={company}\n")

        session['username'] = username
        return redirect(url_for('dashboard'))

    return render_template('register_boss.html')

if __name__ == '__main__':
    print(app.url_map)
    app.run(debug=True)
