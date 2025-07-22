from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta
import json
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.permanent_session_lifetime = timedelta(days=7)

# 파일 저장 가이드
DATA_DIR = 'data'

def load_json(filename, default):
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default

def save_json(filename, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 기존 데이터는 하나만 로드 (edit/delete에서 다시 로드할 것이긴 해도, 사용 안해도 되는 방식)
users = load_json('users.json', {})
workers = load_json('workers.json', {})
machines = load_json('machines.json', {})
clients = load_json('clients.json', {})

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
    username = session.get('username')
    user_info = users.get(username)

    if not username or not user_info:
        return redirect(url_for('login'))

    role = user_info['role']
    return render_template('dashboard.html', username=username, role=role)

@app.route('/register/role', methods=['GET', 'POST'])
def choose_role():
    return render_template('choose_role.html')

@app.route('/register/boss', methods=['GET', 'POST'])
def register_boss():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        company = request.form['company']

        users[username] = {
            'password': password,
            'role': 'boss',
            'company': company
        }

        # 착용 가능한 공간 추가
        save_json('users.json', users)
        save_json('workers.json', {**load_json('workers.json', {}), company: []})
        save_json('machines.json', {**load_json('machines.json', {}), company: []})
        save_json('clients.json', {**load_json('clients.json', {}), company: []})
        save_json('jobs.json', {**load_json('jobs.json', {}), company: []})

        session['username'] = username
        return redirect(url_for('dashboard'))

    return render_template('register_boss.html')

@app.route('/register/worker', methods=['GET', 'POST'])
def register_worker():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        company = request.form['company']

        # users 딕셔너리 업데이트
        users[username] = {
            'password': password,
            'role': 'worker',
            'company': company
        }
        save_json('users.json', users)

        session['username'] = username
        return redirect(url_for('dashboard'))

    # 회사 목록 불러오기 (users 중 boss role 회사만)
    boss_companies = set(u['company'] for u in users.values() if u['role'] == 'boss')
    companies = sorted(boss_companies)

    return render_template('register_worker.html', companies=companies)

@app.route('/add_worker', methods=['GET', 'POST'])
def add_worker():
    username = session.get('username')
    if not username or username not in users:
        return redirect(url_for('login'))

    company = users[username]['company']
    if request.method == 'POST':
        name = request.form.get('name')
        if name:
            data = load_json('workers.json', {})
            data.setdefault(company, []).append({'name': name})
            save_json('workers.json', data)

    workers_data = load_json('workers.json', {})
    return render_template('add_worker.html', workers=[w['name'] for w in workers_data.get(company, [])])

@app.route('/add_machine', methods=['GET', 'POST'])
def add_machine():
    username = session.get('username')
    if not username or username not in users:
        return redirect(url_for('login'))

    company = users[username]['company']
    if request.method == 'POST':
        machine_type = request.form.get('machine_type')
        model = request.form.get('model')
        if machine_type and model:
            data = load_json('machines.json', {})
            data.setdefault(company, []).append({'type': machine_type, 'model': model})
            save_json('machines.json', data)

    machines_data = load_json('machines.json', {})
    return render_template('add_machine.html', machines=machines_data.get(company, []))

@app.route('/add_job', methods=['GET', 'POST'])
def add_job():
    if 'username' not in session:
        return redirect('/login')

    company = users[session['username']]['company']

    if request.method == 'POST':
        new_job = {
            "date": request.form['date'],
            "time": request.form['time'],
            "worker": request.form['worker'],
            "machine": request.form['machine'],
            "client": request.form['client'],
            "location": request.form['location'],
            "note": request.form['note']
        }

        jobs_db = load_json('jobs.json', {})
        jobs_db.setdefault(company, []).append(new_job)
        save_json('jobs.json', jobs_db)

        # 거래처/위치 자동 저장
        for field, filename in [('client', 'clients.json'), ('location', 'locations.json')]:
            data = load_json(filename, {})
            data.setdefault(company, [])
            if new_job[field] not in data[company]:
                data[company].append(new_job[field])
                save_json(filename, data)

        return redirect('/jobs')

    # GET 요청 시 데이터 준비
    workers = load_json('workers.json', {}).get(company, [])
    machines = load_json('machines.json', {}).get(company, [])
    clients = load_json('clients.json', {}).get(company, [])
    locations = load_json('locations.json', {}).get(company, [])

    return render_template(
        'add_job.html',
        workers=workers,
        machines=machines,
        clients=clients,
        locations=locations
    )

@app.route('/toggle_complete/<int:job_index>')
def toggle_complete(job_index):
    if 'username' not in session:
        return redirect('/login')
    username = session['username']
    company = users[username]['company']
    role = users[username]['role']

    jobs_db = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])

    if job_index >= len(job_list):
        return "작업을 찾을 수 없습니다.", 404

    job = job_list[job_index]

    # 권한 검사: 사장 또는 해당 작업 기사만 토글 가능
    if role != 'boss' and job.get('worker') != username:
        return "권한이 없습니다.", 403

    # 상태 토글
    job['status'] = '완료' if job.get('status') != '완료' else '진행중'

    # 저장
    save_json('jobs.json', jobs_db)

    # 리다이렉트 (필터 유지)
    return redirect(url_for('jobs', **request.args))


