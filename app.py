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
    print(">>> / 라우트 진입")
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    print(">>> /login 라우트 진입, method =", request.method)
    error = None

    if request.method == 'POST':
        phone = request.form.get('phone')
        password = request.form.get('password')

        # users.json에서 모든 사용자 로드
        users_db = load_json('users.json', {})

        # 전화번호로 사용자 찾기
        user = None
        username = None
        for u_name, u_data in users_db.items():
            if u_data.get('phone') == phone:
                user = u_data
                username = u_name
                break

        # 인증 처리
        if user and user.get('password') == password:
            # 세션에 사용자 정보 저장
            session.permanent = True
            session['username'] = username
            session['role']     = user.get('role')       # 'boss' 또는 'worker'
            session['company']  = user.get('company', '') # 회사명

            # 역할별 대시보드로 분기
            if user['role'] == 'boss':
                return redirect(url_for('dashboard'))            # 사장 대시보드
            else:
                return redirect(url_for('dashboard_worker'))    # 기사 대시보드
        else:
            error = '휴대폰번호 또는 비밀번호가 올바르지 않습니다.'

    # GET 요청 또는 인증 실패 시
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

from flask import session, redirect, url_for, render_template

@app.route('/dashboard')
def dashboard():
    # 1) 세션에서 사용자·역할 정보 꺼내기
    username = session.get('username')
    role     = session.get('role')

    # 2) 로그인 여부 및 사장 여부 확인
    if not username or role != 'boss':
        return redirect(url_for('login'))

    # 3) users.json 에서 해당 사용자 정보 로드 (company 확인용)
    users_db  = load_json('users.json', {})
    user_info = users_db.get(username, {})
    company   = user_info.get('company', '')

    # 4) 템플릿에 company와 role 모두 전달
    return render_template(
        'dashboard.html',
        company=company,
        role=role
    )


    
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

    jobs_db = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])

    # 현재 로그인한 기사의 작업만 필터링
    my_jobs = [job for job in job_list if job.get('worker') == username]

    # 작업 상태가 없으면 기본값 '진행중' 설정
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

        # 회사명 중복 검사
        if company in companies:
            error = '이미 등록된 회사명입니다.'
            return render_template('register_boss.html', error=error)

        # 회사 코드 길이 체크
        if len(input_code) != 6:
            error = '회사 코드는 6자리여야 합니다.'
            return render_template('register_boss.html', error=error)

        # 전화번호 중복 검사 (같은 회사명은 없으니 전화번호만 중복 체크)
        users_db = load_json('users.json', {})
        for user in users_db.values():
            if user.get('phone') == phone:
                error = '해당 전화번호로 이미 가입된 계정이 있습니다.'
                return render_template('register_boss.html', error=error)

        # username 자동 생성 (회사명 + 'boss')
        base_username = f"{company}boss"
        username = base_username
        suffix = 1
        while username in users_db:
            username = f"{base_username}{suffix}"
            suffix += 1

        # 회원가입 처리
        users_db[username] = {
            'password': password,
            'role': 'boss',
            'company': company,
            'phone': phone,
            'company_code': input_code
        }
        save_json('users.json', users_db)

        # companies.json에 새 회사와 코드 등록
        companies[company] = {
            'code': input_code,
            'phone': phone
        }
        save_json('companies.json', companies)

        # 관련 JSON 초기화 (회사별 빈 리스트 생성)
        save_json('workers.json', {**load_json('workers.json', {}), company: []})
        save_json('machines.json', {**load_json('machines.json', {}), company: []})
        save_json('clients.json', {**load_json('clients.json', {}), company: []})
        save_json('jobs.json', {**load_json('jobs.json', {}), company: []})

        # 로그인 세션 설정
        session['username'] = username

        return redirect(url_for('dashboard'))

    return render_template('register_boss.html')

