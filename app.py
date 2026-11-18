import os
import re
import secrets
from datetime import datetime
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Transaction, BudgetCategory

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fintech-production-key-2024-secure')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 2592000

db.init_app(app)

reset_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
failed_login_attempts = {}

@app.before_request
def csrf_protect():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    if request.method == 'POST':
        token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if not token or token != session.get('csrf_token'):
            flash('Security verification token invalid or expired. Please submit the form again.', 'danger')
            return redirect(request.referrer or url_for('login'))

@app.context_processor
def inject_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return {'csrf_token': session['csrf_token']}

def is_login_rate_limited(key):
    now_ts = datetime.now().timestamp()
    attempts = [t for t in failed_login_attempts.get(key, []) if now_ts - t < 60]
    failed_login_attempts[key] = attempts
    return len(attempts) >= 5

def record_failed_login(key):
    now_ts = datetime.now().timestamp()
    failed_login_attempts.setdefault(key, []).append(now_ts)

def clear_failed_logins(key):
    failed_login_attempts.pop(key, None)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please sign in to access your financial reporting portal.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def validate_email_format(email):
    if not email or len(email) > 120:
        return False
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    if not re.match(pattern, email):
        return False
    parts = email.split('@')
    if len(parts) != 2:
        return False
    domain = parts[1]
    if '..' in domain or '.' not in domain:
        return False
    tld = domain.split('.')[-1]
    return len(tld) >= 2


def validate_indian_phone(phone):
    if not phone:
        return False, None
    clean = re.sub(r'[\s\-\(\)\+]', '', phone)
    if clean.startswith('91') and len(clean) == 12:
        clean = clean[2:]
    elif clean.startswith('0') and len(clean) == 11:
        clean = clean[1:]
    
    if re.match(r'^[6-9]\d{9}$', clean):
        return True, f"+91 {clean[:5]} {clean[5:]}"
    return False, None


