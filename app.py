from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import timedelta
import json
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.permanent_session_lifetime = timedelta(days=7)
DATA_DIR = 'data'


# ---------------------------
# 유틸
# ---------------------------
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


def _get_current_user():
    if 'username' not in session:
        return None, None, None
    users_db = load_json('users.json', {})
    user = users_db.get(session['username'])
    if not user:
        return None, None, None
    return session['username'], user.get('company', ''), (user.get('role') or '').strip()


def _attach_indices(jobs):
    # 각 작업에 _idx를 부여 (리스트 index 기준)
    for i, j in enumerate(jobs):
        j['_idx'] = i
    return jobs


def _filter_jobs(jobs, worker=None, client=None, date=None):
    def match(val, q):
        return (q is None or q == '' or (val or '').strip().find(q.strip()) != -1)
    out = []
    for j in jobs:
        if worker is not None and worker != '':
            if (j.get('worker') or '').strip() != worker.strip():
                continue
        if not match(j.get('client'), client):
            continue
        if date and (j.get('date') or '') != date:
            continue
        out.append(j)
    return out


# ---------------------------
# 홈/인증
# ---------------------------
@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    else:
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


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------------------
# 대시보드
# ---------------------------
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


@app.route('/dashboard_worker')
def dashboard_worker():
    username, company, role = _get_current_user()
    if not username:
        return redirect(url_for('login'))

    db = load_json('jobs.json', {})
    jobs = db.get(company, [])

    # 기사면 내 작업만, 사장이면 모든 작업(혹시 사장이 들어오더라도 사용 가능)
    if role == 'worker':
        jobs = [j for j in jobs if (j.get('worker') or '') == username]

    # 필터: 거래처/날짜
    q_client = request.args.get('client', '').strip()
    q_date = request.args.get('date', '').strip()
    if q_client or q_date:
        jobs = _filter_jobs(_attach_indices(jobs), worker=None, client=q_client, date=q_date)
    else:
        jobs = _attach_indices(jobs)

    return render_template('dashboard_worker.html', jobs=jobs)


# ---------------------------
# 작업 목록(사장용)
# ---------------------------
@app.route('/jobs', endpoint='view_jobs')              # 정식 경로
@app.route('/view_jobs', endpoint='view_jobs_legacy')  # 레거시 경로(옵션)
def view_jobs():
    # 로그인/권한
    if 'username' not in session:
        return redirect(url_for('login'))

    users_db = load_json('users.json', {})
    user = users_db.get(session['username'], {}) or {}
    role = (user.get('role') or '').strip()
    if role != 'boss':
        return redirect(url_for('dashboard_worker'))

    company = user.get('company', '')

    # 작업 로드
    jobs_all = load_json('jobs.json', {}).get(company, [])

    # _idx 부여(원본 인덱스 유지)
    for i, j in enumerate(jobs_all):
        j['_idx'] = i

    # 검색/필터 파라미터
    q_worker = (request.args.get('worker') or '').strip()
    q_client = (request.args.get('client') or '').strip()
    q_date = (request.args.get('date') or '').strip()
    overdue = (request.args.get('overdue') or '').strip()  # '1'이면 완료 아님만

    # 필터 적용
    jobs = jobs_all
    if q_worker:
        jobs = [j for j in jobs if q_worker in (j.get('worker') or '')]
    if q_client:
        jobs = [j for j in jobs if q_client in (j.get('client') or '')]
    if q_date:
        jobs = [j for j in jobs if q_date == (j.get('date') or '')]
    if overdue == '1':
        jobs = [j for j in jobs if (j.get('status') or '진행중').strip() != '완료']

    # '미수작업만/전체보기' 토글 URL
    args_dict = request.args.to_dict(flat=True)
    overdue_on = args_dict.copy(); overdue_on['overdue'] = '1'
    overdue_off = args_dict.copy(); overdue_off['overdue'] = '0'
    overdue_on_url = url_for('view_jobs', **overdue_on)
    overdue_off_url = url_for('view_jobs', **overdue_off)

    return render_template(
        'view_job.html',
        jobs=jobs,
        overdue=overdue,
        overdue_on_url=overdue_on_url,
        overdue_off_url=overdue_off_url
    )


