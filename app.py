from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
from datetime import timedelta
from functools import wraps
import json
import os
from io import StringIO
import csv
import datetime as _dt
from io import BytesIO
import datetime as _dt

# --- paths ---
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# 데이터 폴더 보장
DATA_DIR.mkdir(exist_ok=True)

# === JSON 유틸 (단일 정의로 통합) ===
def load_json(filename, default):
    """
    data/<filename>를 JSON으로 로드. 파일이 없거나 JSON 파싱 실패 시 default 반환.
    """
    p = DATA_DIR / filename
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(filename, data):
    """
    data/<filename>에 JSON 저장. .tmp로 쓰고 원자적 교체(os.replace)로 안전성 확보.
    """
    p = DATA_DIR / filename
    tmp = p.with_name(p.name + ".tmp")  # file.json.tmp (이전 동작과 동일한 형태)
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)

app = Flask(__name__)
app.secret_key = "your_secret_key"
app.permanent_session_lifetime = timedelta(days=7)

def _seed_company_containers(company):
    for fname, seed in [
        ("workers.json", []),
        ("machines.json", []),
        ("clients.json", []),
        ("partners.json", {"owners": [], "tenants": []}),
        ("jobs.json", []),
    ]:
        db = load_json(fname, {})
        if company not in db:
            db[company] = seed
            save_json(fname, db)

# === 유틸 ===
def get_current_user():
    users = load_json('users.json', {})
    return users.get(session.get('username'), {}) or {}

def is_admin(user=None):
    if user is None:
        user = get_current_user()
    return (user.get('role') in ('boss', 'manager'))

def redirect_with_from(endpoint, **kwargs):
    """작업등록 등에서 ?from=add_job 을 보존하며 리다이렉트"""
    src = request.args.get('from') or request.form.get('from')
    if src:
        kwargs['from'] = src
    return redirect(url_for(endpoint, **kwargs))

# ⚠️ 기존에 동일한 이름으로 두 번 정의되던 back_with_error를 통합
def back_with_error(*args, **kwargs):
    """
    두 형태 모두 지원:
    - back_with_error("메시지") -> alert 후 뒤로가기
    - back_with_error(endpoint, "메시지", **qs) -> ?error=... 붙여 redirect_with_from
    """
    # 단일 메시지 형태
    if len(args) == 1 and isinstance(args[0], str):
        msg = args[0]
        return f"<script>alert({json.dumps(msg, ensure_ascii=False)});history.back();</script>"
    # 리다이렉트 형태
    if len(args) >= 2:
        endpoint, message = args[0], args[1]
        return redirect_with_from(endpoint, error=message, **kwargs)
    # 안전한 기본값
    return redirect(url_for('home'))

def ensure_user_entry(users_db, workers_db, company, username):
    """
    users.json에 username이 없으면 workers.json 정보를 이용해 생성.
    반환: users_db[username] 또는 None
    """
    if username in users_db:
        return users_db[username]

    worker = None
    for w in workers_db.get(company, []):
        if w.get('username') == username:
            worker = w
            break
    if not worker:
        return None

    phone = (worker.get('phone') or '').strip()
    default_pw = (phone[-4:] if len(phone) >= 4 else phone) or "0000"
    users_db[username] = {
        'password': default_pw,
        'role': worker.get('role') or 'worker',
        'company': company,
        'name': worker.get('name', ''),
        'phone': phone,
        'status': worker.get('status') or 'active',
    }
    return users_db[username]

def jinja_split(value, sep=':', maxsplit=-1):
    try:
        return (value or '').split(sep, maxsplit)
    except Exception:
        return []
app.jinja_env.filters['split'] = jinja_split
app.jinja_env.globals['str'] = str
app.jinja_env.filters['string'] = lambda x: '' if x is None else str(x)

# === 거래처(원수급자/임차인) 유틸 ===
def load_partners(company: str):
    """partners.json에서 회사별 원수급자/임차인 목록 로드.
       없으면 (레거시) clients.json의 리스트를 원수급자로 시드."""
    data = load_json('partners.json', {})
    entry = data.get(company)
    if not entry:
        legacy = load_json('clients.json', {}).get(company, [])
        entry = {"owners": legacy[:], "tenants": []}
        data[company] = entry
        save_json('partners.json', data)
    return entry

def save_partners(company: str, owners: list, tenants: list):
    data = load_json('partners.json', {})
    data[company] = {"owners": owners, "tenants": tenants}
    save_json('partners.json', data)

# ---------------------------
# 권한
# ---------------------------
PERMISSIONS = {
    'boss': {
        'view_dashboard', 'manage_clients', 'manage_jobs',
        'manage_workers', 'manage_machines',
        'approve_workers', 'manage_roles',
        'manage_payments'
    },
    'manager': {
        'view_dashboard', 'manage_clients', 'manage_jobs',
        'manage_workers', 'manage_machines',
        'manage_payments'
    },
    'worker': {
        'view_dashboard_worker', 'view_my_jobs', 'update_job_status'
    }
}

def has_perm(perm: str) -> bool:
    role = session.get('role')
    return perm in PERMISSIONS.get(role, set())

def perm_required(*perms):
    def deco(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not session.get('username'):
                return redirect(url_for('login'))
            if not any(has_perm(p) for p in perms):
                return redirect(url_for('dashboard_worker'))
            return f(*args, **kwargs)
        return wrapped
    return deco

@app.context_processor
def inject_perms():
    return dict(has_perm=has_perm, session_role=session.get('role'))

# ---------------------------
# 홈/인증
# ---------------------------
@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('dashboard'))
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

            if user['role'] in ('boss', 'manager'):
                return redirect(url_for('dashboard'))
            return redirect(url_for('dashboard_worker'))
        else:
            error = '휴대폰번호 또는 비밀번호가 올바르지 않습니다.'
    return render_template('login.html', error=error)

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))

# 템플릿 호환용: url_for('manage_machines', ...) 사용 계속 가능
@app.route('/machines', methods=['GET', 'POST'], endpoint='manage_machines')
def manage_machines_alias():
    return add_machine()

# ---------------------------
# 대시보드
# ---------------------------
@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    if not is_admin():
        return redirect(url_for('dashboard_worker'))
    return render_template('dashboard.html')

