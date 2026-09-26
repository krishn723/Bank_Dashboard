import json, os, random, secrets, threading
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
DATA_FILE = BASE / 'data' / 'database.json'
load_dotenv(BASE / '.env')

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'smartbank-development-secret-change-me')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
LOCK = threading.RLock()

DEFAULT_DB = {"users": [], "transactions": [], "cards": [], "upi": [], "otps": []}

def read_db():
    with LOCK:
        DATA_FILE.parent.mkdir(exist_ok=True)
        if not DATA_FILE.exists():
            write_db(DEFAULT_DB)
        try:
            with DATA_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
            for key in DEFAULT_DB:
                data.setdefault(key, [])
            return data
        except (json.JSONDecodeError, OSError):
            return json.loads(json.dumps(DEFAULT_DB))

def write_db(data):
    with LOCK:
        tmp = DATA_FILE.with_suffix('.tmp')
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(DATA_FILE)

def now(): return datetime.now().isoformat(timespec='seconds')
def money(v): return round(float(v), 2)

def next_account(db):
    nums=[]
    for u in db['users']:
        a=str(u.get('account_no',''))
        if a.startswith('SB') and a[2:].isdigit(): nums.append(int(a[2:]))
    return f"SB{(max(nums, default=10000000)+1):08d}"

def current_user():
    aid=session.get('account_no')
    if not aid: return None
    db=read_db()
    return next((u for u in db['users'] if u.get('account_no')==aid), None)

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash('Please login to continue.', 'error')
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapper

def user_txns(account):
    return [t for t in read_db()['transactions'] if t.get('account_no')==account]

def balance_for(account):
    return money(sum((t['amount'] if t['type']=='credit' else -t['amount']) for t in user_txns(account)))

def add_txn(db, account, typ, amount, category, description, channel='Internal'):
    db['transactions'].append({
        'id': secrets.token_hex(6).upper(), 'account_no': account, 'type': typ,
        'amount': money(amount), 'category': category, 'description': description,
        'channel': channel, 'created_at': now()
    })

def valid_phone(p): return p.isdigit() and len(p)==10

def send_otp(db, account, purpose):
    user=next((u for u in db['users'] if u['account_no']==account), None)
    if not user: return None
    code=f'{random.randint(0,999999):06d}'
    db['otps']=[x for x in db['otps'] if not (x.get('account_no')==account and x.get('purpose')==purpose)]
    db['otps'].append({'account_no':account,'purpose':purpose,'code':code,'expires_at':(datetime.now()+timedelta(minutes=5)).isoformat()})
    write_db(db)
    return code

@app.context_processor
def inject():
    u=current_user()
    return {'logged_user':u, 'app_name':os.getenv('APP_NAME','SmartBank')}

@app.route('/')
def home(): return render_template('home.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); phone=request.form.get('phone','').strip(); pin=request.form.get('pin','').strip(); confirm=request.form.get('confirm_pin','').strip()
        if len(name)<2: flash('Please enter a valid full name.', 'error')
        elif not valid_phone(phone): flash('Mobile number must contain exactly 10 digits.', 'error')
        elif '@' not in email: flash('Please enter a valid email address.', 'error')
        elif not pin.isdigit() or len(pin)!=4: flash('PIN must be exactly 4 digits.', 'error')
        elif pin!=confirm: flash('PIN confirmation does not match.', 'error')
        else:
            db=read_db()
            if any(u.get('email')==email for u in db['users']): flash('An account with this email already exists.', 'error')
            elif any(u.get('phone')==phone for u in db['users']): flash('An account with this mobile number already exists.', 'error')
            else:
                account=next_account(db)
                db['users'].append({'account_no':account,'name':name,'email':email,'phone':phone,'pin_hash':generate_password_hash(pin),'created_at':now(),'status':'Active'})
                db['cards'].append({'account_no':account,'card_no':f"5399{random.randint(10**11,10**12-1)}",'status':'Active','type':'Debit Card','created_at':now()})
                add_txn(db, account, 'credit', 0, 'Opening', 'Account opened', 'Account')
                write_db(db)
                session['new_account']=account
                return redirect(url_for('registration_success'))
    return render_template('register.html')

@app.route('/registration-success')
def registration_success():
    account=session.pop('new_account',None)
    if not account: return redirect(url_for('login'))
    return render_template('registration_success.html', account=account)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        account=request.form.get('account_no','').strip().upper(); pin=request.form.get('pin','').strip(); db=read_db(); u=next((x for x in db['users'] if x.get('account_no')==account),None)
        if not u or not check_password_hash(u.get('pin_hash',''), pin): flash('Invalid account number or PIN.', 'error')
        elif u.get('status')!='Active': flash('This account is currently inactive.', 'error')
        else:
            session.clear(); session['account_no']=account; return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); flash('You have been logged out securely.', 'success'); return redirect(url_for('login'))