def seed_user_financial_profile(user):
    today = datetime.now().strftime('%Y-%m-%d')
    
    if user.role == 'admin':
        budgets = [
            BudgetCategory(user_id=user.id, name='Cloud Infrastructure & SaaS', allocated=450000.0, spent=392000.0, period='Monthly'),
            BudgetCategory(user_id=user.id, name='Platform Engineering & Payroll', allocated=850000.0, spent=814000.0, period='Monthly'),
            BudgetCategory(user_id=user.id, name='Regulatory & Security Compliance', allocated=250000.0, spent=175000.0, period='Monthly'),
            BudgetCategory(user_id=user.id, name='Enterprise Merchant Acquisition', allocated=350000.0, spent=368000.0, period='Monthly'),
            BudgetCategory(user_id=user.id, name='Corporate Operations & Facilities', allocated=300000.0, spent=221000.0, period='Monthly'),
        ]
        txns = [
            Transaction(user_id=user.id, title='Enterprise Platform Licensing', category='Platform Revenue', amount=1850000.0, txn_type='income', date=today, status='Completed', notes='Q4 Corporate SaaS Invoicing'),
            Transaction(user_id=user.id, title='Multi-Store Merchant Processing Fees', category='Transaction Fees', amount=784500.0, txn_type='income', date=today, status='Completed', notes='Aggregated Interchange Volume'),
            Transaction(user_id=user.id, title='AWS & Cloud Hosting Settlement', category='Cloud Infrastructure & SaaS', amount=245000.0, txn_type='expense', date=today, status='Completed', notes='Global CDN & Database Clusters'),
            Transaction(user_id=user.id, title='Quarterly Cyber-Security Audit', category='Regulatory & Security Compliance', amount=175000.0, txn_type='expense', date=today, status='Completed', notes='SOC2 / RBI Compliance Attestation'),
            Transaction(user_id=user.id, title='Core Engineering Payroll', category='Platform Engineering & Payroll', amount=650000.0, txn_type='expense', date=today, status='Completed', notes='Bi-weekly automated payroll disbursement'),
        ]
    elif user.role == 'shop_owner':
        budgets = [
            BudgetCategory(user_id=user.id, name='Inventory Restock & Wholesale', allocated=380000.0, spent=345000.0, period='Monthly'),
            BudgetCategory(user_id=user.id, name='Storefront Lease & Utilities', allocated=120000.0, spent=118000.0, period='Monthly'),
            BudgetCategory(user_id=user.id, name='Retail Staff Wages & Overtime', allocated=160000.0, spent=149000.0, period='Monthly'),
            BudgetCategory(user_id=user.id, name='POS Terminals & Merchant Fees', allocated=65000.0, spent=68500.0, period='Monthly'),
            BudgetCategory(user_id=user.id, name='Local Promotional Campaigns', allocated=50000.0, spent=39500.0, period='Monthly'),
        ]
        txns = [
            Transaction(user_id=user.id, title='Weekly Register & POS Settlement', category='Retail Sales', amount=468000.0, txn_type='income', date=today, status='Completed', notes='Storefront UPI, card & cash settlements'),
            Transaction(user_id=user.id, title='Online Delivery Channel Payout', category='E-Commerce', amount=184000.0, txn_type='income', date=today, status='Completed', notes='Third-party marketplace settlement'),
            Transaction(user_id=user.id, title='Wholesale FMCG Goods Delivery', category='Inventory Restock & Wholesale', amount=215000.0, txn_type='expense', date=today, status='Completed', notes='Bulk supplier invoice #INV-9921'),
            Transaction(user_id=user.id, title='Commercial Electricity & Cold Storage', category='Storefront Lease & Utilities', amount=34000.0, txn_type='expense', date=today, status='Completed', notes='Monthly utility bill'),
            Transaction(user_id=user.id, title='Store Associate Wages', category='Retail Staff Wages & Overtime', amount=74500.0, txn_type='expense', date=today, status='Completed', notes='Floor associates payroll cycle'),
        ]
    else:
        base_income = (user.total_income / 12.0) if (user.total_income and user.total_income > 0) else 85000.0
        budgets = [
            BudgetCategory(user_id=user.id, name='Housing & Rent / EMI', allocated=round(base_income * 0.32, 0), spent=round(base_income * 0.32, 0), period='Monthly'),
            BudgetCategory(user_id=user.id, name='Groceries & Household Goods', allocated=round(base_income * 0.18, 0), spent=round(base_income * 0.15, 0), period='Monthly'),
            BudgetCategory(user_id=user.id, name='Utilities, Mobile & Internet', allocated=round(base_income * 0.08, 0), spent=round(base_income * 0.07, 0), period='Monthly'),
            BudgetCategory(user_id=user.id, name='Transportation & Auto Fuel', allocated=round(base_income * 0.10, 0), spent=round(base_income * 0.11, 0), period='Monthly'),
            BudgetCategory(user_id=user.id, name='Savings, SIPs & Mutual Funds', allocated=round(base_income * 0.25, 0), spent=round(base_income * 0.22, 0), period='Monthly'),
        ]
        txns = [
            Transaction(user_id=user.id, title='Monthly Primary Salary', category='Salary / Earnings', amount=round(base_income, 0), txn_type='income', date=today, status='Completed', notes='Direct corporate payroll NEFT'),
            Transaction(user_id=user.id, title='Advisory Consulting Retainer', category='Secondary Income', amount=round(base_income * 0.25, 0), txn_type='income', date=today, status='Completed', notes='Freelance / advisory fees'),
            Transaction(user_id=user.id, title='Apartment Monthly Lease Payment', category='Housing & Rent / EMI', amount=round(base_income * 0.32, 0), txn_type='expense', date=today, status='Completed', notes='Direct debit bank wire'),
            Transaction(user_id=user.id, title='Organic Supermarket Supply', category='Groceries & Household Goods', amount=round(base_income * 0.09, 0), txn_type='expense', date=today, status='Completed', notes='Weekly pantry supplies'),
            Transaction(user_id=user.id, title='Index Fund / Mutual Fund SIP', category='Savings, SIPs & Mutual Funds', amount=round(base_income * 0.20, 0), txn_type='expense', date=today, status='Completed', notes='Automated monthly investment'),
        ]

    for b in budgets:
        db.session.add(b)
    for t in txns:
        db.session.add(t)
    db.session.commit()


