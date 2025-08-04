from flask import Flask, render_template, request, redirect, url_for, session
from datetime import timedelta
import json
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.permanent_session_lifetime = timedelta(days=7)

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
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"!!! save_json error: {e}")

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    if request.method == 'POST':
        phone = request.form.get('phone')
        password = request.form.get('password')

        users_db = load_json('users.json', {})

        user = None
        username = None
        for u_name, u_data in users_db.items():
            if u_data.get('phone') == phone:
                user = u_data
                username = u_name
                break

        if user and user.get('password') == password:
            if user.get('role') == 'worker' and user.get('status', 'active') == 'pending':
                error = '승인 대기중입니다. 사장님의 승인을 기다려주세요.'
                return render_template('login.html', error=error)

            session.permanent = True
            session['username'] = username
            session['role'] = user.get('role')
            session['company'] = user.get('company', '')

            if user['role'] == 'boss':
                return redirect(url_for('dashboard'))
            else:
                return redirect(url_for('dashboard_worker'))
        else:
            error = '휴대폰번호 또는 비밀번호가 올바르지 않습니다.'

    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    username = session.get('username')
    role = session.get('role')
    if not username or role != 'boss':
        return redirect(url_for('login'))

    users_db = load_json('users.json', {})
    user_info = users_db.get(username, {})
    company = user_info.get('company', '')

    return render_template(
        'dashboard.html',
        company=company,
        role=role
    )

@app.route('/batch_action_jobs', methods=['POST'])
def batch_action_jobs():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    users_db = load_json('users.json', {})
    company = users_db.get(username, {}).get('company')

    jobs_db = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])

    selected_indices = request.form.getlist('selected_jobs')  # checkbox name이 selected_jobs여야 함

    action = request.form.get('action')  # 예: 'delete' 또는 'complete'

    if action == 'delete':
        # 인덱스 역순으로 삭제 (인덱스 밀림 방지)
        for index_str in sorted(selected_indices, reverse=True):
            index = int(index_str)
            if 0 <= index < len(job_list):
                del job_list[index]
    elif action == 'complete':
        for index_str in selected_indices:
            index = int(index_str)
            if 0 <= index < len(job_list):
                job_list[index]['status'] = '완료'

    save_json('jobs.json', jobs_db)
    return redirect(url_for('jobs'))

@app.route('/dashboard_worker')
def dashboard_worker():
    username = session.get('username')
    if not username:
        return redirect(url_for('login'))

    users_db = load_json('users.json', {})
    user_info = users_db.get(username)

    if not user_info or user_info.get('role') != 'worker':
        return "권한이 없습니다.", 403

    company = user_info['company']
    worker_name = user_info['name']  # 로그인한 기사의 이름 (ex: "이윤재")

    jobs_db = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])

    # 작업 worker 필드가 로그인한 기사의 이름과 같은지 필터링
    my_jobs = [job for job in job_list if job.get('worker') == worker_name]

    for job in my_jobs:
        if 'status' not in job:
            job['status'] = '진행중'

    return render_template('dashboard_worker.html', username=username, jobs=my_jobs)

@app.route('/register/boss', methods=['GET', 'POST'])
def register_boss():
    companies = load_json('companies.json', {})

    if request.method == 'POST':
        password = request.form['password']
        company = request.form['company'].strip()
        phone = request.form['phone'].strip()
        input_code = request.form['company_code'].strip()

        if company in companies:
            error = '이미 등록된 회사명입니다.'
            return render_template('register_boss.html', error=error)

        if len(input_code) != 6:
            error = '회사 코드는 6자리여야 합니다.'
            return render_template('register_boss.html', error=error)

        users_db = load_json('users.json', {})
        for user in users_db.values():
            if user.get('phone') == phone:
                error = '해당 전화번호로 이미 가입된 계정이 있습니다.'
                return render_template('register_boss.html', error=error)

        base_username = f"{company}boss"
        username = base_username
        suffix = 1
        while username in users_db:
            username = f"{base_username}{suffix}"
            suffix += 1

        users_db[username] = {
            'password': password,
            'role': 'boss',
            'company': company,
            'phone': phone,
            'company_code': input_code
        }
        save_json('users.json', users_db)

        companies[company] = {
            'code': input_code,
            'phone': phone
        }
        save_json('companies.json', companies)

        save_json('workers.json', {**load_json('workers.json', {}), company: []})
        save_json('machines.json', {**load_json('machines.json', {}), company: []})
        save_json('clients.json', {**load_json('clients.json', {}), company: []})
        save_json('jobs.json', {**load_json('jobs.json', {}), company: []})

        session['username'] = username

        return redirect(url_for('dashboard'))

    return render_template('register_boss.html')

