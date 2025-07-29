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
    error = None
    if request.method == 'POST':
        phone = request.form.get('phone')
        password = request.form.get('password')

        users_db = load_json('users.json', {})
        # 전화번호로 사용자 찾기
        user = None
        username = None
        for u_name, u_data in users_db.items():
            if u_data.get('phone') == phone:
                user = u_data
                username = u_name
                break

        if user and user.get('password') == password:
            session.permanent = True
            session['username'] = username
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
    if not username or username not in users:
        return redirect(url_for('login'))

    user_info = users[username]
    role = user_info.get('role')

    if role == 'boss':
        # 사장용 대시보드 렌더링
        return render_template('dashboard.html', username=username, role=role)
    elif role == 'worker':
        # 기사용 대시보드 페이지로 리다이렉트
        return redirect(url_for('dashboard_worker'))
    else:
        return "권한이 없습니다.", 403
    
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

@app.route('/register/role', methods=['GET', 'POST'])
def choose_role():
    return render_template('choose_role.html')

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

        print("새 작업 등록 데이터:", new_job)

        jobs_db = load_json('jobs.json', {})
        print("저장 전 작업 수:", len(jobs_db.get(company, [])))

        jobs_db.setdefault(company, []).append(new_job)
        save_json('jobs.json', jobs_db)

        print("저장 후 작업 수:", len(jobs_db.get(company, [])))

        return redirect('/jobs')  # POST 처리 후 리다이렉트

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