@app.route('/dashboard_worker')
def dashboard_worker():
    if 'username' not in session:
        return redirect(url_for('login'))
    if is_admin():
        return redirect(url_for('dashboard'))
    return render_template('dashboard_worker.html')

# ---------------------------
# 작업 목록(사장/매니저)
# ---------------------------
@app.route('/jobs', endpoint='view_jobs')
@app.route('/view_jobs', endpoint='view_jobs_legacy')
def view_jobs():
    if 'username' not in session:
        return redirect(url_for('login'))

    user = get_current_user()
    if not is_admin(user):
        return redirect(url_for('dashboard_worker'))

    company = user.get('company', '')
    jobs_all = load_json('jobs.json', {}).get(company, [])
    for i, j in enumerate(jobs_all):
        j['_idx'] = i

    partners = load_partners(company)
    owners_list  = partners.get('owners', [])
    tenants_list = partners.get('tenants', [])

    q_worker = (request.args.get('worker') or '').strip()
    q_owner  = (request.args.get('owner') or request.args.get('client_primary') or request.args.get('client') or '').strip()
    q_tenant = (request.args.get('tenant') or request.args.get('client_tenant') or '').strip()
    q_date   = (request.args.get('date') or '').strip() 
    q_from   = (request.args.get('date_from') or '').strip()
    q_to     = (request.args.get('date_to') or '').strip()

    overdue = (request.args.get('overdue') or '').strip()
    dues    = (request.args.get('dues')    or '').strip()
    spare   = (request.args.get('spare')   or '').strip()
    outsrc  = (request.args.get('outsrc')  or '').strip()

    def _contains(hay, needle):
        return (needle == '' or (hay or '').lower().find(needle.lower()) != -1)

    jobs = jobs_all
    if q_worker:
        jobs = [j for j in jobs if (j.get('worker') or '') == q_worker]
    if q_owner:
        jobs = [j for j in jobs if _contains(j.get('client_primary') or j.get('client'), q_owner)]
    if q_tenant:
        jobs = [j for j in jobs if _contains(j.get('client_tenant'), q_tenant)]
    if q_from or q_to:
        def in_range(d):
                if not d: return False
                return (not q_from or d >= q_from) and (not q_to or d <= q_to)
        jobs = [j for j in jobs if in_range((j.get('date') or '').strip())]
    elif q_date:
        jobs = [j for j in jobs if q_date == (j.get('date') or '')]

    if overdue == '1':
        jobs = [j for j in jobs if (j.get('status') or '진행중').strip() != '완료']
    if dues == '1':
        def _to_int(x):
            try: return int(x)
            except: return 0
        jobs = [j for j in jobs if _to_int(j.get('amount_man')) > 0 and _to_int(j.get('paid_amount_man')) < _to_int(j.get('amount_man'))]
    if spare == '1':
        jobs = [j for j in jobs if bool(j.get('is_spare'))]
    if outsrc == '1':
        jobs = [j for j in jobs if (j.get('outsource_type') or 'none') != 'none']

    args_dict = request.args.to_dict(flat=True)
    def _onoff(key):
        on  = args_dict.copy(); on[key] = '1'
        off = args_dict.copy(); off.pop(key, None)
        return url_for('view_jobs', **on), url_for('view_jobs', **off)

    overdue_on_url, overdue_off_url = _onoff('overdue')
    dues_on_url,    dues_off_url    = _onoff('dues')
    spare_on_url,   spare_off_url   = _onoff('spare')
    outsrc_on_url,  outsrc_off_url  = _onoff('outsrc')

    return render_template(
        'view_job.html',
        jobs=jobs,
        overdue=overdue, overdue_on_url=overdue_on_url, overdue_off_url=overdue_off_url,
        dues=dues,       dues_on_url=dues_on_url,         dues_off_url=dues_off_url,
        spare=spare,     spare_on_url=spare_on_url,       spare_off_url=spare_off_url,
        outsrc=outsrc,   outsrc_on_url=outsrc_on_url,     outsrc_off_url=outsrc_off_url,
        q_worker=q_worker, q_owner=q_owner, q_tenant=q_tenant, q_date=q_date,
        owners=owners_list, tenants=tenants_list,
        q_from=q_from, q_to=q_to
    )