@app.route('/register/worker', methods=['GET', 'POST'])
def register_worker():
    companies = load_json('companies.json', {})

    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        company = request.form['company']
        input_code = request.form['company_code']
        password = request.form['password']

        # 회사명 존재 여부 확인
        if company not in companies:
            error = '존재하지 않는 회사명입니다.'
            return render_template('register_worker.html', companies=sorted(companies.keys()), error=error)

        # 회사 코드 인증
        if companies[company]['code'] != input_code:
            error = '회사 코드가 올바르지 않습니다.'
            return render_template('register_worker.html', companies=sorted(companies.keys()), error=error)

        # 전화번호 중복 검사
        users_db = load_json('users.json', {})
        for user in users_db.values():
            if user.get('company') == company and user.get('phone') == phone:
                error = '해당 전화번호로 이미 가입된 계정이 있습니다.'
                return render_template('register_worker.html', companies=sorted(companies.keys()), error=error)

        # username 자동 생성 (회사명 + 이름 + 중복 방지 숫자)
        base_username = f"{company.strip()}{name.strip()}"
        username = base_username
        suffix = 1
        while username in users_db:
            username = f"{base_username}{suffix}"
            suffix += 1

        # 회원가입 처리
        users_db[username] = {
            'password': password,
            'role': 'worker',
            'company': company,
            'name': name,
            'phone': phone
        }
        save_json('users.json', users_db)

        # workers.json에도 username 포함해 자동 등록
        workers_db = load_json('workers.json', {})
        workers_db.setdefault(company, []).append({
            'username': username,
            'name': name,
            'phone': phone
        })
        save_json('workers.json', workers_db)

        # 로그인 세션 설정
        session['username'] = username
        return redirect(url_for('dashboard'))

    return render_template('register_worker.html', companies=sorted(companies.keys()))

@app.route('/add_worker', methods=['GET', 'POST'])
def add_worker():
    if 'username' not in session:
        return redirect('/login')

    company = users[session['username']]['company']

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            error = "기사 이름을 입력해 주세요."
            workers = load_json('workers.json', {}).get(company, [])
            return render_template('add_worker.html', workers=workers, error=error)

        workers_db = load_json('workers.json', {})
        workers = workers_db.get(company, [])
        # 중복 등록 방지
        if name not in workers:
            workers.append(name)
            workers_db[company] = workers
            save_json('workers.json', workers_db)

        return redirect('/add_worker')

    workers = load_json('workers.json', {}).get(company, [])
    return render_template('add_worker.html', workers=workers)

@app.route('/delete_worker', methods=['POST'])
def delete_worker():
    if 'username' not in session:
        return redirect('/login')

    company = users[session['username']]['company']
    name = request.form.get('name', '').strip()

    workers_db = load_json('workers.json', {})
    workers = workers_db.get(company, [])
    workers = [w for w in workers if w != name]
    workers_db[company] = workers
    save_json('workers.json', workers_db)

    return redirect('/add_worker')

@app.route('/add_machine', methods=['GET', 'POST'])
def add_machine():
    if 'username' not in session:
        return redirect('/login')

    company = users[session['username']]['company']

    if request.method == 'POST':
        name = request.form.get('machine_name', '').strip()
        number = request.form.get('machine_number', '').strip()
        alias = request.form.get('machine_alias', '').strip()

        if not name or not number:
            error = "장비명과 차량번호는 필수 입력입니다."
            machines = load_json('machines.json', {}).get(company, [])
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

    machines = load_json('machines.json', {}).get(company, [])
    return render_template('add_machine.html', machines=machines)