@app.route('/register/worker', methods=['GET', 'POST'])
def register_worker():
    try:
        companies = load_json('companies.json', {})

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            phone = request.form.get('phone', '').strip()
            company = request.form.get('company', '').strip()
            input_code = request.form.get('company_code', '').strip()
            password = request.form.get('password', '').strip()

            if company not in companies:
                error = '존재하지 않는 회사명입니다.'
                return render_template('register_worker.html', companies=sorted(companies.keys()), error=error)

            if companies[company]['code'] != input_code:
                error = '회사 코드가 올바르지 않습니다.'
                return render_template('register_worker.html', companies=sorted(companies.keys()), error=error)

            users_db = load_json('users.json', {})
            for user in users_db.values():
                if user.get('company') == company and user.get('phone') == phone:
                    error = '해당 전화번호로 이미 가입된 계정이 있습니다.'
                    return render_template('register_worker.html', companies=sorted(companies.keys()), error=error)

            base_username = f"{company}{name}"
            username = base_username
            suffix = 1
            while username in users_db:
                username = f"{base_username}{suffix}"
                suffix += 1

            users_db[username] = {
                'password': password,
                'role': 'worker',
                'company': company,
                'name': name,
                'phone': phone,
                'status': 'pending'
            }
            save_json('users.json', users_db)

            workers_db = load_json('workers.json', {})
            workers_db.setdefault(company, [])
            workers_db[company] = [
                w for w in workers_db[company] if w.get('phone') != phone
            ]
            workers_db[company].append({
                'username': username,
                'name': name,
                'phone': phone,
                'role': 'worker',
                'status': 'pending'
            })
            save_json('workers.json', workers_db)

            return render_template(
                'register_worker_pending.html',
                name=name,
                company=company
            )

        return render_template('register_worker.html', companies=sorted(companies.keys()))
    
    except Exception as e:
        import traceback
        return f"<h2>서버 오류 발생:<br>{e}</h2><pre>{traceback.format_exc()}</pre>"

@app.route('/add_worker', methods=['GET', 'POST'])
def add_worker():
    if 'username' not in session:
        return redirect('/login')

    users_db = load_json('users.json', {})
    company = users_db[session['username']]['company']

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()

        if not name or not phone:
            workers_db = load_json('workers.json', {})
            workers = workers_db.get(company, [])
            error = "기사 이름과 전화번호를 모두 입력해 주세요."
            return render_template('add_worker.html', workers=workers, error=error)

        # 중복 검사 (이름 또는 전화번호가 동일한 기사 존재 시)
        workers_db = load_json('workers.json', {})
        workers = workers_db.get(company, [])
        for w in workers:
            if w.get('name') == name or w.get('phone') == phone:
                error = "이미 등록된 기사명 또는 전화번호입니다."
                return render_template('add_worker.html', workers=workers, error=error)

        # username 생성 (회사명 + 이름)
        username = f"{company}{name}"

        # workers.json에 저장
        new_worker = {
            "username": username,
            "name": name,
            "phone": phone,
            "role": "worker",
            "status": "active"
        }

        workers.append(new_worker)
        workers_db[company] = workers
        save_json('workers.json', workers_db)

        return redirect('/add_worker')

    # GET 요청 시
    workers_db = load_json('workers.json', {})
    workers = workers_db.get(company, [])
    return render_template('add_worker.html', workers=workers)