def init_seed_demo_accounts():
    demo_specs = [
        {
            'fullname': 'Sarah Vance',
            'email': 'admin@finance.com',
            'password': 'admin123',
            'role': 'admin',
            'business': 'FinTrack Enterprise Holdings',
            'age': 36,
            'phone': '+91 98201 44521',
            'address': 'Level 14, Cyber City, Phase II, Gurugram, Haryana',
            'total_income': 3500000.0
        },
        {
            'fullname': 'Marcus Hayes',
            'email': 'shop@metrostore.com',
            'password': 'shop123',
            'role': 'shop_owner',
            'business': 'Metro Mart Superstore & Retail',
            'age': 42,
            'phone': '+91 98450 12890',
            'address': 'Shop #12-14, Commercial Market, Indiranagar, Bengaluru, Karnataka',
            'total_income': 1850000.0
        },
        {
            'fullname': 'Elena Rostova',
            'email': 'user@personal.com',
            'password': 'user123',
            'role': 'user',
            'business': None,
            'age': 29,
            'phone': '+91 98112 37654',
            'address': 'Apt 402, Highline Residency, Bandra West, Mumbai, Maharashtra',
            'total_income': 1200000.0
        }
    ]

    for spec in demo_specs:
        existing = User.query.filter_by(email=spec['email']).first()
        if not existing:
            user = User(
                fullname=spec['fullname'],
                email=spec['email'],
                password=generate_password_hash(spec['password']),
                role=spec['role'],
                business_name=spec['business'],
                age=spec['age'],
                phone=spec['phone'],
                address=spec['address'],
                total_income=spec['total_income']
            )
            db.session.add(user)
            db.session.commit()
            seed_user_financial_profile(user)



@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))


@app.route('/dashboard')
@login_required
def dashboard():
    if not current_user.budgets and not current_user.transactions:
        seed_user_financial_profile(current_user)

    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.id.desc()).all()
    budgets = BudgetCategory.query.filter_by(user_id=current_user.id).all()

    total_income = sum(t.amount for t in transactions if t.txn_type == 'income')
    total_expense = sum(t.amount for t in transactions if t.txn_type == 'expense')
    net_profit = total_income - total_expense
    operating_margin = round((net_profit / total_income * 100), 1) if total_income > 0 else 0.0

    total_allocated = sum(b.allocated for b in budgets)
    total_budget_spent = sum(b.spent for b in budgets)
    budget_utilization = round((total_budget_spent / total_allocated * 100), 1) if total_allocated > 0 else 0.0
    budget_variance = round(total_allocated - total_budget_spent, 2)

    months_data = [
        {'name': 'Jun', 'income': round(total_income * 0.82, 0), 'expense': round(total_expense * 0.88, 0)},
        {'name': 'Jul', 'income': round(total_income * 0.89, 0), 'expense': round(total_expense * 0.91, 0)},
        {'name': 'Aug', 'income': round(total_income * 0.94, 0), 'expense': round(total_expense * 0.89, 0)},
        {'name': 'Sep', 'income': round(total_income * 0.91, 0), 'expense': round(total_expense * 0.95, 0)},
        {'name': 'Oct', 'income': round(total_income * 0.98, 0), 'expense': round(total_expense * 0.94, 0)},
        {'name': 'Nov', 'income': total_income, 'expense': total_expense},
    ]

    max_metric = max([m['income'] for m in months_data] + [m['expense'] for m in months_data] + [1000])

    admin_system_metrics = None
    if current_user.is_admin:
        all_users_count = User.query.count()
        merchants_count = User.query.filter_by(role='shop_owner').count()
        analysts_count = User.query.filter_by(role='user').count()
        admin_system_metrics = {
            'total_users': all_users_count,
            'merchants': merchants_count,
            'analysts': analysts_count,
            'system_health': '99.98% Operational',
            'audit_status': 'Compliant (SOC2 / RBI Security)'
        }

    return render_template(
        'dashboard.html',
        transactions=transactions,
        budgets=budgets,
        total_income=total_income,
        total_expense=total_expense,
        net_profit=net_profit,
        operating_margin=operating_margin,
        total_allocated=total_allocated,
        total_budget_spent=total_budget_spent,
        budget_utilization=budget_utilization,
        budget_variance=budget_variance,
        months_data=months_data,
        max_metric=max_metric,
        admin_system_metrics=admin_system_metrics
    )