@app.route('/delete_machine', methods=['POST'])
def delete_machine():
    if 'username' not in session:
        return redirect('/login')

    company = users[session['username']]['company']
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

    company = users[session['username']]['company']

    if request.method == 'POST':
        # 1. 기사 입력 (드롭다운 + 직접입력)
        worker_select = request.form.get('worker_select', '').strip()
        worker_input  = request.form.get('worker_input', '').strip()
        worker = worker_input if worker_input else worker_select

        # 2. 장비 입력 (드롭다운 + 직접입력: 3필드)
        machine_select_name   = request.form.get('machine_select_name', '').strip()
        machine_select_number = request.form.get('machine_select_number', '').strip()
        machine_select_alias  = request.form.get('machine_select_alias', '').strip()
        # 직접입력
        machine_name_input    = request.form.get('machine_name_input', '').strip()
        machine_number_input  = request.form.get('machine_number_input', '').strip()
        machine_alias_input   = request.form.get('machine_alias_input', '').strip()
        # 실제 사용값
        machine_name   = machine_name_input if machine_name_input else machine_select_name
        machine_number = machine_number_input if machine_number_input else machine_select_number
        machine_alias  = machine_alias_input if machine_alias_input else machine_select_alias

        # 3. 거래처, 위치 (기존대로)
        client_select   = request.form.get('client_select', '').strip()
        client_input    = request.form.get('client_input', '').strip()
        client = client_input if client_input else client_select

        location_select = request.form.get('location_select', '').strip()
        location_input  = request.form.get('location_input', '').strip()
        location = location_input if location_input else location_select

        note = request.form.get('note', '').strip()
        date = request.form.get('date', '').strip()
        time = request.form.get('time', '').strip()

        # 4. 필수 입력 체크
        if not worker or not machine_name or not machine_number or not client or not location:
            workers   = load_json('workers.json', {}).get(company, [])
            machines  = load_json('machines.json', {}).get(company, [])
            clients   = load_json('clients.json', {}).get(company, [])
            locations = load_json('locations.json', {}).get(company, [])
            error = "기사, 장비명, 차량번호, 거래처, 위치는 반드시 입력(혹은 선택)해야 합니다."
            return render_template(
                'add_job.html',
                workers=workers,
                machines=machines,
                clients=clients,
                locations=locations,
                error=error,
                prev={
                    'worker_input': worker_input,
                    'worker_select': worker_select,
                    'machine_name_input': machine_name_input,
                    'machine_number_input': machine_number_input,
                    'machine_alias_input': machine_alias_input,
                    'machine_select_name': machine_select_name,
                    'machine_select_number': machine_select_number,
                    'machine_select_alias': machine_select_alias,
                    'client_input': client_input,
                    'client_select': client_select,
                    'location_input': location_input,
                    'location_select': location_select,
                    'note': note,
                    'date': date,
                    'time': time
                }
            )

        # 5. 작업 등록
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

        print("새 작업 등록 데이터:", new_job)

        jobs_db = load_json('jobs.json', {})
        jobs_db.setdefault(company, []).append(new_job)
        save_json('jobs.json', jobs_db)

        return redirect('/jobs')  # 작업목록으로

    # GET: 드롭다운 데이터 준비
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

    # 권한 확인: 해당 작업의 기사와 로그인 사용자 일치 여부 체크
    if job.get('worker') != username:
        return "권한이 없습니다.", 403

    # 상태 토글
    job['status'] = '완료' if job.get('status') != '완료' else '진행중'

    save_json('jobs.json', jobs_db)

    return redirect(url_for('dashboard_worker'))

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
    user = users.get(username)

    if not user or user['role'] != 'boss':
        return "권한이 없습니다.", 403

    company = user['company']
    companies = load_json('companies.json', {})
    company_info = companies.get(company, {})

    error = None
    success = None

    if request.method == 'POST':
        new_company_name = request.form['company']
        new_phone = request.form['phone']
        new_password = request.form['password']
        new_company_code = request.form['company_code']

        # 간단한 유효성 검사
        if len(new_company_code) != 6:
            error = '회사 코드는 6자리여야 합니다.'
        elif new_company_name != company and new_company_name in companies:
            error = '이미 존재하는 회사명입니다.'
        else:
            # users.json 수정 - 회사명, 전화번호, 비밀번호 변경
            if new_company_name != company:
                # 회사명 변경시 users 딕셔너리 내 모든 관련 데이터(사장, 기사 등) 회사명 변경 필요
                # 간단하게 사장만 변경 예시 (실제로는 기사도 함께 처리하는게 좋음)
                users[username]['company'] = new_company_name

                # companies.json 회사명 변경 (이름 키 변경)
                companies[new_company_name] = companies.pop(company)
                company = new_company_name  # 회사명 변수도 변경

            users[username]['phone'] = new_phone
            if new_password.strip():
                users[username]['password'] = new_password

            save_json('users.json', users)

            # companies.json 수정 - 회사 전화번호, 코드 변경
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