@app.route('/add_machine', methods=['GET', 'POST'])
def add_machine():
    if 'username' not in session:
        return redirect('/login')

    users_db = load_json('users.json', {})
    company = users_db[session['username']]['company']

    if request.method == 'POST':
        name = request.form.get('machine_name', '').strip()
        number = request.form.get('machine_number', '').strip()
        alias = request.form.get('machine_alias', '').strip()

        if not name or not number:
            machines_db = load_json('machines.json', {})
            machines = machines_db.get(company, [])
            error = "장비명과 차량번호는 필수 입력입니다."
            return render_template('add_machine.html', machines=machines, error=error)

        new_machine = {
            'name': name,
            'number': number,
            'alias': alias
        }

        machines_db = load_json('machines.json', {})
        machines_db.setdefault(company, []).append(new_machine)
        save_json('machines.json', machines_db)

        return redirect('/add_machine')

    machines_db = load_json('machines.json', {})
    machines = machines_db.get(company, [])
    return render_template('add_machine.html', machines=machines)

@app.route('/delete_machine', methods=['POST'])
def delete_machine():
    if 'username' not in session:
        return redirect('/login')

    users_db = load_json('users.json', {})
    company = users_db[session['username']]['company']
    number = request.form.get('machine_number', '').strip()

    machines_db = load_json('machines.json', {})
    machines = machines_db.get(company, [])
    machines = [m for m in machines if m.get('number') != number]
    machines_db[company] = machines
    save_json('machines.json', machines_db)

    return redirect('/add_machine')

@app.route('/add_job', methods=['GET', 'POST'])
def add_job():
    if 'username' not in session:
        return redirect('/login')

    users_db = load_json('users.json', {})
    company = users_db.get(session['username'], {}).get('company', '')

    # GET: 드롭다운 데이터 준비
    workers = load_json('workers.json', {}).get(company, [])
    machines = load_json('machines.json', {}).get(company, [])
    clients = load_json('clients.json', {}).get(company, [])
    locations = load_json('locations.json', {}).get(company, [])

    if request.method == 'POST':
        # 폼 데이터 변수로 추출
        date = request.form.get('date', '').strip()
        hour = request.form.get('hour', '').strip()
        minute = request.form.get('minute', '').strip()
        time = f"{hour}:{minute}" if hour and minute else ''

        worker = request.form.get('worker', '').strip()
        machine_name = request.form.get('machine_name_input', '').strip()
        machine_number = request.form.get('machine_number_input', '').strip()
        machine_alias = request.form.get('machine_alias_input', '').strip()
        client = request.form.get('client_input', '').strip()
        location = request.form.get('location', '').strip()
        note = request.form.get('note', '').strip()

        # 필수 입력 체크
        if not (worker and machine_name and machine_number and client and location and date and time):
            error = "기사, 장비명, 차량번호, 거래처, 위치, 날짜, 시간은 반드시 입력(혹은 선택)해야 합니다."
            return render_template(
                'add_job.html',
                workers=workers,
                machines=machines,
                clients=clients,
                locations=locations,
                error=error,
                prev=request.form,
                job_registered=False
            )

        new_job = {
            "date": date,
            "time": time,
            "worker": worker,
            "machine_name": machine_name,
            "machine_number": machine_number,
            "machine_alias": machine_alias,
            "client": client,
            "location": location,
            "note": note
        }

        jobs_db = load_json('jobs.json', {})
        jobs_db.setdefault(company, []).append(new_job)
        save_json('jobs.json', jobs_db)

        return render_template(
            'add_job.html',
            workers=workers,
            machines=machines,
            clients=clients,
            locations=locations,
            job_registered=True
        )

    return render_template(
        'add_job.html',
        workers=workers,
        machines=machines,
        clients=clients,
        locations=locations,
        job_registered=False
    )

@app.route('/toggle_complete/<int:job_index>')
def toggle_complete(job_index):
    username = session.get('username')
    if not username:
        return redirect(url_for('login'))

    users_db = load_json('users.json', {})
    user_info = users_db.get(username)
    if not user_info:
        return redirect(url_for('login'))

    company = user_info['company']
    jobs_db = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])

    if job_index >= len(job_list):
        return "작업을 찾을 수 없습니다.", 404

    job = job_list[job_index]

    is_worker = user_info['role'] == 'worker'
    is_boss = user_info['role'] == 'boss'

    if is_worker and job.get('worker') != username:
        return "권한이 없습니다.", 403

    job['status'] = '완료' if job.get('status') != '완료' else '진행중'
    save_json('jobs.json', jobs_db)

    if is_boss:
        return redirect(url_for('jobs'))
    else:
        return redirect(url_for('dashboard_worker'))