# ---------------------------
# 작업 등록/수정/삭제
# ---------------------------
@app.route('/add_job', methods=['GET', 'POST'])
@perm_required('manage_jobs')
def add_job():
    users_db = load_json('users.json', {})
    username = session.get('username')
    company = users_db.get(username, {}).get('company', '')

    workers   = load_json('workers.json',   {}).get(company, [])
    machines  = load_json('machines.json',  {}).get(company, [])
    locations = load_json('locations.json', {}).get(company, [])
    partners  = load_partners(company)
    owners    = partners.get('owners', [])
    tenants   = partners.get('tenants', [])

    if request.method == 'POST':
        time_str = (request.form.get('time') or '').strip()
        if not time_str:
            hour   = (request.form.get('hour')   or '').strip()
            minute = (request.form.get('minute') or '').strip()
            if hour and not minute:
                minute = '00'
            time_str = f"{hour}:{minute}" if hour and minute else ''
        date = (request.form.get('date') or '').strip()

        worker = (request.form.get('worker_input') or request.form.get('worker') or '').strip()

        machine_name   = (request.form.get('machine_name_input')   or request.form.get('machine_name')   or '').strip()
        machine_number = (request.form.get('machine_number_input') or request.form.get('machine_number') or '').strip()
        machine_alias  = (request.form.get('machine_alias_input')  or request.form.get('machine_alias')  or '').strip()

        client_primary = (request.form.get('client_primary') or request.form.get('client') or '').strip()
        client_tenant  = (request.form.get('client_tenant')  or '').strip()
        if request.form.get('same_as_owner'):
            client_tenant = client_primary

        if request.form.get('save_owner') == '1' and client_primary and client_primary not in owners:
            owners.append(client_primary)
        if request.form.get('save_tenant') == '1' and client_tenant and client_tenant not in tenants:
            tenants.append(client_tenant)
        save_partners(company, owners, tenants)

        location = (request.form.get('location_input') or request.form.get('location') or '').strip()
        note     = (request.form.get('note') or '').strip()

        duration_type  = (request.form.get('duration_type')  or '하루').strip()
        duration_hours = (request.form.get('duration_hours') or '').strip()
        if duration_type == 'N시간':
            try:
                n = int(duration_hours)
                if not (1 <= n <= 24):
                    raise ValueError()
            except Exception:
                return render_template(
                    'add_job.html',
                    workers=workers, machines=machines, locations=locations,
                    owners=owners, tenants=tenants,
                    error="N시간을 선택했으면 1~24시간 중 하나를 선택해야 합니다.",
                    prev=request.form,
                    job_registered=False
                )
        else:
            duration_hours = ''

        amount_raw = (request.form.get('amount_man') or '').strip()
        try:
            amount_man = int(amount_raw) if amount_raw != '' else 0
        except ValueError:
            amount_man = 0
        share_amount = bool(request.form.get('share_amount'))

        outsource_type = (request.form.get('outsource_type') or 'none').strip()
        if outsource_type not in ('none', 'received', 'given'):
            outsource_type = 'none'
        outsource_partner = (request.form.get('outsource_partner') or '').strip()

        missing = []
        if not worker: missing.append('기사')
        if not machine_name: missing.append('장비명')
        if not machine_number: missing.append('차량번호')
        if not client_primary: missing.append('원수급자')
        if not location: missing.append('위치')
        if not date: missing.append('날짜')
        if not time_str: missing.append('시간')
        if missing:
            return render_template(
                'add_job.html',
                workers=workers, machines=machines, locations=locations,
                owners=owners, tenants=tenants,
                error="다음 항목을 확인해 주세요: " + ", ".join(missing),
                prev=request.form,
                job_registered=False
            )

        payment_status  = '미설정' if amount_man <= 0 else '미납'
        paid_amount_man = 0

        new_job = {
            "date": date, "time": time_str,
            "worker": worker, "is_spare": bool(request.form.get('is_spare')),
            "machine_name": machine_name,
            "machine_number": machine_number,
            "machine_alias": machine_alias,
            "client_primary": client_primary,
            "client_tenant":  client_tenant,
            "client": client_primary,
            "location": location,
            "note": note,
            "status": "진행중",
            "duration_type": duration_type,
            "duration_hours": duration_hours,
            "amount_man": amount_man,
            "share_amount": share_amount,
            "outsource_type": outsource_type,
            "outsource_partner": outsource_partner,
            "payment_status":  payment_status,
            "paid_amount_man": paid_amount_man
        }

        # 위치 최근 20개 저장
        try:
            locdb = load_json('locations.json', {})
            locs = locdb.get(company, [])
            if location:
                locs = [location] + [x for x in locs if x != location]
                locs = locs[:20]
                locdb[company] = locs
                save_json('locations.json', locdb)
                locations = locs
        except Exception as e:
            app.logger.warning(f"locations.json 업데이트 실패: {e}")

        jobs_db = load_json('jobs.json', {})
        jobs_db.setdefault(company, []).append(new_job)
        save_json('jobs.json', jobs_db)

        return render_template(
            'add_job.html',
            workers=workers, machines=machines, locations=locations,
            owners=owners, tenants=tenants,
            prev={}, job_registered=True
        )

    return render_template(
        'add_job.html',
        workers=workers, machines=machines, locations=locations,
        owners=owners, tenants=tenants,
        prev={}, job_registered=False
    )

@app.route('/edit_job/<int:job_index>', methods=['GET', 'POST'])
@perm_required('manage_jobs')
def edit_job(job_index):
    username = session['username']
    users_db = load_json('users.json', {})
    company  = users_db.get(username, {}).get('company')

    jobs_db  = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])
    if not (0 <= job_index < len(job_list)):
        return "작업을 찾을 수 없습니다.", 404
    job = job_list[job_index]

    machines  = load_json('machines.json',  {}).get(company, [])
    workers   = load_json('workers.json',   {}).get(company, [])
    locations = load_json('locations.json', {}).get(company, [])
    partners  = load_partners(company)
    owners    = partners.get('owners', [])
    tenants   = partners.get('tenants', [])

    if request.method == 'POST':
        # 시간: hidden time 우선, 없으면 hour/minute로 보완
        t = (request.form.get('time') or '').strip()
        if not t:
            hh = (request.form.get('hour') or '').strip()
            mm = (request.form.get('minute') or '').strip()
            if hh and mm:
                t = f"{hh}:{mm}"
        job['time']           = t
        job['date']           = (request.form.get('date') or '').strip()
        job['worker']         = (request.form.get('worker') or '').strip()
        job['machine_name']   = (request.form.get('machine_name') or '').strip()
        job['machine_number'] = (request.form.get('machine_number') or '').strip()
        job['machine_alias']  = (request.form.get('machine_alias') or '').strip()

        client_primary = (request.form.get('client_primary') or '').strip()
        client_tenant  = (request.form.get('client_tenant')  or '').strip()
        if request.form.get('same_as_owner'):
            client_tenant = client_primary
        job['client_primary'] = client_primary
        job['client_tenant']  = client_tenant
        job['client']         = client_primary

        # 거래처 저장 옵션
        if request.form.get('save_owner') == '1' and client_primary and client_primary not in owners:
            owners.append(client_primary)
        if request.form.get('save_tenant') == '1' and client_tenant and client_tenant not in tenants:
            tenants.append(client_tenant)
        save_partners(company, owners, tenants)

        job['location'] = (request.form.get('location') or '').strip()
        job['note']     = (request.form.get('note') or '').strip()
        job['is_spare'] = bool(request.form.get('is_spare'))

        ot = (request.form.get('outsource_type') or 'none').strip()
        if ot not in ('none', 'received', 'given'):
            ot = 'none'
        job['outsource_type']    = ot
        job['outsource_partner'] = (request.form.get('outsource_partner') or '').strip()

        # 금액/지불 상태
        amount_raw = (request.form.get('amount_man') or '').strip()
        try:
            amount_man = int(amount_raw) if amount_raw != '' else 0
        except ValueError:
            amount_man = 0
        job['amount_man']   = amount_man
        job['share_amount'] = bool(request.form.get('share_amount'))

        old_paid = int(job.get('paid_amount_man') or 0)
        if amount_man <= 0:
            job['paid_amount_man'] = 0
            job['payment_status']  = '미설정'
        else:
            paid = max(0, min(old_paid, amount_man))
            job['paid_amount_man'] = paid
            if paid == 0:
                job['payment_status'] = '미납'
            elif paid >= amount_man:
                job['payment_status'] = '완납'
            else:
                job['payment_status'] = '부분'

        # 작업시간(하루/반나절/N시간)도 반영
        job['duration_type']  = (request.form.get('duration_type') or '하루').strip()
        job['duration_hours'] = (request.form.get('duration_hours') or '').strip() if job['duration_type'] == 'N시간' else ''

        save_json('jobs.json', jobs_db)

        # 목록 필터 유지해서 돌아가기 (edit_job.html에서 넣어준 filter_* 히든들 사용)
        params = {}
        for k, v in request.form.items():
            if k.startswith('filter_') and v != '':
                params[k[7:]] = v
        return redirect(url_for('view_jobs', **params))

    return render_template(
        'edit_job.html',
        job=job, job_index=job_index,
        machines=machines, workers=workers, locations=locations,
        owners=owners, tenants=tenants
    )