# ---------------------------
# 작업 등록/수정/삭제
# ---------------------------
@app.route('/add_job', methods=['GET', 'POST'])
def add_job():
    if 'username' not in session:
        return redirect('/login')

    users_db = load_json('users.json', {})
    company = users_db.get(session['username'], {}).get('company', '')

    workers = load_json('workers.json', {}).get(company, [])
    machines = load_json('machines.json', {}).get(company, [])
    clients = load_json('clients.json', {}).get(company, [])
    locations = load_json('locations.json', {}).get(company, [])

    if request.method == 'POST':
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

        # 신규: 금액(만원) & 기사공유 여부
        amount_man_raw = (request.form.get('amount_man') or '').strip()
        try:
            amount_man = int(amount_man_raw) if amount_man_raw != '' else 0
        except ValueError:
            amount_man = 0
        share_amount = bool(request.form.get('share_amount'))

        duration_type = request.form.get('duration_type', '하루')
        duration_hours = request.form.get('duration_hours', '').strip()

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
            "note": note,
            "status": "진행중",  # 기본 상태
            "duration_type": duration_type,
            "duration_hours": duration_hours,
            # 신규 필드
            "amount_man": amount_man,          # 만원 단위 정수
            "share_amount": share_amount       # True/False
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

        # 신규: 금액/공유 업데이트
        amount_man_raw = (request.form.get('amount_man') or '').strip()
        try:
            job['amount_man'] = int(amount_man_raw) if amount_man_raw != '' else 0
        except ValueError:
            job['amount_man'] = 0
        job['share_amount'] = bool(request.form.get('share_amount'))

        save_json('jobs.json', jobs_db)
        return redirect(url_for('view_jobs'))

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

    return redirect(url_for('view_jobs', **request.args))


# ---------------------------
# 일괄 처리(사장용)
# ---------------------------
@app.route('/bulk_action', methods=['POST'])
def bulk_action():
    if 'username' not in session:
        return redirect(url_for('login'))

    action = request.form.get('action', '').strip()
    # 체크박스 value는 원본 인덱스(_idx)여야 합니다.
    try:
        selected = [int(x) for x in request.form.getlist('selected_jobs')]
    except ValueError:
        selected = []

    users_db = load_json('users.json', {})
    user = users_db.get(session['username'], {})
    company = user.get('company', '')

    db = load_json('jobs.json', {})
    jobs = db.get(company, [])

    if action == 'complete':
        for idx in selected:
            if 0 <= idx < len(jobs):
                jobs[idx]['status'] = '완료'
    elif action == 'delete':
        # 인덱스 꼬임 방지: 큰 인덱스부터 삭제
        for idx in sorted(set(selected), reverse=True):
            if 0 <= idx < len(jobs):
                jobs.pop(idx)

    db[company] = jobs
    save_json('jobs.json', db)
    return redirect(url_for('view_jobs'))


# ---------------------------
# 상태 토글 API (공통)
# ---------------------------
@app.route('/api/toggle_complete/<int:job_index>', methods=['POST'])
def toggle_complete_api(job_index):
    if 'username' not in session:
        return jsonify(success=False, error='unauthorized'), 401

    users_db = load_json('users.json', {})
    user = users_db.get(session['username'], {})
    company = user.get('company', '')
    role = (user.get('role') or '').strip()
    username = session['username']

    db = load_json('jobs.json', {})
    jobs = db.get(company, [])

    if not (0 <= job_index < len(jobs)):
        return jsonify(success=False, error='index_out_of_range'), 400

    # worker는 자신의 작업만 토글 가능
    if role == 'worker' and (jobs[job_index].get('worker') or '') != username:
        return jsonify(success=False, error='forbidden'), 403

    cur = (jobs[job_index].get('status') or '진행중').strip()
    new_status = '완료' if cur != '완료' else '진행중'
    jobs[job_index]['status'] = new_status

    db[company] = jobs
    save_json('jobs.json', db)

    return jsonify(success=True, status=new_status)