@app.route('/manage_workers')
def manage_workers():
    if 'username' not in session or session.get('role') != 'boss':
        return redirect('/login')

    company = session['company']
    workers_db = load_json('workers.json', {})
    users_db = load_json('users.json', {})

    workers = workers_db.get(company, [])

    # workers 리스트에 users.json의 role 최신 정보 덮어쓰기
    for w in workers:
        user_info = users_db.get(w['username'])
        if user_info:
            w['role'] = user_info.get('role', 'worker')
        else:
            w['role'] = 'worker'  # 기본 권한

    return render_template('manage_workers.html', workers=workers)

@app.route('/approve_worker/<username>', methods=['POST'])
def approve_worker(username):
    if 'username' not in session or session.get('role') != 'boss':
        return redirect('/login')
    company = session['company']

    users_db = load_json('users.json', {})
    workers_db = load_json('workers.json', {})

    if username in users_db and users_db[username]['company'] == company:
        users_db[username]['status'] = 'active'
        save_json('users.json', users_db)

        for w in workers_db.get(company, []):
            if w['username'] == username:
                w['status'] = 'active'
                break
        save_json('workers.json', workers_db)
    return redirect('/manage_workers')

@app.route('/delete_worker/<username>', methods=['POST'])
def delete_worker(username):
    if 'username' not in session or session.get('role') != 'boss':
        return redirect('/login')
    company = session['company']
    users_db = load_json('users.json', {})
    workers_db = load_json('workers.json', {})

    if username in users_db and users_db[username]['company'] == company:
        del users_db[username]
        save_json('users.json', users_db)

    if company in workers_db:
        workers_db[company] = [w for w in workers_db[company] if w.get('username') != username]
        save_json('workers.json', workers_db)
    else:
        workers_db[company] = []
        save_json('workers.json', workers_db)

    return redirect('/manage_workers')

@app.route('/grant_manager/<username>', methods=['POST'])
def grant_manager(username):
    if 'username' not in session or session.get('role') != 'boss':
        return redirect('/login')
    company = session['company']
    users_db = load_json('users.json', {})

    if username in users_db and users_db[username]['company'] == company:
        users_db[username]['role'] = 'boss'
        save_json('users.json', users_db)

    return redirect('/manage_workers')

@app.route('/revoke_manager/<username>', methods=['POST'])
def revoke_manager(username):
    if 'username' not in session or session.get('role') != 'boss':
        return redirect('/login')
    company = session['company']
    users_db = load_json('users.json', {})

    if username in users_db and users_db[username]['company'] == company:
        users_db[username]['role'] = 'worker'
        save_json('users.json', users_db)

    return redirect('/manage_workers')

@app.route('/update_worker/<username>', methods=['GET', 'POST'])
def update_worker(username):
    if 'username' not in session or session.get('role') != 'boss':
        return redirect('/login')
    company = session['company']
    users_db = load_json('users.json', {})
    workers_db = load_json('workers.json', {})

    user = users_db.get(username)
    if not user or user['company'] != company:
        return redirect('/manage_workers')

    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        user['name'] = name
        user['phone'] = phone
        save_json('users.json', users_db)

        for w in workers_db.get(company, []):
            if w['username'] == username:
                w['name'] = name
                w['phone'] = phone
                break
        save_json('workers.json', workers_db)

        return redirect('/manage_workers')

    return render_template('update_worker.html', user=user)