@app.route('/add-transaction', methods=['POST'])
@login_required
def add_transaction():
    title = request.form.get('title', '').strip()
    category = request.form.get('category', '').strip()
    amount_str = request.form.get('amount', '0').strip()
    txn_type = request.form.get('txn_type', 'expense').strip().lower()
    date_val = request.form.get('date', datetime.now().strftime('%Y-%m-%d')).strip()
    notes = request.form.get('notes', '').strip()

    try:
        amount = float(amount_str)
        if amount <= 0:
            flash('Transaction amount must be greater than zero.', 'danger')
            return redirect(url_for('dashboard'))
    except ValueError:
        flash('Please enter a valid numeric transaction amount.', 'danger')
        return redirect(url_for('dashboard'))

    if not title or not category:
        flash('Transaction title and category are required.', 'danger')
        return redirect(url_for('dashboard'))

    new_txn = Transaction(
        user_id=current_user.id,
        title=title,
        category=category,
        amount=amount,
        txn_type=txn_type,
        date=date_val,
        status='Completed',
        notes=notes
    )
    db.session.add(new_txn)

    if txn_type == 'expense':
        matched_budget = BudgetCategory.query.filter_by(user_id=current_user.id, name=category).first()
        if matched_budget:
            matched_budget.spent += amount

    db.session.commit()
    flash(f'Transaction "{title}" (₹{amount:,.2f}) recorded successfully.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/add-budget', methods=['POST'])
@login_required
def add_budget():
    name = request.form.get('name', '').strip()
    allocated_str = request.form.get('allocated', '0').strip()
    spent_str = request.form.get('spent', '0').strip()

    try:
        allocated = float(allocated_str)
        spent = float(spent_str) if spent_str else 0.0
        if allocated <= 0:
            flash('Budget allocation must be positive.', 'danger')
            return redirect(url_for('dashboard'))
    except ValueError:
        flash('Invalid numeric budget amount.', 'danger')
        return redirect(url_for('dashboard'))

    if not name:
        flash('Budget category name is required.', 'danger')
        return redirect(url_for('dashboard'))

    existing = BudgetCategory.query.filter_by(user_id=current_user.id, name=name).first()
    if existing:
        existing.allocated = allocated
        if spent > 0:
            existing.spent = spent
        flash(f'Budget allocation for "{name}" updated to ₹{allocated:,.2f}.', 'success')
    else:
        new_b = BudgetCategory(user_id=current_user.id, name=name, allocated=allocated, spent=spent)
        db.session.add(new_b)
        flash(f'New budget category "{name}" created with cap ₹{allocated:,.2f}.', 'success')

    db.session.commit()
    return redirect(url_for('dashboard'))


@app.route('/delete-transaction/<int:txn_id>', methods=['POST'])
@login_required
def delete_transaction(txn_id):
    txn = Transaction.query.filter_by(id=txn_id, user_id=current_user.id).first()
    if txn:
        if txn.txn_type == 'expense':
            matched_budget = BudgetCategory.query.filter_by(user_id=current_user.id, name=txn.category).first()
            if matched_budget:
                matched_budget.spent = max(0.0, matched_budget.spent - txn.amount)
        db.session.delete(txn)
        db.session.commit()
        flash('Transaction removed from financial ledger.', 'info')
    return redirect(url_for('dashboard'))