@app.route('/delete_job/<int:job_index>')
@perm_required('manage_jobs')
def delete_job(job_index):
    username = session['username']
    users_db = load_json('users.json', {})
    company = users_db.get(username, {}).get('company')

    jobs_db = load_json('jobs.json', {})
    job_list = jobs_db.get(company, [])
    if not (0 <= job_index < len(job_list)):
        return "작업을 찾을 수 없습니다.", 404

    job_list.pop(job_index)
    save_json('jobs.json', jobs_db)
    return redirect(url_for('view_jobs', **request.args))

# ---------------------------
# 일괄 처리
# ---------------------------
@app.route('/bulk_action', methods=['POST'])
@perm_required('manage_jobs')
def bulk_action():
    action = request.form.get('action', '').strip()
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
        for idx in sorted(set(selected), reverse=True):
            if 0 <= idx < len(jobs):
                jobs.pop(idx)

    db[company] = jobs
    save_json('jobs.json', db)
    return redirect(url_for('view_jobs'))

@app.route('/export_selected', methods=['POST'])
@perm_required('manage_jobs')
def export_selected():
    users_db = load_json('users.json', {})
    user = users_db.get(session['username'], {})
    company = user.get('company', '')

    # 선택 인덱스 수집
    try:
        selected = [int(x) for x in request.form.getlist('selected_jobs')]
    except ValueError:
        selected = []
    if not selected:
        return back_with_error("선택된 작업이 없습니다.")

    db = load_json('jobs.json', {})
    jobs = db.get(company, [])

    rows = []
    for idx in selected:
        if 0 <= idx < len(jobs):
            j = jobs[idx]
            rows.append([
                idx,
                j.get('date',''),
                j.get('time',''),
                j.get('worker',''),
                j.get('machine_name',''),
                j.get('machine_number',''),
                j.get('machine_alias',''),
                (j.get('client_primary') or j.get('client','')),
                j.get('client_tenant',''),
                j.get('location',''),
                j.get('status',''),
                j.get('duration_type',''),
                j.get('duration_hours',''),
                int(j.get('amount_man') or 0),
                'Y' if j.get('share_amount') else '',
                j.get('outsource_type',''),
                j.get('outsource_partner',''),
                j.get('payment_status',''),
                int(j.get('paid_amount_man') or 0),
            ])

    if not rows:
        return back_with_error("선택된 작업이 없습니다.")

    filename = f"jobs_selected_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    # Excel 한글깨짐 방지용 BOM
    s = StringIO()
    s.write('\ufeff')
    writer = csv.writer(s)
    writer.writerow([
        'index','date','time','worker',
        'machine_name','machine_number','machine_alias',
        'client_primary','client_tenant','location',
        'status','duration_type','duration_hours',
        'amount_man','share_amount',
        'outsource_type','outsource_partner',
        'payment_status','paid_amount_man'
    ])
    writer.writerows(rows)
    data = s.getvalue()

    return Response(
        data,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )

# ---------------------------
# 선택 항목 XLSX 내보내기 (중복 방지: _v2)
# ---------------------------
@app.route('/export_selected_xlsx', methods=['POST'])
@perm_required('manage_jobs')
def export_selected_xlsx():
    from io import BytesIO
    import datetime as _dt
    from urllib.parse import quote
    from flask import Response
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Border, Side, Alignment, Font
    except Exception:
        # 목록 화면으로 돌아가며 안내
        return back_with_error('view_jobs', "서버에 openpyxl 패키지가 없습니다. 가상환경에서 'pip install openpyxl' 후 다시 시도해 주세요.")

    # 회사/선택 인덱스
    users_db = load_json('users.json', {})
    user = users_db.get(session['username'], {})
    company = user.get('company', '')
    try:
        selected = [int(x) for x in request.form.getlist('selected_jobs')]
    except ValueError:
        selected = []
    if not selected:
        return back_with_error('view_jobs', "선택된 작업이 없습니다.")

    jobs = load_json('jobs.json', {}).get(company, [])

    # 워크북/시트/헤더(분담 삭제, 받은/제공 외주 분리, 컬럼 순서 지정)
    wb = Workbook()
    ws = wb.active
    ws.title = "작업목록(선택)"
    headers = [
        "날짜","시간","기사","장비명","차량번호","별칭",
        "원수급자","임차인","위치","상태","작업시간",
        "받은 외주","제공 외주",
        "지불상태","지불금액(만)","총금액(만)"
    ]
    ws.append(headers)

    def to_worktime(d_type, d_hours):
        d_type = (d_type or '').strip()
        d_hours = str(d_hours or '').strip()
        if d_type == '하루':
            return '하루'
        if d_type == '반나절':
            return '반나절'
        if d_type == 'N시간' and d_hours.isdigit():
            return f"{int(d_hours)}시간"
        return ''

    for idx in selected:
        if 0 <= idx < len(jobs):
            j = jobs[idx]
            # 받은/제공 외주 칸에 파트너 배치
            ot = (j.get('outsource_type') or 'none').strip()
            partner = j.get('outsource_partner', '') or ''
            recv_col = partner if ot == 'received' else ''
            give_col = partner if ot == 'given' else ''

            amount = int(j.get('amount_man') or 0)
            paid   = int(j.get('paid_amount_man') or 0)

            ws.append([
                j.get('date',''), j.get('time',''), j.get('worker',''),
                j.get('machine_name',''), j.get('machine_number',''), j.get('machine_alias',''),
                (j.get('client_primary') or j.get('client','')), j.get('client_tenant',''),
                j.get('location',''), j.get('status',''),
                to_worktime(j.get('duration_type'), j.get('duration_hours')),
                recv_col, give_col,
                j.get('payment_status',''), paid, amount
            ])

    # 테두리/정렬
    thin   = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    center = Alignment(horizontal='center', vertical='center')
    left   = Alignment(horizontal='left',   vertical='center')

    # 헤더 스타일
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = center
        c.border = thin

    # 본문 스타일
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=ws.max_column):
        for c in row:
            c.border = thin
            # 텍스트 위주 컬럼은 좌정렬
            if c.column_letter in ['D','E','F','G','H','I','L','M']:  # 장비/거래처/위치/외주 칼럼들
                c.alignment = left
            else:
                c.alignment = center

    # 열 너비: 글자수 기반 + 여백(+4), 최대 10칸까지 보여주고 여백으로 덜 빡빡하게
    maxlen = {}
    for row in ws.iter_rows(values_only=True):
        for i, v in enumerate(row, start=1):
            L = len(str(v)) if v is not None else 0
            maxlen[i] = max(maxlen.get(i, 0), L)
    for i, L in maxlen.items():
        col = ws.cell(row=1, column=i).column_letter
        ws.column_dimensions[col].width = min(L, 10) + 4   # ← 여백 넉넉(+4)

    # 파일 응답 (한글 파일명 깨짐 방지)
    bio = BytesIO()
    wb.save(bio); bio.seek(0)
    filename = f"작업목록_선택_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    quoted = quote(filename)
    return Response(
        bio.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={quoted}; filename*=UTF-8''{quoted}"
        }
    )