@app.route('/jobs')
def jobs():
    if 'username' not in session:
        return redirect('/login')

    username = session['username']
    users_db = load_json('users.json', {})
    role = users_db.get(username, {}).get('role')
    company = users_db.get(username, {}).get('company')

    jobs_db = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])
    print("=== 작업 목록 ===")
    for job in job_list:
        print(f"날짜: {job.get('date')}, 요청사항 길이: {len(job.get('note', ''))}")

    q_worker = request.args.get('worker', '').strip()
    q_machine = request.args.get('machine', '').strip()
    q_client = request.args.get('client', '').strip()
    q_date = request.args.get('date', '').strip()

    filtered_jobs = []
    for job in job_list:
        if q_worker and q_worker not in job.get('worker', ''):
            continue
        if q_machine and q_machine not in job.get('machine_name', ''):
            continue
        if q_client and q_client not in job.get('client', ''):
            continue
        if q_date and q_date != job.get('date', ''):
            continue
        filtered_jobs.append(job)

    return render_template(
        'view_job.html',
        jobs=filtered_jobs,
        username=username,
        role=role,
        request=request
    )

@app.route('/edit_job/<int:job_index>', methods=['GET', 'POST'])
def edit_job(job_index):
    if 'username' not in session:
        return redirect('/login')
    username = session['username']
    users_db = load_json('users.json', {})
    company = users_db.get(username, {}).get('company')

    jobs_db = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])

    if job_index >= len(job_list):
        return "작업을 찾을 수 없습니다.", 404

    job = job_list[job_index]

    if request.method == 'POST':
        job['date'] = request.form.get('date', '')
        job['time'] = request.form.get('time', '')
        job['worker'] = request.form.get('worker', '')
        job['machine_name'] = request.form.get('machine_name', '')
        job['machine_number'] = request.form.get('machine_number', '')
        job['machine_alias'] = request.form.get('machine_alias', '')
        job['client'] = request.form.get('client', '')
        job['location'] = request.form.get('location', '')
        job['note'] = request.form.get('note', '')
        save_json('jobs.json', jobs_db)
        return redirect(url_for('jobs'))

    machines = load_json('machines.json', {}).get(company, [])
    workers = load_json('workers.json', {}).get(company, [])
    clients = load_json('clients.json', {}).get(company, [])
    locations = load_json('locations.json', {}).get(company, [])

    return render_template(
        'edit_job.html',
        job=job,
        job_index=job_index,
        machines=machines,
        workers=workers,
        clients=clients,
        locations=locations
    )

@app.route('/delete_job/<int:job_index>')
def delete_job(job_index):
    if 'username' not in session:
        return redirect('/login')

    username = session['username']
    users_db = load_json('users.json', {})
    company = users_db.get(username, {}).get('company')

    jobs_db = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])

    if job_index >= len(job_list):
        return "작업을 찾을 수 없습니다.", 404

    del job_list[job_index]
    save_json('jobs.json', jobs_db)

    return redirect(url_for('jobs', **request.args))

@app.route('/profile')
def profile():
    return "내 정보 조회 및 수정 페이지 (추후 구현 예정)"

@app.route('/calendar_view')
def calendar_view():
    return "작업 상세 보기 및 수정(캘린더) 페이지 (추후 구현 예정)"

@app.route('/company_info', methods=['GET', 'POST'])
def company_info():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    users_db = load_json('users.json', {})
    user = users_db.get(username, {})

    if not user or user.get('role') != 'boss':
        return "권한이 없습니다.", 403

    company = user.get('company')
    companies = load_json('companies.json', {})
    company_info = companies.get(company, {})

    error = None
    success = None

    if request.method == 'POST':
        new_company_name = request.form['company']
        new_phone = request.form['phone']
        new_password = request.form['password']
        new_company_code = request.form['company_code']

        if len(new_company_code) != 6:
            error = '회사 코드는 6자리여야 합니다.'
        elif new_company_name != company and new_company_name in companies:
            error = '이미 존재하는 회사명입니다.'
        else:
            if new_company_name != company:
                users_db[username]['company'] = new_company_name
                companies[new_company_name] = companies.pop(company)
                company = new_company_name

            users_db[username]['phone'] = new_phone
            if new_password.strip():
                users_db[username]['password'] = new_password

            save_json('users.json', users_db)

            companies[company]['phone'] = new_phone
            companies[company]['code'] = new_company_code
            save_json('companies.json', companies)

            success = '회사 정보가 성공적으로 수정되었습니다.'

    return render_template(
        'company_info.html',
        username=username,
        user=user,
        company=company,
        company_info=company_info,
        error=error,
        success=success
    )

if __name__ == '__main__':
    app.run(debug=True)