@app.route('/jobs')
def jobs():
    if 'username' not in session:
        return redirect('/login')

    username = session['username']
    role = users[username]['role']
    company = users[username]['company']

    # ✅ 항상 최신 데이터 불러오기
    jobs_db = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])

    # 🔍 검색 조건 받기
    q_worker = request.args.get('worker', '').strip()
    q_machine = request.args.get('machine', '').strip()
    q_client = request.args.get('client', '').strip()
    q_date = request.args.get('date', '').strip()

    # 🔍 필터링
    filtered_jobs = []
    for job in job_list:
        if q_worker and q_worker not in job.get('worker', ''):
            continue
        if q_machine and q_machine not in job.get('machine', ''):
            continue
        if q_client and q_client not in job.get('client', ''):
            continue
        if q_date and q_date != job.get('date', ''):
            continue
        filtered_jobs.append(job)

    # 🔎 디버깅 출력
    print("=== [jobs 라우트 디버깅] ===")
    print(f"검색 조건: worker={q_worker}, machine={q_machine}, client={q_client}, date={q_date}")
    print(f"검색 결과 {len(filtered_jobs)}건")
    print("===========================")

    return render_template(
        'view_jobs.html',
        jobs=filtered_jobs,
        username=username,
        role=role,
        request=request  # 템플릿에서 request.args 사용 위해 필요
    )

@app.route('/edit_job/<int:job_index>', methods=['GET', 'POST'])
def edit_job(job_index):
    if 'username' not in session:
        return redirect('/login')

    username = session['username']
    company = users[username]['company']

    # ✅ jobs.json 파일 로드
    jobs_db = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])

    if job_index >= len(job_list):
        return "작업을 찾을 수 없습니다.", 404

    job = job_list[job_index]

    if request.method == 'POST':
        job['date'] = request.form['date']
        job['time'] = request.form['time']
        job['worker'] = request.form['worker']
        job['machine'] = request.form['machine']
        job['client'] = request.form['client']
        job['location'] = request.form['location']
        job['note'] = request.form['note']

        # ✅ 수정 후 저장
        save_json('jobs.json', jobs_db)

        # ✅ 검색 조건 유지
        query_args = {
            k.replace('filter_', ''): v
            for k, v in request.form.items()
            if k.startswith('filter_') and v
        }

        return redirect(url_for('jobs', **query_args))

    # ✅ 드롭다운 데이터
    workers = load_json('workers.json', {}).get(company, [])
    machines = load_json('machines.json', {}).get(company, [])
    clients = load_json('clients.json', {}).get(company, [])
    locations = load_json('locations.json', {}).get(company, [])

    return render_template(
        'edit_job.html',
        job=job,
        job_index=job_index,
        workers=workers,
        machines=machines,
        clients=clients,
        locations=locations,
        request=request  # 필터 유지용
    )

@app.route('/delete_job/<int:job_index>')
def delete_job(job_index):
    if 'username' not in session:
        return redirect('/login')

    username = session['username']
    company = users[username]['company']

    jobs_db = load_json('jobs.json', {})  # ← 여기가 빠져있음
    job_list = jobs_db.get(company, [])

    if job_index >= len(job_list):
        return "작업을 찾을 수 없습니다.", 404

    del job_list[job_index]
    save_json('jobs.json', jobs_db)

    return redirect(url_for('jobs', **request.args))

if __name__ == '__main__':
    app.run(debug=True)