@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        fullname         = request.form.get('fullname', '').strip()
        email            = request.form.get('email', '').strip().lower()
        role             = request.form.get('role', 'user').strip()
        business_name    = request.form.get('business_name', '').strip()
        
        age_str          = request.form.get('age', '').strip()
        phone            = request.form.get('phone', '').strip()
        address          = request.form.get('address', '').strip()
        income_str       = request.form.get('total_income', '0').strip()

        password         = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        error = None
        if not fullname:
            error = 'Full name is required.'
        elif not email:
            error = 'Email address is required.'
        elif not validate_email_format(email):
            error = 'Please enter a valid email address format (e.g. name@company.com).'
        elif not phone:
            error = 'Phone number is required.'
        else:
            is_valid_phone, formatted_phone = validate_indian_phone(phone)
            if not is_valid_phone:
                error = 'Please enter a valid 10-digit Indian phone number starting with 6, 7, 8, or 9 (e.g. 9876543210).'
            else:
                phone = formatted_phone

        if not error:
            if not address:
                error = 'Residential / Business address is required.'
            elif role not in ['user', 'shop_owner', 'admin']:
                error = 'Please select a valid account role.'
            elif role == 'shop_owner' and not business_name:
                error = 'Shop or business name is required for Shop Owner accounts.'
            elif len(password) < 8:
                error = 'Password must be at least 8 characters long.'
            elif password != confirm_password:
                error = 'Passwords do not match.'
            elif User.query.filter_by(email=email).first():
                error = 'An account with this email is already registered.'

        age = None
        if not error and age_str:
            try:
                age = int(age_str)
                if age < 18 or age > 110:
                    error = 'Age must be between 18 and 110 years.'
            except ValueError:
                error = 'Please enter a valid numeric age.'

        total_income = 0.0
        if not error and income_str:
            try:
                total_income = float(income_str)
                if total_income < 0:
                    error = 'Total income cannot be negative.'
            except ValueError:
                error = 'Please enter a valid numeric total income amount.'

        if error:
            flash(error, 'danger')
            return render_template(
                'register.html',
                fullname=fullname,
                email=email,
                role=role,
                business_name=business_name,
                age=age_str,
                phone=phone,
                address=address,
                total_income=income_str
            )

        hashed_pw = generate_password_hash(password)
        new_user = User(
            fullname=fullname,
            email=email,
            password=hashed_pw,
            role=role,
            business_name=business_name if business_name else None,
            age=age,
            phone=phone,
            address=address,
            total_income=total_income
        )
        db.session.add(new_user)
        db.session.commit()

        seed_user_financial_profile(new_user)

        flash('Your account has been registered successfully! You may now sign in.', 'success')
        return redirect(url_for('login'))

    return render_template(
        'register.html',
        fullname='',
        email='',
        role='user',
        business_name='',
        age='',
        phone='',
        address='',
        total_income=''
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email       = request.form.get('email', '').strip().lower()
        password    = request.form.get('password', '')
        role        = request.form.get('role', 'user').strip()
        remember_me = 'remember_me' in request.form

        client_key = request.remote_addr or email
        if is_login_rate_limited(client_key):
            flash('Too many failed sign-in attempts. For your security, please wait 60 seconds before trying again.', 'danger')
            return render_template('login.html', email=email, role=role)

        if not email or not validate_email_format(email):
            flash('Please enter a valid email address format (e.g. name@company.com).', 'danger')
            return render_template('login.html', email=email, role=role)

        if not password:
            flash('Password is required.', 'danger')
            return render_template('login.html', email=email, role=role)

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password, password):
            record_failed_login(client_key)
            flash('Invalid email or password combination. Please try again.', 'danger')
            return render_template('login.html', email=email, role=role)

        if user.role != role:
            record_failed_login(client_key)
            role_labels = {'admin': 'Administrator', 'shop_owner': 'Shop Owner', 'user': 'Standard User'}
            selected_label = role_labels.get(role, role)
            flash(f'Account role mismatch: Your account is registered as "{user.role_title}", not "{selected_label}". Please select the correct login type.', 'danger')
            return render_template('login.html', email=email, role=role)

        clear_failed_logins(client_key)
        login_user(user, remember=remember_me)
        next_page = request.args.get('next')
        return redirect(next_page or url_for('dashboard'))

    return render_template('login.html', email='', role='user')


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email or not validate_email_format(email):
            flash('Please enter a valid email address format.', 'danger')
            return render_template('forgot_password.html', email=email, reset_url=None)

        user = User.query.filter_by(email=email).first()
        if user:
            token = reset_serializer.dumps(user.email, salt='fintech-password-reset')
            reset_url = url_for('reset_password', token=token, _external=True)
            flash(f'Password reset token generated. Verification link: {reset_url}', 'info')
            return render_template('forgot_password.html', email=email, reset_url=reset_url)
        else:
            flash('If an account is associated with this email, a reset verification token has been issued.', 'info')
            return render_template('forgot_password.html', email=email, reset_url=None)

    return render_template('forgot_password.html', email='', reset_url=None)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    try:
        email = reset_serializer.loads(token, salt='fintech-password-reset', max_age=3600)
    except (SignatureExpired, BadTimeSignature):
        flash('The password reset link has expired or is invalid. Please request a new one.', 'danger')
        return redirect(url_for('forgot_password'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Invalid password reset request.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if len(password) < 8:
            flash('New password must be at least 8 characters long.', 'danger')
            return render_template('reset_password.html', token=token, email=email)

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token, email=email)

        user.password = generate_password_hash(password)
        db.session.commit()
        flash('Your password has been reset successfully. Please sign in with your new credentials.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token, email=email)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been securely logged out of the finance platform.', 'success')
    return redirect(url_for('login'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_seed_demo_accounts()
        print(" * Finance Analytics Database Initialized (INR ₹ Multi-Role Profiles).")
    app.run(debug=True, port=5000)