@app.route('/forgot-pin', methods=['GET','POST'])
def forgot_pin():
    if request.method=='POST':
        account=request.form.get('account_no','').strip().upper(); phone=request.form.get('phone','').strip(); db=read_db(); u=next((x for x in db['users'] if x.get('account_no')==account and x.get('phone')==phone),None)
        if not u: flash('Account number and mobile number do not match.', 'error')
        else:
            code=send_otp(db,account,'reset_pin'); session['reset_account']=account
            flash(f'Development OTP: {code}', 'success'); return redirect(url_for('verify_otp'))
    return render_template('forgot_pin.html')

@app.route('/verify-otp', methods=['GET','POST'])
def verify_otp():
    account=session.get('reset_account')
    if not account: return redirect(url_for('forgot_pin'))
    if request.method=='POST':
        code=request.form.get('otp','').strip(); pin=request.form.get('pin','').strip(); confirm=request.form.get('confirm_pin','').strip(); db=read_db(); item=next((x for x in db['otps'] if x.get('account_no')==account and x.get('purpose')=='reset_pin'),None)
        if not item or datetime.fromisoformat(item['expires_at']) < datetime.now(): flash('OTP expired. Please request a new OTP.', 'error')
        elif item['code']!=code: flash('Incorrect OTP.', 'error')
        elif not pin.isdigit() or len(pin)!=4 or pin!=confirm: flash('New PIN must be 4 digits and both fields must match.', 'error')
        else:
            u=next(x for x in db['users'] if x['account_no']==account); u['pin_hash']=generate_password_hash(pin); db['otps']=[x for x in db['otps'] if x is not item]; write_db(db); session.pop('reset_account',None); flash('PIN changed successfully. You can login now.', 'success'); return redirect(url_for('login'))
    return render_template('verify_otp.html', account=account)

@app.route('/dashboard')
@login_required
def dashboard():
    u=current_user(); tx=user_txns(u['account_no']); recent=sorted(tx,key=lambda x:x['created_at'],reverse=True)[:6]
    credits=money(sum(x['amount'] for x in tx if x['type']=='credit')); debits=money(sum(x['amount'] for x in tx if x['type']=='debit'))
    return render_template('dashboard.html', balance=balance_for(u['account_no']), recent=recent, credits=credits, debits=debits, count=len(tx))

@app.route('/transactions')
@login_required
def transactions():
    tx=sorted(user_txns(current_user()['account_no']), key=lambda x:x['created_at'], reverse=True)
    return render_template('transactions.html', transactions=tx)

@app.route('/statement')
@login_required
def statement():
    tx=sorted(user_txns(current_user()['account_no']), key=lambda x:x['created_at'], reverse=True)
    return render_template('statement.html', transactions=tx, balance=balance_for(current_user()['account_no']))