# ---------------------------
# 상태 토글 API
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

    if role == 'worker' and (jobs[job_index].get('worker') or '') != username:
        return jsonify(success=False, error='forbidden'), 403

    cur = (jobs[job_index].get('status') or '진행중').strip()
    new_status = '완료' if cur != '완료' else '진행중'
    jobs[job_index]['status'] = new_status

    db[company] = jobs
    save_json('jobs.json', db)
    return jsonify(success=True, status=new_status)

# ---------------------------
# 캘린더
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

    events = []
    for j in jobs:
        d = (j.get('date') or '').strip()
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
# 결제(사장/매니저)
# ---------------------------
@app.route('/api/payment/<int:job_index>', methods=['POST'], endpoint='payment_api')
@perm_required('manage_payments')
def payment_api(job_index):
    users_db = load_json('users.json', {})
    user = users_db.get(session['username'], {})
    company = user.get('company', '')

    db = load_json('jobs.json', {})
    jobs = db.get(company, [])
    if not (0 <= job_index < len(jobs)):
        return jsonify(success=False, error='index_out_of_range'), 400

    job = jobs[job_index]
    amount = int(job.get('amount_man') or 0)
    paid   = int(job.get('paid_amount_man') or 0)

    data = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip()

    if action == 'full':
        if amount <= 0:
            return jsonify(success=False, error='no_amount'), 400
        paid = amount
        status = '완납'
    elif action == 'unpay':
        paid = 0
        status = '미납' if amount > 0 else '미설정'
    elif action == 'partial':
        if amount <= 0:
            return jsonify(success=False, error='no_amount'), 400
        try:
            add = int(data.get('amount_man'))
        except (TypeError, ValueError):
            return jsonify(success=False, error='invalid_amount'), 400
        paid = max(0, min(amount, paid + add))
        if paid == 0:
            status = '미납'
        elif paid >= amount:
            status = '완납'
        else:
            status = '부분'
    else:
        return jsonify(success=False, error='invalid_action'), 400

    job['paid_amount_man'] = paid
    job['payment_status']  = status
    db[company] = jobs
    save_json('jobs.json', db)

    remaining = max(0, amount - paid)
    return jsonify(success=True, payment_status=status, remaining=remaining,
                   paid_amount_man=paid, amount_man=amount)

# ---------------------------
# 기사/장비/회사 관리
# ---------------------------
@app.route('/add_worker', methods=['GET', 'POST'])
@perm_required('manage_workers')
def add_worker():
    users_db = load_json('users.json', {})
    company = users_db.get(session['username'], {}).get('company', '')

    workers_db = load_json('workers.json', {})
    workers = workers_db.get(company, [])

    if request.method == 'POST':
        name  = (request.form.get('name')  or '').strip()
        phone = (request.form.get('phone') or '').strip()

        if not name or not phone:
            return render_template('add_worker.html', workers=workers,
                                   error="기사 이름과 전화번호를 모두 입력해 주세요.")

        if any(w.get('name') == name or w.get('phone') == phone for w in workers):
            return render_template('add_worker.html', workers=workers,
                                   error="이미 등록된 기사명 또는 전화번호입니다.")

        username = f"{company}{name}"

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

        udb = load_json('users.json', {})
        default_pw = (phone[-4:] if len(phone) >= 4 else phone) or "0000"
        udb[username] = {
            'password': udb.get(username, {}).get('password', default_pw),
            'role': 'worker',
            'company': company,
            'name': name,
            'phone': phone,
            'status': 'active'
        }
        save_json('users.json', udb)

        return redirect_with_from('add_worker')

    err = request.args.get('error')  # 쿼리로 전달된 에러 표시
    return render_template('add_worker.html', workers=workers, error=err)