# ---------------------------
# 캘린더(요약 + 클릭 이동은 템플릿에서 처리)
# ---------------------------
@app.route('/calendar')
def calendar_view():
    if 'username' not in session:
        return redirect(url_for('login'))

    users_db = load_json('users.json', {})
    user = users_db.get(session['username'], {})
    company = user.get('company', '')
    jobs = load_json('jobs.json', {}).get(company, [])

    total_count = len(jobs)
    complete_count = sum(1 for j in jobs if (j.get('status') or '').strip() == '완료')
    pending_count = total_count - complete_count

    # 풀캘린더용 event는 필요 시 템플릿에서 fetch로 대체; 여기서는 간단히 개수만
    events = []
    for j in jobs:
        d = (j.get('date') or '').strip()  # YYYY-MM-DD
        if not d:
            continue
        title_bits = [j.get('worker') or '', j.get('client') or '']
        title = " - ".join([x for x in title_bits if x]) or "작업"
        events.append({
            "title": title,
            "start": d,
            "extendedProps": {
                "status": j.get('status',''),
                "time": j.get('time',''),
                "duration_type": j.get('duration_type','하루'),
                "duration_hours": j.get('duration_hours','')
            }
        })

    return render_template(
        'calendar_jobs.html',
        total_count=total_count,
        complete_count=complete_count,
        pending_count=pending_count,
        events=json.dumps(events, ensure_ascii=False)
    )


@app.route('/api/calendar_stats', methods=['GET'], endpoint='calendar_stats')
def calendar_stats():
    if 'username' not in session:
        return jsonify(success=False, error='unauthorized'), 401

    users_db = load_json('users.json', {})
    user = users_db.get(session['username'], {})
    company = user.get('company', '')
    role = (user.get('role') or '').strip()
    username = session['username']

    db = load_json('jobs.json', {})
    jobs = db.get(company, [])

    counts = {}
    for job in jobs:
        date = (job.get('date') or '').strip()
        if not date:
            continue
        if role == 'worker' and (job.get('worker') or '') != username:
            continue
        c = counts.setdefault(date, {"total": 0, "done": 0, "todo": 0})
        c["total"] += 1
        if (job.get('status') or '진행중').strip() == '완료':
            c["done"] += 1
        else:
            c["todo"] += 1

    return jsonify(success=True, counts=counts)


# ---------------------------
# 기사/장비/회사 관리
# ---------------------------
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


# ---------------------------
# 회원가입 (사장/기사)
# ---------------------------
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


# ---------------------------
# 기타
# ---------------------------
@app.route('/edit_worker', methods=['GET', 'POST'])
def edit_worker():
    if 'username' not in session:
        return redirect('/login')

    worker_username = request.args.get('worker_username')
    # 사장인지 확인
    users_db = load_json('users.json', {})
    current_user = users_db.get(session['username'], {})
    is_boss = current_user.get('role') == 'boss'

    if worker_username and is_boss:
        # 사장이 다른 기사 편집
        username_to_edit = worker_username
        back_endpoint = 'manage_workers'
        back_label = '← 기사관리 메뉴로 돌아가기'
    else:
        # 기사가 자기 정보 편집
        username_to_edit = session['username']
        back_endpoint = 'dashboard_worker'
        back_label = '🏠 메인화면으로 돌아가기'

    user_info = users_db.get(username_to_edit)
    if not user_info:
        return "사용자 정보를 찾을 수 없습니다.", 404

    if request.method == 'POST':
        name = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip()
        password = request.form.get('password','').strip()
        if name:     user_info['name'] = name
        if phone:    user_info['phone'] = phone
        if password: user_info['password'] = password
        users_db[username_to_edit] = user_info
        save_json('users.json', users_db)
        return redirect(url_for(back_endpoint))

    # GET 시
    return render_template(
        'edit_worker.html',
        user=user_info,
        back_endpoint=back_endpoint,
        back_label=back_label
    )


# ---------------------------
# 앱 실행
# ---------------------------
if __name__ == '__main__':
    # debug=True에서 엔드포인트 중복이 있으면 즉시 AssertionError가 납니다.
    app.run(debug=True, host='0.0.0.0', port=5000)