@app.route('/transfer', methods=['GET','POST'])
@login_required
def transfer():
    u=current_user()
    if request.method=='POST':
        recipient=request.form.get('recipient','').strip().upper(); amount=request.form.get('amount','').strip(); note=request.form.get('note','').strip() or 'Fund transfer'; pin=request.form.get('pin','').strip()
        try: amount=money(amount)
        except: amount=0
        if amount<=0: flash('Enter a valid amount.', 'error')
        elif amount>balance_for(u['account_no']): flash('Insufficient available balance.', 'error')
        elif not check_password_hash(u['pin_hash'],pin): flash('Incorrect transaction PIN.', 'error')
        elif not recipient.startswith('SB') or recipient==u['account_no']: flash('Enter a valid recipient account number.', 'error')
        else:
            db=read_db(); target=next((x for x in db['users'] if x.get('account_no')==recipient),None)
            if not target: flash('Recipient account was not found.', 'error')
            else:
                add_txn(db,u['account_no'],'debit',amount,'Transfer',f'Transfer to {recipient}: {note}','Bank Transfer'); add_txn(db,recipient,'credit',amount,'Transfer',f'Transfer from {u["account_no"]}: {note}','Bank Transfer'); write_db(db); flash(f'₹{amount:,.2f} transferred successfully.', 'success'); return redirect(url_for('transactions'))
    return render_template('transfer.html', balance=balance_for(u['account_no']))

@app.route('/upi', methods=['GET','POST'])
@login_required
def upi():
    u=current_user(); db=read_db(); my=next((x for x in db['upi'] if x.get('account_no')==u['account_no']),None)
    if request.method=='POST':
        handle=request.form.get('upi_id','').strip().lower();
        if not handle.endswith('@smartbank'): flash('UPI ID must end with @smartbank.', 'error')
        elif any(x.get('upi_id')==handle and x.get('account_no')!=u['account_no'] for x in db['upi']): flash('That UPI ID is already in use.', 'error')
        else:
            if my: my['upi_id']=handle
            else: db['upi'].append({'account_no':u['account_no'],'upi_id':handle,'created_at':now()})
            write_db(db); flash('UPI ID saved.', 'success'); return redirect(url_for('upi'))
    return render_template('upi.html', upi=my)

@app.route('/cards')
@login_required
def cards():
    u=current_user(); card=next((x for x in read_db()['cards'] if x.get('account_no')==u['account_no']),None)
    return render_template('cards.html', card=card)

@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    u=current_user(); db=read_db()
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower()
        if len(name)<2 or '@' not in email: flash('Please enter valid profile details.', 'error')
        elif any(x.get('email')==email and x.get('account_no')!=u['account_no'] for x in db['users']): flash('Email is already used by another account.', 'error')
        else: u['name']=name; u['email']=email; write_db(db); flash('Profile updated successfully.', 'success'); return redirect(url_for('profile'))
    return render_template('profile.html', user=u)

@app.route('/analytics')
@login_required
def analytics():
    tx=user_txns(current_user()['account_no']); cats={}
    for t in tx:
        if t['type']=='debit': cats[t['category']]=money(cats.get(t['category'],0)+t['amount'])
    monthly={}
    for t in tx:
        month=t['created_at'][:7]; monthly.setdefault(month,{'credit':0,'debit':0}); monthly[month][t['type']]=money(monthly[month][t['type']]+t['amount'])
    return render_template('analytics.html', categories=cats, monthly=monthly, balance=balance_for(current_user()['account_no']))

@app.route('/api/analytics')
@login_required
def api_analytics():
    tx=user_txns(current_user()['account_no']); cats={}; months={}
    for t in tx:
        if t['type']=='debit': cats[t['category']]=money(cats.get(t['category'],0)+t['amount'])
        m=t['created_at'][:7]; months.setdefault(m,{'credit':0,'debit':0}); months[m][t['type']]=money(months[m][t['type']]+t['amount'])
    return jsonify({'balance':balance_for(current_user()['account_no']),'categories':cats,'monthly':months})

@app.errorhandler(404)
def not_found(e): return render_template('error.html', code=404, message='The page you requested was not found.'),404
@app.errorhandler(500)
def server_error(e): return render_template('error.html', code=500, message='Something went wrong while processing your request.'),500

if __name__ == '__main__':
    print('SmartBank running at http://127.0.0.1:5000')
    app.run(debug=True, host='127.0.0.1', port=5000)