@app.route('/add_machine', methods=['GET', 'POST'])
@perm_required('manage_machines')
def add_machine():
    users_db = load_json('users.json', {})
    company = users_db[session['username']]['company']

    machines_db = load_json('machines.json', {})
    machines = machines_db.get(company, [])
    error = None

    if request.method == 'POST':
        action = (request.form.get('action') or 'add').strip()

        if action == 'add':
            name = request.form.get('machine_name', '').strip()
            number = request.form.get('machine_number', '').strip()
            alias = request.form.get('machine_alias', '').strip()

            if not name or not number:
                error = "장비명과 차량번호는 필수 입력입니다."
            elif any(m.get('number') == number for m in machines):
                error = f"차량번호 {number} 는 이미 등록되어 있습니다."
            else:
                machines.append({'name': name, 'number': number, 'alias': alias})
                machines_db[company] = machines
                save_json('machines.json', machines_db)
                return redirect_with_from('add_machine')

        elif action == 'edit_save':
            try:
                idx = int(request.form.get('edit_idx', '-1'))
            except ValueError:
                idx = -1
            if 0 <= idx < len(machines):
                machines[idx]['name'] = request.form.get('machine_name', '').strip()
                machines[idx]['number'] = request.form.get('machine_number', '').strip()
                machines[idx]['alias'] = request.form.get('machine_alias', '').strip()
                machines_db[company] = machines
                save_json('machines.json', machines_db)
            return redirect_with_from('add_machine')

        elif action == 'delete':
            number = request.form.get('machine_number', '').strip()
            machines = [m for m in machines if m.get('number') != number]
            machines_db[company] = machines
            save_json('machines.json', machines_db)
            return redirect_with_from('add_machine')

    # GET: ?edit=
    edit_machine = None
    edit_machine_idx = None
    edit_idx = request.args.get('edit')
    if edit_idx is not None and str(edit_idx).isdigit():
        idx = int(edit_idx)
        if 0 <= idx < len(machines):
            edit_machine = machines[idx]
            edit_machine_idx = idx

    return render_template(
        'add_machine.html',
        machines=machines,
        error=error,
        edit_machine=edit_machine,
        edit_machine_idx=edit_machine_idx
    )

@app.route('/manage_workers')
@perm_required('manage_workers')
def manage_workers():
    company = session['company']
    workers_db = load_json('workers.json', {})
    users_db = load_json('users.json', {})

    workers = workers_db.get(company, [])
    for w in workers:
        user_info = users_db.get(w['username'])
        w['role'] = (user_info or {}).get('role', 'worker')
    return render_template('manage_workers.html', workers=workers)

@app.route('/approve_worker/<username>', methods=['POST'])
@perm_required('approve_workers')
def approve_worker(username):
    users = load_json('users.json', {})
    workers_db = load_json('workers.json', {})
    company = load_json('users.json', {}).get(session['username'], {}).get('company','')

    u = users.get(username)
    if not u:
        return back_with_error("사용자 정보를 찾을 수 없습니다.")

    # 승인 처리
    u['status'] = 'active'
    # 가입자가 요청한 전화번호 업데이트가 대기중이면 반영
    pending = (u.get('pending_update') or {})
    if 'phone' in pending and pending['phone']:
        u['phone'] = pending['phone']
        u.pop('pending_update', None)

    # workers.json 동기화
    lst = workers_db.get(u.get('company','') or company, [])
    for w in lst:
        if w.get('username') == username:
            w['status'] = 'active'
            if 'phone' in pending and pending['phone']:
                w['phone'] = pending['phone']
            break
    workers_db[u.get('company','') or company] = lst

    save_json('users.json', users)
    save_json('workers.json', workers_db)
    return redirect_with_from('add_worker')

# 삭제/권한 라우트: path param & query param & form 모두 지원
@app.route('/delete_worker', methods=['POST'])
@app.route('/delete_worker/<username>', methods=['POST'])
@perm_required('manage_workers')
def delete_worker(username=None):
    username = username or request.form.get('username') or request.args.get('username')
    if not username:
        return back_with_error('add_worker', '대상 사용자를 찾을 수 없습니다.')

    users = load_json('users.json', {})
    workers_db = load_json('workers.json', {})
    company = load_json('users.json', {}).get(session['username'], {}).get('company','')

    lst = workers_db.get(company, [])
    workers_db[company] = [w for w in lst if w.get('username') != username]
    if username in users:
        users.pop(username, None)

    save_json('workers.json', workers_db)
    save_json('users.json', users)
    return redirect_with_from('add_worker')

@app.route('/grant_manager', methods=['POST'])
@app.route('/grant_manager/<username>', methods=['POST'])
@perm_required('manage_workers')
def grant_manager(username=None):
    username = username or request.form.get('username') or request.args.get('username')
    if not username:
        return back_with_error('add_worker', '대상 사용자를 찾을 수 없습니다.')

    users = load_json('users.json', {})
    workers_db = load_json('workers.json', {})
    company = load_json('users.json', {}).get(session['username'], {}).get('company','')

    u = ensure_user_entry(users, workers_db, company, username)
    if not u:
        return back_with_error('add_worker', '사용자 정보를 찾을 수 없습니다.')

    u['role'] = 'manager'
    for w in workers_db.get(company, []):
        if w.get('username') == username:
            w['role'] = 'manager'
            break

    save_json('users.json', users)
    save_json('workers.json', workers_db)
    return redirect_with_from('add_worker')

@app.route('/revoke_manager', methods=['POST'])
@app.route('/revoke_manager/<username>', methods=['POST'])
@perm_required('manage_workers')
def revoke_manager(username=None):
    username = username or request.form.get('username') or request.args.get('username')
    if not username:
        return back_with_error('add_worker', '대상 사용자를 찾을 수 없습니다.')

    users = load_json('users.json', {})
    workers_db = load_json('workers.json', {})
    company = load_json('users.json', {}).get(session['username'], {}).get('company','')

    u = ensure_user_entry(users, workers_db, company, username)
    if not u:
        return back_with_error('add_worker', '사용자 정보를 찾을 수 없습니다.')

    if u.get('role') == 'boss':
        return back_with_error('add_worker', '사장 권한은 해제할 수 없습니다.')

    u['role'] = 'worker'
    for w in workers_db.get(company, []):
        if w.get('username') == username:
            w['role'] = 'worker'
            break

    save_json('users.json', users)
    save_json('workers.json', workers_db)
    return redirect_with_from('add_worker')

@app.route('/update_worker/<username>', methods=['GET', 'POST'])
@perm_required('manage_workers')
def update_worker(username):
    company = session['company']
    users_db = load_json('users.json', {})
    workers_db = load_json('workers.json', {})

    user = users_db.get(username)
    if not user or user.get('company') != company:
        return redirect('/manage_workers')

    if user.get('role') == 'boss':
        return "보스 계정은 수정할 수 없습니다.", 403

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        if name:  user['name'] = name
        if phone: user['phone'] = phone
        save_json('users.json', users_db)

        for w in workers_db.get(company, []):
            if w.get('username') == username:
                if name:  w['name'] = name
                if phone: w['phone'] = phone
                break
        workers_db[company] = workers_db.get(company, [])
        save_json('workers.json', workers_db)
        return redirect('/manage_workers')

    return render_template('update_worker.html', user=user)

@app.route('/clients', methods=['GET', 'POST'])
@perm_required('manage_clients')
def manage_clients():
    user = get_current_user()
    company = user.get('company', '')
    entry   = load_partners(company)
    owners  = entry.get('owners', [])
    tenants = entry.get('tenants', [])

    if request.method == 'POST':
        kind   = (request.form.get('kind')   or '').strip()    # 'primary' | 'tenant'
        action = (request.form.get('action') or '').strip()    # 'add' | 'delete'
        name   = (request.form.get('name')   or '').strip()

        if kind not in ('primary', 'tenant') or action not in ('add', 'delete'):
            return redirect_with_from('manage_clients')

        lst = owners if kind == 'primary' else tenants
        if action == 'add':
            if name and name not in lst:
                lst.append(name)
        elif action == 'delete':
            idx = request.form.get('idx')
            if idx not in (None, ''):
                try:
                    i = int(idx)
                    if 0 <= i < len(lst):
                        lst.pop(i)
                except ValueError:
                    pass
            elif name in lst:
                lst.remove(name)

        save_partners(company, owners, tenants)
        return redirect_with_from('manage_clients')

    return render_template('manage_clients.html', owners=owners, tenants=tenants)

# 호환 주소 유지
app.add_url_rule('/manage_clients', view_func=manage_clients, methods=['GET', 'POST'])

@app.route('/company_info', methods=['GET', 'POST'])
@perm_required('manage_roles')
def company_info():
    username = session['username']
    users_db = load_json('users.json', {})
    user = users_db.get(username, {})

    if user.get('role') != 'boss':
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
            # 회사명 변경 시 기존 정보 보존하면서 안전하게 이동
            if new_company_name != company:
                moved = companies.pop(company, {})
                companies[new_company_name] = moved
                users_db[username]['company'] = new_company_name
                company = new_company_name

            users_db[username]['phone'] = new_phone
            if new_password.strip():
                users_db[username]['password'] = new_password
            save_json('users.json', users_db)

            companies.setdefault(company, {})
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
    if request.method == 'POST':
        password     = (request.form.get('password') or '').strip()
        company      = (request.form.get('company') or '').strip()
        phone        = (request.form.get('phone') or '').strip()
        company_code = (request.form.get('company_code') or '').strip()

        if not (password and company and phone and len(company_code) == 6):
            return render_template('register_boss.html', error='모든 값을 올바르게 입력해 주세요.')

        users = load_json('users.json', {})
        companies = load_json('companies.json', {})

        if company in companies:
            return render_template('register_boss.html', error='이미 존재하는 회사명입니다.')
        if any(u.get('phone') == phone for u in users.values()):
            return render_template('register_boss.html', error='해당 전화번호로 이미 가입된 계정이 있습니다.')

        # username 생성
        base_username = f"{company}boss"
        username = base_username
        i = 1
        while username in users:
            username = f"{base_username}{i}"
            i += 1

        # users.json 저장
        users[username] = {
            "password": password,
            "role": "boss",
            "company": company,
            "phone": phone,
            "company_code": company_code,
            "name": "사장님",
        }
        save_json('users.json', users)

        # companies.json 저장
        companies[company] = {"code": company_code, "phone": phone}
        save_json('companies.json', companies)

        # 회사별 컨테이너 시드
        _seed_company_containers(company)

        return render_template(
            'register_boss_success.html',
            boss_name="사장님",
            company=company,
            phone=phone,
            company_code=company_code
        )

    return render_template('register_boss.html')

@app.route('/_repair_companies_once')
def _repair_companies_once():
    users = load_json('users.json', {})
    companies = load_json('companies.json', {})
    changed = 0
    for u in users.values():
        if u.get('role') == 'boss':
            c = (u.get('company') or '').strip()
            if not c:
                continue
            code = (u.get('company_code') or '').strip()
            phone = (u.get('phone') or '').strip()
            if c not in companies or companies[c].get('code') != code or companies[c].get('phone') != phone:
                companies[c] = {"code": code, "phone": phone}
                changed += 1
    save_json('companies.json', companies)
    return f"repaired: {changed}"

@app.route('/_debug_paths')
def _debug_paths():
    # load_json/save_json이 사용하는 실제 경로 확인용
    base = Path(__file__).resolve().parent
    data = base / "data"
    return f"BASE_DIR={base}\nDATA_DIR={data}\nusers.json={data/'users.json'}\ncompanies.json={data/'companies.json'}", 200, {"Content-Type":"text/plain; charset=utf-8"}

@app.route('/register/worker', methods=['GET', 'POST'])
def register_worker():
    try:
        companies = load_json('companies.json', {})

        if request.method == 'POST':
            name = (request.form.get('name') or '').strip()
            phone = (request.form.get('phone') or '').strip()
            company = (request.form.get('company') or '').strip()
            input_code = (request.form.get('company_code') or '').strip()
            password = (request.form.get('password') or '').strip()

            if company not in companies:
                error = '존재하지 않는 회사명입니다.'
                return render_template('register_worker.html', companies=sorted(companies.keys()), error=error)

            if companies[company]['code'] != input_code:
                error = '회사 코드가 올바르지 않습니다.'
                return render_template('register_worker.html', companies=sorted(companies.keys()), error=error)

            users_db = load_json('users.json', {})
            workers_db = load_json('workers.json', {})
            workers_db.setdefault(company, [])

            # 1) 같은 회사+전화번호로 이미 가입되어 있으면(중복 전화) → 로그인 유도
            for u_name, u in users_db.items():
                if u.get('company') == company and (u.get('phone') or '') == phone:
                    return render_template(
                        'register_worker_conflict.html',
                        company=company,
                        name=name,
                        existing_name=u.get('name',''),
                        existing_phone=phone,
                        message='이미 동일한 전화번호로 가입된 계정이 있습니다.',
                        show_homonym=False  # 동명이인 버튼은 숨김
                    )

            # 2) 같은 회사에 동명이인(이름 완전 동일) 기사 존재?
            exists = None
            for w in workers_db[company]:
                if (w.get('name') or '').strip() == name:
                    exists = w
                    break

            if exists:
                # 기존 기사 username
                ex_username = exists.get('username') or f"{company}{name}"

                # users.json에 보장
                ensure_user_entry(users_db, workers_db, company, ex_username)
                # 기존 기사를 가입대기로 전환 + 가입자가 요청한 전화번호를 pending_update에 담음
                users_db[ex_username]['status'] = 'pending'
                users_db[ex_username]['pending_update'] = {'phone': phone}

                # workers.json 도 대기로
                for w in workers_db[company]:
                    if w.get('username') == ex_username:
                        w['status'] = 'pending'
                        break

                save_json('users.json', users_db)
                save_json('workers.json', workers_db)

                # 충돌 안내(동명이인 처리/로그인으로 돌아가기 버튼)
                return render_template(
                    'register_worker_conflict.html',
                    company=company,
                    name=name,
                    existing_name=exists.get('name',''),
                    existing_phone=exists.get('phone',''),
                    new_phone=phone,
                    password=password,
                    message=f'해당 회사에 {name}({exists.get("phone","")}) 기사가 존재합니다. 관리자/사장님에게 가입승인을 요청했습니다.',
                    show_homonym=True  # 동명이인 버튼 표시
                )

            # 3) 동명이인 없으면 일반 대기 등록
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

            # workers.json 반영(중복 전화 제거 후 추가)
            workers_db[company] = [w for w in workers_db[company] if w.get('phone') != phone]
            workers_db[company].append({
                'username': username,
                'name': name,
                'phone': phone,
                'role': 'worker',
                'status': 'pending'
            })
            save_json('workers.json', workers_db)

            return render_template('register_worker_pending.html', name=name, company=company)

        # GET
        return render_template('register_worker.html', companies=sorted(companies.keys()))

    except Exception as e:
        import traceback
        return f"<h2>서버 오류 발생:<br>{e}</h2><pre>{traceback.format_exc()}</pre>"

@app.route('/register/worker/resolve_homonym', methods=['POST'])
def resolve_homonym():
    # hidden 으로 넘어온 값들
    name = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    company = (request.form.get('company') or '').strip()
    password = (request.form.get('password') or '').strip()

    users_db = load_json('users.json', {})
    workers_db = load_json('workers.json', {})
    workers_db.setdefault(company, [])

    # 기존 동명이인 찾기 (status pending 으로 바꿔둔 그 사람)
    ex = None
    for w in workers_db[company]:
        if (w.get('name') or '').strip() == name and (w.get('status') or '') == 'pending':
            ex = w
            break
    # 못 찾으면 안전하게 이름만 같은 첫 항목
    if not ex:
        for w in workers_db[company]:
            if (w.get('name') or '').strip() == name:
                ex = w
                break
    if not ex:
        return back_with_error("기존 기사를 찾을 수 없습니다.")

    ex_username = ex.get('username') or f"{company}{name}"

    # 기존 기사 → (A) 로 표기 변경 + active 복구 + pending_update 제거
    ex['name'] = f"{name}(A)"
    ex['status'] = 'active'
    if ex_username in users_db:
        users_db[ex_username]['name'] = f"{name}(A)"
        users_db[ex_username]['status'] = 'active'
        users_db[ex_username].pop('pending_update', None)

    # 새 가입자 → (B) 이름으로 별도 사용자/워커 생성(대기)
    base_username = f"{company}{name}"
    username = base_username
    i = 1
    while username in users_db:
        username = f"{base_username}{i}"
        i += 1

    users_db[username] = {
        'password': password,
        'role': 'worker',
        'company': company,
        'name': f"{name}(B)",
        'phone': phone,
        'status': 'pending'
    }
    workers_db[company].append({
        'username': username,
        'name': f"{name}(B)",
        'phone': phone,
        'role': 'worker',
        'status': 'pending'
    })

    save_json('users.json', users_db)
    save_json('workers.json', workers_db)

    # 기존처럼 대기 화면
    return render_template('register_worker_pending.html', name=f"{name}(B)", company=company)

# ---------------------------
# 본인 정보 / 관리자 수정
# ---------------------------
@app.route('/edit_worker', methods=['GET', 'POST'])
def edit_worker():
    if 'username' not in session:
        return redirect('/login')

    worker_username = request.args.get('worker_username')
    users_db = load_json('users.json', {})
    current_user = users_db.get(session['username'], {})
    is_admin_user = current_user.get('role') in ('boss', 'manager')

    if worker_username and is_admin_user:
        username_to_edit = worker_username
        back_endpoint = 'add_worker'
        back_label = '← 기사 등록/관리로 돌아가기'
    else:
        username_to_edit = session['username']
        back_endpoint = 'dashboard_worker' if current_user.get('role') == 'worker' else 'dashboard'
        back_label = '🏠 메인화면으로 돌아가기'

    user_info = users_db.get(username_to_edit)
    if not user_info:
        return "사용자 정보를 찾을 수 없습니다.", 404

    if user_info.get('role') == 'boss' and not (username_to_edit == session['username']):
        return "보스 계정은 수정할 수 없습니다.", 403

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        password = (request.form.get('password') or '').strip()

        if name:     user_info['name'] = name
        if phone:    user_info['phone'] = phone
        if password: user_info['password'] = password

        users_db[username_to_edit] = user_info
        save_json('users.json', users_db)

        target_company = user_info.get('company', '')
        workers_db = load_json('workers.json', {})
        lst = workers_db.get(target_company, [])
        for w in lst:
            if w.get('username') == username_to_edit:
                if name:  w['name'] = name
                if phone: w['phone'] = phone
                break
        workers_db[target_company] = lst
        save_json('workers.json', workers_db)

        return redirect_with_from(back_endpoint)

    return render_template('edit_worker.html', user=user_info, back_endpoint=back_endpoint, back_label=back_label)

# ---------------------------
# 앱 실행/디버그용
# ---------------------------
@app.route('/_peek_users')
def _peek_users():
    users = load_json('users.json', {})
    bosses = {k:v for k,v in users.items() if (v.get('role') == 'boss')}
    return Response(json.dumps(bosses, ensure_ascii=False, indent=2), mimetype='application/json; charset=utf-8')

@app.route('/_peek_companies')
def _peek_companies():
    return Response(json.dumps(load_json('companies.json', {}), ensure_ascii=False, indent=2),
                    mimetype='application/json; charset=utf-8')

if __name__ == '__main__':
    # 기존 동작 유지
    app.run(debug=True, host='0.0.0.0', port=5000)
