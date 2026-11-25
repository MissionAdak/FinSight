import os
import re
import csv
import io
import secrets
from datetime import datetime, timezone
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from flask import Flask, render_template, redirect, url_for, request, flash, session, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Transaction, BudgetCategory, Account, Investment, PortfolioHistory, Goal, GoalTransaction

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'finsight-secure-production-key-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 2592000

db.init_app(app)

reset_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
failed_login_attempts = {}

CURRENCIES = {
    'USD': {'code': 'USD', 'symbol': '$', 'name': 'US Dollar'},
    'EUR': {'code': 'EUR', 'symbol': '€', 'name': 'Euro'},
    'GBP': {'code': 'GBP', 'symbol': '£', 'name': 'British Pound'},
    'INR': {'code': 'INR', 'symbol': '₹', 'name': 'Indian Rupee'},
    'JPY': {'code': 'JPY', 'symbol': '¥', 'name': 'Japanese Yen'},
    'AUD': {'code': 'AUD', 'symbol': 'A$', 'name': 'Australian Dollar'},
    'CAD': {'code': 'CAD', 'symbol': 'C$', 'name': 'Canadian Dollar'},
    'CHF': {'code': 'CHF', 'symbol': 'CHF', 'name': 'Swiss Franc'},
    'CNY': {'code': 'CNY', 'symbol': '¥', 'name': 'Chinese Yuan'},
    'HKD': {'code': 'HKD', 'symbol': 'HK$', 'name': 'Hong Kong Dollar'},
    'NZD': {'code': 'NZD', 'symbol': 'NZ$', 'name': 'New Zealand Dollar'},
    'SGD': {'code': 'SGD', 'symbol': 'S$', 'name': 'Singapore Dollar'},
    'SEK': {'code': 'SEK', 'symbol': 'kr', 'name': 'Swedish Krona'},
    'KRW': {'code': 'KRW', 'symbol': '₩', 'name': 'South Korean Won'},
    'NOK': {'code': 'NOK', 'symbol': 'kr', 'name': 'Norwegian Krone'},
    'MXN': {'code': 'MXN', 'symbol': 'MX$', 'name': 'Mexican Peso'},
    'BRL': {'code': 'BRL', 'symbol': 'R$', 'name': 'Brazilian Real'},
    'ZAR': {'code': 'ZAR', 'symbol': 'R', 'name': 'South African Rand'},
    'AED': {'code': 'AED', 'symbol': 'د.إ', 'name': 'UAE Dirham'},
    'SAR': {'code': 'SAR', 'symbol': '﷼', 'name': 'Saudi Riyal'}
}

COUNTRIES = [
    'India', 'United States', 'United Kingdom', 'Germany', 'France',
    'Canada', 'Australia', 'Japan', 'China', 'United Arab Emirates',
    'Saudi Arabia', 'Singapore', 'Switzerland', 'New Zealand',
    'Hong Kong', 'Sweden', 'South Korea', 'Norway', 'Mexico',
    'Brazil', 'South Africa', 'Other'
]

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please sign in to access your FinSight workspace.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def get_user_currency_info():
    code = 'INR'
    if current_user.is_authenticated and current_user.currency:
        code = current_user.currency
    curr = CURRENCIES.get(code, {'code': code, 'symbol': code, 'name': code})
    return curr['code'], curr['symbol']


def format_money(amount):
    if amount is None:
        amount = 0.0
    _, symbol = get_user_currency_info()
    is_neg = amount < 0
    val_str = f"{abs(amount):,.2f}"
    return f"-{symbol}{val_str}" if is_neg else f"{symbol}{val_str}"


@app.before_request
def csrf_protect():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    if request.method == 'POST':
        token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if not token or token != session.get('csrf_token'):
            flash('Security verification token invalid or expired. Please submit the form again.', 'danger')
            return redirect(request.referrer or url_for('dashboard'))


@app.context_processor
def inject_global_context():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    
    code, symbol = get_user_currency_info()
    theme = 'light'
    if current_user.is_authenticated and current_user.theme:
        theme = current_user.theme

    budget_alerts = []
    investment_alerts = []
    goal_alerts = []
    sidebar_summary = {
        'income': 0.0,
        'expense': 0.0,
        'savings': 0.0,
        'budget_pct': 0.0,
        'allocated': 0.0,
        'spent': 0.0
    }

    if current_user.is_authenticated:
        for b in current_user.budgets:
            pct = (b.spent / b.allocated * 100) if b.allocated > 0 else 0
            thresh = b.alert_threshold or 80
            if pct >= thresh:
                budget_alerts.append({
                    'id': b.id,
                    'category': b.name,
                    'spent': b.spent,
                    'allocated': b.allocated,
                    'pct': round(pct, 1),
                    'is_over': pct > 100,
                    'thresh': thresh
                })

        for inv in current_user.investments:
            if inv.return_pct >= 25.0:
                investment_alerts.append({
                    'title': f'{inv.asset_name} Outperforming',
                    'desc': f'Unrealized gain of +{inv.return_pct}% on holding.',
                    'is_gain': True
                })
            elif inv.return_pct <= -10.0:
                investment_alerts.append({
                    'title': f'{inv.asset_name} Drawdown Alert',
                    'desc': f'Holding is down {inv.return_pct}% against purchase price.',
                    'is_gain': False
                })
            elif abs(inv.day_change_pct) >= 3.0:
                investment_alerts.append({
                    'title': f'{inv.asset_name} Volatility',
                    'desc': f'Intraday movement of {inv.day_change_pct:+.1f}% recorded today.',
                    'is_gain': inv.day_change_pct > 0
                })

        for g in current_user.goals:
            c_status = g.computed_status
            if c_status == 'At Risk':
                goal_alerts.append({
                    'title': f'Goal at Risk: {g.goal_name}',
                    'desc': f'Behind schedule. Target date {g.target_date}. Recommended: {format_money(g.recommended_monthly_saving)}/mo.',
                    'is_risk': True
                })
            elif g.progress_pct >= 100.0:
                goal_alerts.append({
                    'title': f'Target Achieved: {g.goal_name}',
                    'desc': f'Target corpus of {format_money(g.target_amount)} fully funded!',
                    'is_risk': False
                })
            elif g.progress_pct >= 75.0 and g.progress_pct < 80.0:
                goal_alerts.append({
                    'title': f'Milestone Hit: {g.goal_name}',
                    'desc': f'{g.progress_pct}% of goal corpus accumulated.',
                    'is_risk': False
                })

        now_prefix = datetime.now().strftime('%Y-%m')
        m_in = sum(t.amount for t in current_user.transactions if t.txn_type == 'income' and t.date.startswith(now_prefix))
        m_out = sum(t.amount for t in current_user.transactions if t.txn_type == 'expense' and t.date.startswith(now_prefix))
        m_sav = m_in - m_out
        tot_alloc = sum(b.allocated for b in current_user.budgets if b.period == 'Monthly')
        tot_sp = sum(b.spent for b in current_user.budgets if b.period == 'Monthly')
        b_pct = round((tot_sp / tot_alloc * 100), 1) if tot_alloc > 0 else 0.0

        sidebar_summary = {
            'income': m_in,
            'expense': m_out,
            'savings': m_sav,
            'budget_pct': min(b_pct, 100.0),
            'allocated': tot_alloc,
            'spent': tot_sp
        }

    total_notif_count = len(budget_alerts) + len(investment_alerts) + len(goal_alerts)

    return {
        'CURRENCIES': CURRENCIES,
        'COUNTRIES': COUNTRIES,
        'currency_code': code,
        'currency_symbol': symbol,
        'format_money': format_money,
        'user_theme': theme,
        'budget_alerts': budget_alerts,
        'investment_alerts': investment_alerts,
        'goal_alerts': goal_alerts,
        'total_notif_count': total_notif_count,
        'sidebar_summary': sidebar_summary,
        'csrf_token': session['csrf_token']
    }


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


def validate_phone(phone, country='India'):
    if not phone:
        return False, None
    clean = re.sub(r'[\s\-\(\)\.]', '', phone)
    
    if country == 'India':
        digits = clean
        if digits.startswith('+91'):
            digits = digits[3:]
        elif digits.startswith('91') and len(digits) == 12:
            digits = digits[2:]
        elif digits.startswith('0') and len(digits) == 11:
            digits = digits[1:]
        
        if re.match(r'^[6-9]\d{9}$', digits):
            return True, f"+91 {digits[:5]} {digits[5:]}"
        return False, None
    else:
        num_only = re.sub(r'[^\d]', '', clean)
        if 7 <= len(num_only) <= 15:
            if clean.startswith('+'):
                return True, clean
            return True, f"+{num_only}"
        return False, None


def get_last_6_months():
    now = datetime.now()
    months = []
    for i in range(5, -1, -1):
        year = now.year
        month = now.month - i
        while month <= 0:
            month += 12
            year -= 1
        key = f"{year:04d}-{month:02d}"
        label = datetime(year, month, 1).strftime('%b %Y')
        short_label = datetime(year, month, 1).strftime('%b')
        months.append({'key': key, 'label': label, 'short_label': short_label})
    return months


def seed_user_financial_profile(user):
    today = datetime.now()
    months = get_last_6_months()

    accounts = [
        Account(user_id=user.id, name='Primary Checking Account', account_type='Bank', balance=350000.0),
        Account(user_id=user.id, name='High-Yield Savings', account_type='Bank', balance=750000.0),
        Account(user_id=user.id, name='Corporate Credit Card', account_type='Credit Card', balance=-35000.0),
        Account(user_id=user.id, name='Mobile UPI & Digital Wallet', account_type='Wallet', balance=25000.0),
        Account(user_id=user.id, name='Petty Cash Reserve', account_type='Cash', balance=10000.0)
    ]
    for acc in accounts:
        db.session.add(acc)
    db.session.commit()

    primary_acc = accounts[0]
    credit_acc = accounts[2]
    wallet_acc = accounts[3]

    if user.role == 'admin':
        budgets = [
            BudgetCategory(user_id=user.id, name='Cloud Infrastructure & SaaS', allocated=450000.0, spent=392000.0, period='Monthly', alert_threshold=80),
            BudgetCategory(user_id=user.id, name='Platform Engineering & Payroll', allocated=850000.0, spent=814000.0, period='Monthly', alert_threshold=85),
            BudgetCategory(user_id=user.id, name='Regulatory & Security Compliance', allocated=250000.0, spent=175000.0, period='Monthly', alert_threshold=80),
            BudgetCategory(user_id=user.id, name='Enterprise Merchant Acquisition', allocated=350000.0, spent=368000.0, period='Monthly', alert_threshold=80),
            BudgetCategory(user_id=user.id, name='Corporate Facilities & Utilities', allocated=300000.0, spent=221000.0, period='Monthly', alert_threshold=80),
            BudgetCategory(user_id=user.id, name='Annual Datacenter Hardware Cap', allocated=4500000.0, spent=3200000.0, period='Yearly', alert_threshold=75)
        ]
        txns = []
        for idx, m in enumerate(months):
            mo_key = m['key']
            factor = 0.82 + (idx * 0.035)
            txns.append(Transaction(user_id=user.id, account_id=primary_acc.id, title='Enterprise Platform Licensing', category='Platform Revenue', amount=round(1850000.0 * factor, 2), txn_type='income', payment_mode='Bank Transfer', date=f"{mo_key}-05", status='Completed', notes=f"{m['label']} Corporate SaaS Invoicing"))
            txns.append(Transaction(user_id=user.id, account_id=primary_acc.id, title='Merchant Processing Volume Fees', category='Transaction Fees', amount=round(784500.0 * factor, 2), txn_type='income', payment_mode='Bank Transfer', date=f"{mo_key}-15", status='Completed', notes=f"{m['label']} Network interchange settlement"))
            txns.append(Transaction(user_id=user.id, account_id=credit_acc.id, title='AWS Cloud Hosting Infrastructure', category='Cloud Infrastructure & SaaS', amount=round(245000.0 * factor, 2), txn_type='expense', payment_mode='Credit Card', date=f"{mo_key}-10", status='Completed', notes=f"{m['label']} CDN & DB cluster nodes"))
            txns.append(Transaction(user_id=user.id, account_id=primary_acc.id, title='Engineering & Dev Payroll', category='Platform Engineering & Payroll', amount=round(650000.0 * factor, 2), txn_type='expense', payment_mode='Bank Transfer', date=f"{mo_key}-28", status='Completed', notes=f"{m['label']} Automated payroll cycle"))
            txns.append(Transaction(user_id=user.id, account_id=wallet_acc.id, title='Security Compliance Audit Review', category='Regulatory & Security Compliance', amount=round(175000.0 * factor, 2), txn_type='expense', payment_mode='Bank Transfer', date=f"{mo_key}-22", status='Completed', notes=f"{m['label']} Attestation & certification"))

    elif user.role == 'shop_owner':
        budgets = [
            BudgetCategory(user_id=user.id, name='Inventory Restock & Wholesale', allocated=380000.0, spent=345000.0, period='Monthly', alert_threshold=80),
            BudgetCategory(user_id=user.id, name='Storefront Lease & Utilities', allocated=120000.0, spent=118000.0, period='Monthly', alert_threshold=85),
            BudgetCategory(user_id=user.id, name='Retail Staff Wages & Overtime', allocated=160000.0, spent=149000.0, period='Monthly', alert_threshold=80),
            BudgetCategory(user_id=user.id, name='POS Terminals & Merchant Fees', allocated=65000.0, spent=68500.0, period='Monthly', alert_threshold=80),
            BudgetCategory(user_id=user.id, name='Local Promotional Campaigns', allocated=50000.0, spent=39500.0, period='Monthly', alert_threshold=80),
            BudgetCategory(user_id=user.id, name='Storefront Annual Renovation', allocated=1500000.0, spent=920000.0, period='Yearly', alert_threshold=70)
        ]
        txns = []
        for idx, m in enumerate(months):
            mo_key = m['key']
            factor = 0.85 + (idx * 0.03)
            txns.append(Transaction(user_id=user.id, account_id=primary_acc.id, title='Storefront Register Settlement', category='Retail Sales', amount=round(468000.0 * factor, 2), txn_type='income', payment_mode='UPI', date=f"{mo_key}-04", status='Completed', notes=f"{m['label']} Counter POS batches"))
            txns.append(Transaction(user_id=user.id, account_id=primary_acc.id, title='Online Delivery Marketplace Sales', category='E-Commerce', amount=round(184000.0 * factor, 2), txn_type='income', payment_mode='Bank Transfer', date=f"{mo_key}-18", status='Completed', notes=f"{m['label']} Partner fulfillment payouts"))
            txns.append(Transaction(user_id=user.id, account_id=primary_acc.id, title='FMCG Goods Wholesale Delivery', category='Inventory Restock & Wholesale', amount=round(215000.0 * factor, 2), txn_type='expense', payment_mode='Bank Transfer', date=f"{mo_key}-08", status='Completed', notes=f"{m['label']} Supplier batch invoice"))
            txns.append(Transaction(user_id=user.id, account_id=wallet_acc.id, title='Store Electricity & Cold Storage', category='Storefront Lease & Utilities', amount=round(34000.0 * factor, 2), txn_type='expense', payment_mode='UPI', date=f"{mo_key}-14", status='Completed', notes=f"{m['label']} Utility provider bill"))
            txns.append(Transaction(user_id=user.id, account_id=primary_acc.id, title='Floor Associates Wages', category='Retail Staff Wages & Overtime', amount=round(74500.0 * factor, 2), txn_type='expense', payment_mode='Bank Transfer', date=f"{mo_key}-26", status='Completed', notes=f"{m['label']} Staff bi-weekly payroll"))

    else:
        base_income = (user.total_income / 12.0) if (user.total_income and user.total_income > 0) else 85000.0
        budgets = [
            BudgetCategory(user_id=user.id, name='Housing & Rent / EMI', allocated=round(base_income * 0.32, 0), spent=round(base_income * 0.32, 0), period='Monthly', alert_threshold=85),
            BudgetCategory(user_id=user.id, name='Groceries & Household Goods', allocated=round(base_income * 0.18, 0), spent=round(base_income * 0.15, 0), period='Monthly', alert_threshold=80),
            BudgetCategory(user_id=user.id, name='Utilities, Mobile & Internet', allocated=round(base_income * 0.08, 0), spent=round(base_income * 0.07, 0), period='Monthly', alert_threshold=80),
            BudgetCategory(user_id=user.id, name='Transportation & Auto Fuel', allocated=round(base_income * 0.10, 0), spent=round(base_income * 0.11, 0), period='Monthly', alert_threshold=80),
            BudgetCategory(user_id=user.id, name='Savings, SIPs & Mutual Funds', allocated=round(base_income * 0.25, 0), spent=round(base_income * 0.22, 0), period='Monthly', alert_threshold=90),
            BudgetCategory(user_id=user.id, name='Annual Vacation & Travel Fund', allocated=round(base_income * 1.5, 0), spent=round(base_income * 1.1, 0), period='Yearly', alert_threshold=75)
        ]
        txns = []
        for idx, m in enumerate(months):
            mo_key = m['key']
            factor = 0.88 + (idx * 0.024)
            txns.append(Transaction(user_id=user.id, account_id=primary_acc.id, title='Primary Monthly Salary', category='Salary / Earnings', amount=round(base_income * factor, 2), txn_type='income', payment_mode='Bank Transfer', date=f"{mo_key}-01", status='Completed', notes=f"{m['label']} Direct payroll NEFT"))
            txns.append(Transaction(user_id=user.id, account_id=primary_acc.id, title='Advisory Consulting Retainer', category='Secondary Income', amount=round(base_income * 0.25 * factor, 2), txn_type='income', payment_mode='UPI', date=f"{mo_key}-15", status='Completed', notes=f"{m['label']} Professional advisory retainer"))
            txns.append(Transaction(user_id=user.id, account_id=primary_acc.id, title='Apartment Monthly Lease Payment', category='Housing & Rent / EMI', amount=round(base_income * 0.32, 2), txn_type='expense', payment_mode='Bank Transfer', date=f"{mo_key}-03", status='Completed', notes=f"{m['label']} Residence rent auto-debit"))
            txns.append(Transaction(user_id=user.id, account_id=credit_acc.id, title='Supermarket & Household Supplies', category='Groceries & Household Goods', amount=round(base_income * 0.14 * factor, 2), txn_type='expense', payment_mode='Credit Card', date=f"{mo_key}-11", status='Completed', notes=f"{m['label']} Pantry & kitchen essentials"))
            txns.append(Transaction(user_id=user.id, account_id=wallet_acc.id, title='High-Speed Fiber & Mobile Plan', category='Utilities, Mobile & Internet', amount=round(base_income * 0.07, 2), txn_type='expense', payment_mode='UPI', date=f"{mo_key}-19", status='Completed', notes=f"{m['label']} Utility bill payment"))
            txns.append(Transaction(user_id=user.id, account_id=primary_acc.id, title='Index Fund SIP Automated Allocation', category='Savings, SIPs & Mutual Funds', amount=round(base_income * 0.22, 2), txn_type='expense', payment_mode='Bank Transfer', date=f"{mo_key}-25", status='Completed', notes=f"{m['label']} Mutual fund monthly investment"))

    for b in budgets:
        db.session.add(b)
    for t in txns:
        db.session.add(t)
    db.session.commit()

    seed_user_investments_and_goals(user)


def seed_user_investments_and_goals(user):
    if Investment.query.filter_by(user_id=user.id).first() or Goal.query.filter_by(user_id=user.id).first():
        return

    is_usd = (user.currency == 'USD')
    if is_usd:
        holdings_spec = [
            ('Apple Inc.', 'AAPL', 'Equity', 25.0, 185.00, 228.50, 1.4, '2026-05-15', 'Core consumer tech holding'),
            ('Microsoft Corp.', 'MSFT', 'Equity', 20.0, 340.00, 425.00, 0.8, '2026-06-10', 'Cloud and AI enterprise infrastructure'),
            ('Vanguard S&P 500 ETF', 'VOO', 'ETF', 45.0, 410.00, 512.00, 0.4, '2026-04-20', 'Broad US large-cap passive index'),
            ('Fidelity Contrafund', 'FCNTX', 'Mutual Fund', 150.0, 18.50, 24.20, -0.2, '2026-03-12', 'Active large-cap growth fund'),
            ('US Treasury 10Y Benchmark', 'US10Y', 'Bond', 10.0, 980.00, 1025.00, 0.1, '2026-02-18', 'Fixed income sovereign capital preservation'),
            ('SPDR Gold Shares', 'GLD', 'Gold', 30.0, 195.00, 242.00, 0.6, '2026-01-25', 'Inflation hedge and precious metal reserve'),
            ('High-Yield Dollar Cash Reserve', 'CASH-USD', 'Cash', 1.0, 5000.00, 5000.00, 0.0, '2026-01-01', 'Emergency liquidity buffer')
        ]
    else:
        holdings_spec = [
            ('HDFC Bank Ltd.', 'HDFCBANK', 'Equity', 120.0, 1480.00, 1720.00, 1.4, '2026-05-12', 'Private sector banking anchor holding'),
            ('Reliance Industries Ltd.', 'RELIANCE', 'Equity', 65.0, 2650.00, 2980.00, 0.9, '2026-06-05', 'Conglomerate energy retail and telecom'),
            ('ICICI Prudential Bluechip Fund', 'ICICIBLUE', 'Mutual Fund', 1500.0, 82.50, 108.20, 0.5, '2026-03-15', 'Large-cap equity systematic SIP fund'),
            ('SBI Balanced Advantage Fund', 'SBIBALADV', 'Mutual Fund', 2200.0, 38.00, 47.60, -0.3, '2026-04-10', 'Dynamic asset allocation balanced fund'),
            ('Nippon India Growth Fund', 'NIPPONGROW', 'Mutual Fund', 180.0, 280.00, 365.00, 1.1, '2026-02-20', 'Mid-cap growth wealth compounder'),
            ('HDFC Corporate Bond Debt Fund', 'HDFCCORP', 'Debt', 3500.0, 24.50, 27.80, 0.05, '2026-01-18', 'AAA-rated corporate debt fixed income'),
            ('Sovereign Gold Bond 2026 Series', 'SGB2026', 'Gold', 25.0, 6200.00, 7650.00, 0.7, '2026-01-10', 'RBI sovereign gold bond with 2.5% coupon'),
            ('Liquid Bank Cash Reserve', 'CASH-INR', 'Cash', 1.0, 125000.00, 125000.00, 0.0, '2026-01-01', 'Liquid short-term emergency buffer')
        ]

    for h in holdings_spec:
        inv = Investment(
            user_id=user.id,
            asset_name=h[0],
            ticker=h[1],
            asset_type=h[2],
            quantity=h[3],
            purchase_price=h[4],
            current_price=h[5],
            day_change_pct=h[6],
            purchase_date=h[7],
            notes=h[8]
        )
        db.session.add(inv)
    db.session.commit()

    history_points = [
        ('2026-06-01', 0.88, 0.90, 2.2, 1.8),
        ('2026-06-15', 0.89, 0.92, 3.4, 2.6),
        ('2026-07-01', 0.90, 0.94, 4.4, 3.5),
        ('2026-07-15', 0.91, 0.96, 5.5, 4.1),
        ('2026-08-01', 0.92, 0.98, 6.5, 5.2),
        ('2026-08-15', 0.93, 1.01, 8.6, 6.0),
        ('2026-09-01', 0.95, 1.04, 9.5, 7.3),
        ('2026-09-15', 0.96, 1.07, 11.5, 8.1),
        ('2026-10-01', 0.97, 1.10, 13.4, 9.2),
        ('2026-10-15', 0.98, 1.13, 15.3, 10.4),
        ('2026-11-01', 0.99, 1.16, 17.2, 11.8),
        ('2026-11-15', 1.00, 1.19, 19.0, 12.5)
    ]

    total_inv = sum(i.invested_value for i in user.investments)
    total_cur = sum(i.current_value for i in user.investments)

    for hp in history_points:
        ph = PortfolioHistory(
            user_id=user.id,
            date=hp[0],
            invested_total=round(total_inv * hp[1], 2),
            portfolio_value=round(total_cur * hp[2], 2),
            portfolio_return_pct=hp[3],
            benchmark_return_pct=hp[4]
        )
        db.session.add(ph)

    if is_usd:
        goals_spec = [
            ('Buy a Home', 'Home', 450000.0, 145000.0, '2030-12-31', 9.5, [
                (15000.0, '2026-09-15', 'Q3 savings transfer towards down payment'),
                (18000.0, '2026-10-20', 'Annual performance bonus allocation'),
                (12000.0, '2026-11-10', 'Monthly systematic goal contribution')
            ]),
            ('Retirement Corpus', 'Retirement', 1200000.0, 280000.0, '2045-06-30', 11.0, [
                (8500.0, '2026-08-30', '401k IRA monthly contribution'),
                (9200.0, '2026-09-30', 'Index SIP automated allocation'),
                (9500.0, '2026-10-31', 'Retirement portfolio rebalancing sum')
            ]),
            ('Europe Family Vacation', 'Travel', 15000.0, 11200.0, '2027-08-15', 7.5, [
                (2500.0, '2026-09-05', 'Flight tickets savings deposit'),
                (3200.0, '2026-10-12', 'Hotel booking reserve fund')
            ]),
            ('Higher Education Reserve', 'Education', 120000.0, 52000.0, '2032-05-31', 10.5, [
                (4500.0, '2026-08-14', 'College 529 plan deposit'),
                (5000.0, '2026-10-18', 'Academic semester fund allocation')
            ])
        ]
    else:
        goals_spec = [
            ('Buy a Dream Home', 'Home', 8500000.0, 2850000.0, '2030-12-31', 9.5, [
                (350000.0, '2026-09-15', 'Down payment fixed deposit allocation'),
                (450000.0, '2026-10-20', 'Diwali festive bonus contribution'),
                (150000.0, '2026-11-10', 'Monthly systematic housing fund SIP')
            ]),
            ('Retirement Freedom Corpus', 'Retirement', 25000000.0, 6200000.0, '2045-06-30', 11.0, [
                (120000.0, '2026-08-30', 'NPS and PPF annual allocation'),
                (150000.0, '2026-09-30', 'Equity mutual fund retirement SIP'),
                (150000.0, '2026-10-31', 'Monthly index compounder deposit')
            ]),
            ('Europe Family Vacation', 'Travel', 650000.0, 480000.0, '2027-08-15', 7.5, [
                (75000.0, '2026-09-05', 'Flight booking installment savings'),
                (95000.0, '2026-10-12', 'Hotel reservation advance fund')
            ]),
            ('Child Higher Education Fund', 'Education', 3500000.0, 1450000.0, '2032-05-31', 10.5, [
                (85000.0, '2026-08-14', 'Children education hybrid fund deposit'),
                (95000.0, '2026-10-18', 'Target maturity debt fund contribution')
            ])
        ]

    for g in goals_spec:
        goal = Goal(
            user_id=user.id,
            goal_name=g[0],
            goal_type=g[1],
            target_amount=g[2],
            current_amount=g[3],
            target_date=g[4],
            expected_return_rate=g[5],
            status='On Track'
        )
        db.session.add(goal)
        db.session.flush()
        goal.status = goal.computed_status

        for txn in g[6]:
            gt = GoalTransaction(
                goal_id=goal.id,
                amount=txn[0],
                date=txn[1],
                notes=txn[2]
            )
            db.session.add(gt)

    db.session.commit()


def init_seed_demo_accounts():
    demo_specs = [
        {
            'fullname': 'Sarah Vance',
            'email': 'admin@finance.com',
            'password': 'admin123',
            'role': 'admin',
            'business': 'FinSight Enterprise Holdings',
            'age': 36,
            'phone': '+91 98201 44521',
            'country': 'India',
            'currency': 'INR',
            'theme': 'light',
            'address': 'Level 14, Cyber City, Phase II, Gurugram, Haryana',
            'total_income': 3500000.0,
            'income_sources': 'Enterprise Platform SaaS, Merchant Processing Fees',
            'financial_preferences': 'Aggressive Growth, SOC2 Compliance, Multi-Entity Consolidation'
        },
        {
            'fullname': 'Marcus Hayes',
            'email': 'shop@metrostore.com',
            'password': 'shop123',
            'role': 'shop_owner',
            'business': 'Metro Mart Superstore & Retail',
            'age': 42,
            'phone': '+91 98450 12890',
            'country': 'India',
            'currency': 'INR',
            'theme': 'light',
            'address': 'Shop #12-14, Commercial Market, Indiranagar, Bengaluru, Karnataka',
            'total_income': 1850000.0,
            'income_sources': 'Storefront POS Sales, Online Delivery Orders',
            'financial_preferences': 'Cashflow Maximization, Inventory Cost Reduction'
        },
        {
            'fullname': 'Elena Rostova',
            'email': 'user@personal.com',
            'password': 'user123',
            'role': 'user',
            'business': None,
            'age': 29,
            'phone': '+1 415 555 2671',
            'country': 'United States',
            'currency': 'USD',
            'theme': 'light',
            'address': 'Apt 402, Highline Residency, Bandra West, Mumbai, Maharashtra',
            'total_income': 120000.0,
            'income_sources': 'Corporate Salary, Advisory Consulting',
            'financial_preferences': 'Index Funds SIP, Emergency Fund 6-Months, Debt Free'
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
                country=spec['country'],
                currency=spec['currency'],
                theme=spec['theme'],
                address=spec['address'],
                total_income=spec['total_income'],
                income_sources=spec['income_sources'],
                financial_preferences=spec['financial_preferences']
            )
            db.session.add(user)
            db.session.commit()
            seed_user_financial_profile(user)
        else:
            seed_user_investments_and_goals(existing)


@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))


@app.route('/dashboard')
@login_required
def dashboard():
    if not current_user.budgets and not current_user.transactions:
        seed_user_financial_profile(current_user)

    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.date.desc(), Transaction.id.desc()).all()
    budgets = BudgetCategory.query.filter_by(user_id=current_user.id).all()
    accounts = Account.query.filter_by(user_id=current_user.id).all()

    total_income = sum(t.amount for t in transactions if t.txn_type == 'income')
    total_expense = sum(t.amount for t in transactions if t.txn_type == 'expense')
    net_profit = total_income - total_expense
    operating_margin = round((net_profit / total_income * 100), 1) if total_income > 0 else 0.0

    total_allocated = sum(b.allocated for b in budgets if b.period == 'Monthly')
    total_budget_spent = sum(b.spent for b in budgets if b.period == 'Monthly')
    budget_utilization = round((total_budget_spent / total_allocated * 100), 1) if total_allocated > 0 else 0.0
    budget_variance = round(total_allocated - total_budget_spent, 2)

    expense_by_cat = {}
    for t in transactions:
        if t.txn_type == 'expense':
            expense_by_cat[t.category] = expense_by_cat.get(t.category, 0.0) + t.amount

    palette = ['#1a56db', '#f97316', '#10b981', '#6366f1', '#ec4899', '#8b5cf6', '#14b8a6', '#f59e0b', '#06b6d4', '#64748b']
    donut_labels = list(expense_by_cat.keys())
    donut_data = [round(expense_by_cat[k], 2) for k in donut_labels]
    donut_colors = [palette[i % len(palette)] for i in range(len(donut_labels))]
    
    donut_items = []
    tot_exp = sum(donut_data)
    for idx, name in enumerate(donut_labels):
        val = donut_data[idx]
        pct = round((val / tot_exp * 100), 1) if tot_exp > 0 else 0
        donut_items.append({'name': name, 'amount': val, 'pct': pct, 'color': donut_colors[idx]})

    donut_items.sort(key=lambda x: x['amount'], reverse=True)

    months = get_last_6_months()
    income_by_month = {m['key']: 0.0 for m in months}
    expense_by_month = {m['key']: 0.0 for m in months}

    for t in transactions:
        mo_key = t.date[:7]
        if mo_key in income_by_month and t.txn_type == 'income':
            income_by_month[mo_key] += t.amount
        elif mo_key in expense_by_month and t.txn_type == 'expense':
            expense_by_month[mo_key] += t.amount

    trend_labels = [m['short_label'] for m in months]
    trend_income = [round(income_by_month[m['key']], 2) for m in months]
    trend_expense = [round(expense_by_month[m['key']], 2) for m in months]

    recent_transactions = transactions[:8]

    return render_template(
        'dashboard.html',
        active_page='dashboard',
        page_title='Dashboard',
        transactions=recent_transactions,
        budgets=budgets,
        accounts=accounts,
        total_income=total_income,
        total_expense=total_expense,
        net_profit=net_profit,
        operating_margin=operating_margin,
        total_allocated=total_allocated,
        total_budget_spent=total_budget_spent,
        budget_utilization=budget_utilization,
        budget_variance=budget_variance,
        donut_labels=donut_labels,
        donut_data=donut_data,
        donut_colors=donut_colors,
        donut_items=donut_items,
        trend_labels=trend_labels,
        trend_income=trend_income,
        trend_expense=trend_expense
    )


@app.route('/expenses')
@login_required
def expenses():
    query = Transaction.query.filter_by(user_id=current_user.id, txn_type='expense')

    search = request.args.get('q', '').strip().lower()
    cat_filter = request.args.get('category', '').strip()
    mode_filter = request.args.get('mode', '').strip()

    if search:
        query = query.filter((Transaction.title.ilike(f'%{search}%')) | (Transaction.notes.ilike(f'%{search}%')))
    if cat_filter:
        query = query.filter_by(category=cat_filter)
    if mode_filter:
        query = query.filter_by(payment_mode=mode_filter)

    transactions = query.order_by(Transaction.date.desc(), Transaction.id.desc()).all()
    all_expenses = Transaction.query.filter_by(user_id=current_user.id, txn_type='expense').all()

    total_expense = sum(t.amount for t in all_expenses)
    avg_expense = (total_expense / len(all_expenses)) if all_expenses else 0.0

    categories = sorted(list(set(t.category for t in all_expenses)))
    payment_modes = sorted(list(set(t.payment_mode for t in all_expenses if t.payment_mode)))

    top_cat = 'None'
    if all_expenses:
        cat_counts = {}
        for t in all_expenses:
            cat_counts[t.category] = cat_counts.get(t.category, 0.0) + t.amount
        top_cat = max(cat_counts, key=lambda k: cat_counts[k])

    accounts = Account.query.filter_by(user_id=current_user.id).all()

    return render_template(
        'expenses.html',
        active_page='expenses',
        page_title='Expenses',
        transactions=transactions,
        total_expense=total_expense,
        avg_expense=avg_expense,
        top_cat=top_cat,
        categories=categories,
        payment_modes=payment_modes,
        search=search,
        selected_category=cat_filter,
        selected_mode=mode_filter,
        accounts=accounts
    )


@app.route('/income')
@login_required
def income():
    query = Transaction.query.filter_by(user_id=current_user.id, txn_type='income')

    search = request.args.get('q', '').strip().lower()
    cat_filter = request.args.get('category', '').strip()
    mode_filter = request.args.get('mode', '').strip()

    if search:
        query = query.filter((Transaction.title.ilike(f'%{search}%')) | (Transaction.notes.ilike(f'%{search}%')))
    if cat_filter:
        query = query.filter_by(category=cat_filter)
    if mode_filter:
        query = query.filter_by(payment_mode=mode_filter)

    transactions = query.order_by(Transaction.date.desc(), Transaction.id.desc()).all()
    all_incomes = Transaction.query.filter_by(user_id=current_user.id, txn_type='income').all()

    total_income = sum(t.amount for t in all_incomes)
    avg_income = (total_income / len(all_incomes)) if all_incomes else 0.0

    categories = sorted(list(set(t.category for t in all_incomes)))
    payment_modes = sorted(list(set(t.payment_mode for t in all_incomes if t.payment_mode)))

    top_source = 'None'
    if all_incomes:
        cat_counts = {}
        for t in all_incomes:
            cat_counts[t.category] = cat_counts.get(t.category, 0.0) + t.amount
        top_source = max(cat_counts, key=lambda k: cat_counts[k])

    accounts = Account.query.filter_by(user_id=current_user.id).all()

    return render_template(
        'income.html',
        active_page='income',
        page_title='Income',
        transactions=transactions,
        total_income=total_income,
        avg_income=avg_income,
        top_source=top_source,
        categories=categories,
        payment_modes=payment_modes,
        search=search,
        selected_category=cat_filter,
        selected_mode=mode_filter,
        accounts=accounts
    )


@app.route('/budgets')
@login_required
def budgets():
    budgets_list = BudgetCategory.query.filter_by(user_id=current_user.id).all()
    
    monthly_budgets = [b for b in budgets_list if b.period == 'Monthly']
    yearly_budgets = [b for b in budgets_list if b.period == 'Yearly']

    total_monthly_allocated = sum(b.allocated for b in monthly_budgets)
    total_monthly_spent = sum(b.spent for b in monthly_budgets)
    monthly_pct = round((total_monthly_spent / total_monthly_allocated * 100), 1) if total_monthly_allocated > 0 else 0.0

    total_yearly_allocated = sum(b.allocated for b in yearly_budgets)
    total_yearly_spent = sum(b.spent for b in yearly_budgets)
    yearly_pct = round((total_yearly_spent / total_yearly_allocated * 100), 1) if total_yearly_allocated > 0 else 0.0

    return render_template(
        'budgets.html',
        active_page='budgets',
        page_title='Budgets',
        monthly_budgets=monthly_budgets,
        yearly_budgets=yearly_budgets,
        total_monthly_allocated=total_monthly_allocated,
        total_monthly_spent=total_monthly_spent,
        monthly_pct=monthly_pct,
        total_yearly_allocated=total_yearly_allocated,
        total_yearly_spent=total_yearly_spent,
        yearly_pct=yearly_pct
    )


@app.route('/add-budget', methods=['POST'])
@login_required
def add_budget():
    name = request.form.get('name', '').strip()
    allocated_str = request.form.get('allocated', '0').strip()
    spent_str = request.form.get('spent', '0').strip()
    period = request.form.get('period', 'Monthly').strip()
    threshold_str = request.form.get('alert_threshold', '80').strip()

    try:
        allocated = float(allocated_str)
        spent = float(spent_str) if spent_str else 0.0
        threshold = int(threshold_str) if threshold_str else 80
        if allocated <= 0:
            flash('Budget allocation must be positive.', 'danger')
            return redirect(url_for('budgets'))
    except ValueError:
        flash('Invalid numeric budget amount.', 'danger')
        return redirect(url_for('budgets'))

    if not name:
        flash('Budget category name is required.', 'danger')
        return redirect(url_for('budgets'))

    existing = BudgetCategory.query.filter_by(user_id=current_user.id, name=name, period=period).first()
    if existing:
        existing.allocated = allocated
        if spent > 0:
            existing.spent = spent
        existing.alert_threshold = threshold
        flash(f'Budget for "{name}" ({period}) updated successfully.', 'success')
    else:
        new_b = BudgetCategory(
            user_id=current_user.id,
            name=name,
            allocated=allocated,
            spent=spent,
            period=period,
            alert_threshold=threshold
        )
        db.session.add(new_b)
        flash(f'New {period} budget category "{name}" created.', 'success')

    db.session.commit()
    return redirect(url_for('budgets'))


@app.route('/edit-budget/<int:budget_id>', methods=['POST'])
@login_required
def edit_budget(budget_id):
    budget = BudgetCategory.query.filter_by(id=budget_id, user_id=current_user.id).first()
    if not budget:
        flash('Budget category not found.', 'danger')
        return redirect(url_for('budgets'))

    name = request.form.get('name', '').strip()
    allocated_str = request.form.get('allocated', '0').strip()
    spent_str = request.form.get('spent', '0').strip()
    period = request.form.get('period', 'Monthly').strip()
    threshold_str = request.form.get('alert_threshold', '80').strip()

    try:
        allocated = float(allocated_str)
        spent = float(spent_str) if spent_str else budget.spent
        threshold = int(threshold_str) if threshold_str else 80
        if allocated <= 0:
            flash('Allocation cap must be positive.', 'danger')
            return redirect(url_for('budgets'))
    except ValueError:
        flash('Please enter valid numerical figures.', 'danger')
        return redirect(url_for('budgets'))

    if name:
        budget.name = name
    budget.allocated = allocated
    budget.spent = spent
    budget.period = period
    budget.alert_threshold = threshold

    db.session.commit()
    flash(f'Budget "{budget.name}" updated successfully.', 'success')
    return redirect(url_for('budgets'))


@app.route('/delete-budget/<int:budget_id>', methods=['POST'])
@login_required
def delete_budget(budget_id):
    b = BudgetCategory.query.filter_by(id=budget_id, user_id=current_user.id).first()
    if b:
        db.session.delete(b)
        db.session.commit()
        flash('Budget category removed.', 'info')
    return redirect(url_for('budgets'))


@app.route('/accounts')
@login_required
def accounts():
    accounts_list = Account.query.filter_by(user_id=current_user.id).all()
    total_balance = sum(a.balance for a in accounts_list)
    bank_balance = sum(a.balance for a in accounts_list if a.account_type == 'Bank')
    card_balance = sum(a.balance for a in accounts_list if a.account_type == 'Credit Card')
    wallet_balance = sum(a.balance for a in accounts_list if a.account_type in ['Wallet', 'Cash'])

    return render_template(
        'accounts.html',
        active_page='accounts',
        page_title='Accounts & Wallets',
        accounts=accounts_list,
        total_balance=total_balance,
        bank_balance=bank_balance,
        card_balance=card_balance,
        wallet_balance=wallet_balance
    )


@app.route('/add-account', methods=['POST'])
@login_required
def add_account():
    name = request.form.get('name', '').strip()
    account_type = request.form.get('account_type', 'Bank').strip()
    balance_str = request.form.get('balance', '0').strip()

    try:
        balance = float(balance_str) if balance_str else 0.0
    except ValueError:
        flash('Invalid numeric initial balance.', 'danger')
        return redirect(url_for('accounts'))

    if not name:
        flash('Account name is required.', 'danger')
        return redirect(url_for('accounts'))

    new_acc = Account(
        user_id=current_user.id,
        name=name,
        account_type=account_type,
        balance=balance
    )
    db.session.add(new_acc)
    db.session.commit()
    flash(f'Account "{name}" ({account_type}) added successfully.', 'success')
    return redirect(url_for('accounts'))


@app.route('/delete-account/<int:account_id>', methods=['POST'])
@login_required
def delete_account(account_id):
    acc = Account.query.filter_by(id=account_id, user_id=current_user.id).first()
    if acc:
        db.session.delete(acc)
        db.session.commit()
        flash(f'Account "{acc.name}" removed.', 'info')
    return redirect(url_for('accounts'))


@app.route('/categories')
@login_required
def categories():
    expenses_list = Transaction.query.filter_by(user_id=current_user.id, txn_type='expense').all()
    total_spent = sum(t.amount for t in expenses_list)

    cat_stats = {}
    for t in expenses_list:
        if t.category not in cat_stats:
            cat_stats[t.category] = {'count': 0, 'total': 0.0, 'modes': set()}
        cat_stats[t.category]['count'] += 1
        cat_stats[t.category]['total'] += t.amount
        if t.payment_mode:
            cat_stats[t.category]['modes'].add(t.payment_mode)

    cat_rows = []
    palette = ['#1a56db', '#f97316', '#10b981', '#6366f1', '#ec4899', '#8b5cf6', '#14b8a6', '#f59e0b', '#06b6d4', '#64748b']
    for idx, (cat_name, data) in enumerate(cat_stats.items()):
        pct = round((data['total'] / total_spent * 100), 1) if total_spent > 0 else 0.0
        avg_txn = round(data['total'] / data['count'], 2) if data['count'] > 0 else 0.0
        cat_rows.append({
            'name': cat_name,
            'count': data['count'],
            'total': round(data['total'], 2),
            'pct': pct,
            'avg': avg_txn,
            'modes': ', '.join(sorted(data['modes'])),
            'color': palette[idx % len(palette)]
        })

    cat_rows.sort(key=lambda x: x['total'], reverse=True)

    return render_template(
        'categories.html',
        active_page='categories',
        page_title='Categories',
        categories=cat_rows,
        total_spent=total_spent,
        total_txns=len(expenses_list)
    )


@app.route('/reports')
@login_required
def reports():
    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.date.desc()).all()
    budgets = BudgetCategory.query.filter_by(user_id=current_user.id).all()

    total_income = sum(t.amount for t in transactions if t.txn_type == 'income')
    total_expense = sum(t.amount for t in transactions if t.txn_type == 'expense')
    net_profit = total_income - total_expense
    operating_margin = round((net_profit / total_income * 100), 1) if total_income > 0 else 0.0

    cogs_estimate = round(total_expense * 0.65, 2)
    gross_margin = round(total_income - cogs_estimate, 2)
    overheads_estimate = round(total_expense * 0.35, 2)

    cat_breakdown = {}
    for t in transactions:
        if t.txn_type == 'expense':
            cat_breakdown[t.category] = cat_breakdown.get(t.category, 0.0) + t.amount

    return render_template(
        'reports.html',
        active_page='reports',
        page_title='Financial Reports',
        transactions=transactions,
        budgets=budgets,
        total_income=total_income,
        total_expense=total_expense,
        net_profit=net_profit,
        operating_margin=operating_margin,
        cogs_estimate=cogs_estimate,
        gross_margin=gross_margin,
        overheads_estimate=overheads_estimate,
        cat_breakdown=cat_breakdown,
        today_date=datetime.now().strftime('%B %d, %Y')
    )


@app.route('/export/csv')
@login_required
def export_csv():
    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.date.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Title', 'Category', 'Type', 'Amount', 'Payment Mode', 'Status', 'Notes'])

    for t in transactions:
        writer.writerow([t.date, t.title, t.category, t.txn_type.capitalize(), f"{t.amount:.2f}", t.payment_mode or '', t.status or 'Completed', t.notes or ''])

    output.seek(0)
    filename = f"FinSight_Ledger_{current_user.fullname.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )


@app.route('/investments')
@login_required
def investments():
    if not current_user.investments and not current_user.goals:
        seed_user_investments_and_goals(current_user)

    active_tab = request.args.get('tab', 'overview')
    inv_list = Investment.query.filter_by(user_id=current_user.id).order_by(Investment.created_at.desc()).all()

    total_portfolio_value = round(sum(i.current_value for i in inv_list), 2)
    total_invested = round(sum(i.invested_value for i in inv_list), 2)
    overall_return = round(total_portfolio_value - total_invested, 2)
    overall_return_pct = round((overall_return / total_invested) * 100, 2) if total_invested > 0 else 0.0
    today_change_value = round(sum(i.day_change_value for i in inv_list), 2)
    today_change_pct = round((today_change_value / total_portfolio_value) * 100, 2) if total_portfolio_value > 0 else 0.0

    allocation_map = {}
    for i in inv_list:
        allocation_map[i.asset_type] = allocation_map.get(i.asset_type, 0.0) + i.current_value

    allocation_breakdown = []
    target_alloc_map = {
        'Equity': 45.0,
        'Mutual Fund': 25.0,
        'ETF': 10.0,
        'Debt': 10.0,
        'Bond': 10.0,
        'Gold': 5.0,
        'Cash': 5.0,
        'Other': 5.0
    }
    for asset_type, val in sorted(allocation_map.items(), key=lambda x: x[1], reverse=True):
        share_pct = round((val / total_portfolio_value) * 100, 1) if total_portfolio_value > 0 else 0.0
        tgt_pct = target_alloc_map.get(asset_type, 10.0)
        diff = round(share_pct - tgt_pct, 1)
        hint = 'Overweight' if diff > 3.0 else ('Underweight' if diff < -3.0 else 'Balanced')
        allocation_breakdown.append({
            'type': asset_type,
            'value': round(val, 2),
            'share_pct': share_pct,
            'target_pct': tgt_pct,
            'diff': diff,
            'hint': hint
        })

    history_records = PortfolioHistory.query.filter_by(user_id=current_user.id).order_by(PortfolioHistory.date.asc()).all()
    if not history_records:
        history_records = [
            PortfolioHistory(
                user_id=current_user.id,
                date=datetime.now().strftime('%Y-%m-%d'),
                invested_total=total_invested,
                portfolio_value=total_portfolio_value,
                portfolio_return_pct=overall_return_pct,
                benchmark_return_pct=12.5
            )
        ]

    chart_labels = [h.date for h in history_records]
    chart_portfolio_returns = [h.portfolio_return_pct for h in history_records]
    chart_benchmark_returns = [h.benchmark_return_pct for h in history_records]
    chart_values = [h.portfolio_value for h in history_records]

    top_holdings = sorted(inv_list, key=lambda x: x.current_value, reverse=True)[:5]
    user_goals = Goal.query.filter_by(user_id=current_user.id).order_by(Goal.target_date.asc()).limit(4).all()

    equity_and_mf_pct = sum(item['share_pct'] for item in allocation_breakdown if item['type'] in ['Equity', 'Mutual Fund', 'ETF'])
    if equity_and_mf_pct >= 65.0:
        risk_profile = 'Aggressive'
    elif equity_and_mf_pct >= 35.0:
        risk_profile = 'Moderate'
    else:
        risk_profile = 'Conservative'

    latest_bench = chart_benchmark_returns[-1] if chart_benchmark_returns else 12.0
    portfolio_alpha = round(overall_return_pct - latest_bench, 2)
    top_gainer = max(inv_list, key=lambda x: x.return_pct) if inv_list else None
    top_laggard = min(inv_list, key=lambda x: x.return_pct) if inv_list else None

    txns_history = []
    for inv in inv_list:
        txns_history.append({
            'date': inv.purchase_date,
            'type': 'Purchase',
            'instrument': inv.asset_name,
            'category': inv.asset_type,
            'quantity': inv.quantity,
            'price': inv.purchase_price,
            'total': inv.invested_value,
            'notes': inv.notes or 'Initial portfolio asset acquisition'
        })
    for g in Goal.query.filter_by(user_id=current_user.id).all():
        for ct in g.contributions:
            txns_history.append({
                'date': ct.date,
                'type': 'Goal Contribution',
                'instrument': g.goal_name,
                'category': f"Goal: {g.goal_type}",
                'quantity': 1.0,
                'price': ct.amount,
                'total': ct.amount,
                'notes': ct.notes or f"Contribution to {g.goal_name}"
            })
    txns_history.sort(key=lambda x: x['date'], reverse=True)

    return render_template(
        'investments.html',
        page_title='Investment Portfolio',
        active_page='investments',
        active_tab=active_tab,
        investments=inv_list,
        total_portfolio_value=total_portfolio_value,
        total_invested=total_invested,
        overall_return=overall_return,
        overall_return_pct=overall_return_pct,
        today_change_value=today_change_value,
        today_change_pct=today_change_pct,
        allocation_breakdown=allocation_breakdown,
        top_holdings=top_holdings,
        goals_summary=user_goals,
        chart_labels=chart_labels,
        chart_portfolio_returns=chart_portfolio_returns,
        chart_benchmark_returns=chart_benchmark_returns,
        chart_values=chart_values,
        risk_profile=risk_profile,
        portfolio_alpha=portfolio_alpha,
        top_gainer=top_gainer,
        top_laggard=top_laggard,
        txns_history=txns_history,
        today_date=datetime.now().strftime('%Y-%m-%d')
    )


@app.route('/add-investment', methods=['POST'])
@login_required
def add_investment():
    asset_name = request.form.get('asset_name', '').strip()
    ticker = request.form.get('ticker', '').strip().upper()
    asset_type = request.form.get('asset_type', 'Equity').strip()
    qty_str = request.form.get('quantity', '1').strip()
    buy_str = request.form.get('purchase_price', '0').strip()
    curr_str = request.form.get('current_price', '0').strip()
    day_str = request.form.get('day_change_pct', '0').strip()
    p_date = request.form.get('purchase_date', datetime.now().strftime('%Y-%m-%d')).strip()
    notes = request.form.get('notes', '').strip()

    try:
        qty = float(qty_str)
        buy_price = float(buy_str)
        curr_price = float(curr_str) if curr_str else buy_price
        day_pct = float(day_str) if day_str else 0.0

        if not asset_name:
            flash('Instrument name is required.', 'danger')
            return redirect(url_for('investments', tab='holdings'))
        if qty <= 0 or buy_price <= 0:
            flash('Quantity and purchase price must be positive numbers.', 'danger')
            return redirect(url_for('investments', tab='holdings'))

        inv = Investment(
            user_id=current_user.id,
            asset_name=asset_name,
            ticker=ticker if ticker else None,
            asset_type=asset_type,
            quantity=qty,
            purchase_price=buy_price,
            current_price=curr_price,
            day_change_pct=day_pct,
            purchase_date=p_date,
            notes=notes if notes else None
        )
        db.session.add(inv)
        db.session.commit()

        all_inv = Investment.query.filter_by(user_id=current_user.id).all()
        tot_val = sum(i.current_value for i in all_inv)
        tot_inv = sum(i.invested_value for i in all_inv)
        ret_pct = round(((tot_val - tot_inv) / tot_inv) * 100, 2) if tot_inv > 0 else 0.0
        ph = PortfolioHistory(
            user_id=current_user.id,
            investment_id=inv.id,
            date=datetime.now().strftime('%Y-%m-%d'),
            invested_total=tot_inv,
            portfolio_value=tot_val,
            portfolio_return_pct=ret_pct,
            benchmark_return_pct=12.5
        )
        db.session.add(ph)
        db.session.commit()

        flash(f'Investment holding {asset_name} added to portfolio successfully!', 'success')
    except ValueError:
        flash('Please enter valid numeric figures for financial fields.', 'danger')

    return redirect(url_for('investments', tab='holdings'))


@app.route('/edit-investment/<int:inv_id>', methods=['POST'])
@login_required
def edit_investment(inv_id):
    inv = db.session.get(Investment, inv_id)
    if not inv or inv.user_id != current_user.id:
        flash('Investment holding not found or unauthorized access.', 'danger')
        return redirect(url_for('investments', tab='holdings'))

    qty_str = request.form.get('quantity', str(inv.quantity)).strip()
    buy_str = request.form.get('purchase_price', str(inv.purchase_price)).strip()
    curr_str = request.form.get('current_price', str(inv.current_price)).strip()
    day_str = request.form.get('day_change_pct', str(inv.day_change_pct or 0.0)).strip()
    notes = request.form.get('notes', inv.notes or '').strip()

    try:
        inv.quantity = float(qty_str)
        inv.purchase_price = float(buy_str)
        inv.current_price = float(curr_str)
        inv.day_change_pct = float(day_str)
        inv.notes = notes if notes else None
        db.session.commit()

        all_inv = Investment.query.filter_by(user_id=current_user.id).all()
        tot_val = sum(i.current_value for i in all_inv)
        tot_inv = sum(i.invested_value for i in all_inv)
        ret_pct = round(((tot_val - tot_inv) / tot_inv) * 100, 2) if tot_inv > 0 else 0.0
        ph = PortfolioHistory(
            user_id=current_user.id,
            investment_id=inv.id,
            date=datetime.now().strftime('%Y-%m-%d'),
            invested_total=tot_inv,
            portfolio_value=tot_val,
            portfolio_return_pct=ret_pct,
            benchmark_return_pct=12.5
        )
        db.session.add(ph)
        db.session.commit()

        flash(f'Holding {inv.asset_name} market parameters updated successfully!', 'success')
    except ValueError:
        flash('Please enter valid numeric figures for financial fields.', 'danger')

    return redirect(url_for('investments', tab='holdings'))


@app.route('/delete-investment/<int:inv_id>', methods=['POST'])
@login_required
def delete_investment(inv_id):
    inv = db.session.get(Investment, inv_id)
    if not inv or inv.user_id != current_user.id:
        flash('Investment holding not found or unauthorized access.', 'danger')
        return redirect(url_for('investments', tab='holdings'))

    name = inv.asset_name
    db.session.delete(inv)
    db.session.commit()
    flash(f'Holding {name} removed from your portfolio.', 'success')
    return redirect(url_for('investments', tab='holdings'))


@app.route('/export/investments-csv')
@login_required
def export_investments_csv():
    holdings = Investment.query.filter_by(user_id=current_user.id).order_by(Investment.asset_type.asc(), Investment.asset_name.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Instrument', 'Ticker', 'Asset Type', 'Quantity', 'Avg Purchase Price',
        'Current Price', 'Invested Value', 'Current Value', 'Absolute Return',
        'Return %', 'Day Change %', 'Purchase Date', 'Notes'
    ])

    for h in holdings:
        writer.writerow([
            h.asset_name,
            h.ticker or '',
            h.asset_type,
            h.quantity,
            h.purchase_price,
            h.current_price,
            h.invested_value,
            h.current_value,
            h.absolute_return,
            f"{h.return_pct}%",
            f"{h.day_change_pct}%",
            h.purchase_date,
            h.notes or ''
        ])

    output.seek(0)
    filename = f"FinSight_Holdings_{current_user.fullname.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )


@app.route('/goals')
@login_required
def goals():
    if not current_user.goals and not current_user.investments:
        seed_user_investments_and_goals(current_user)

    user_goals = Goal.query.filter_by(user_id=current_user.id).order_by(Goal.target_date.asc()).all()
    for g in user_goals:
        new_status = g.computed_status
        if g.status != new_status:
            g.status = new_status
    db.session.commit()

    active_goals_count = len(user_goals)
    total_target = round(sum(g.target_amount for g in user_goals), 2)
    total_saved = round(sum(g.current_amount for g in user_goals), 2)
    overall_progress = round((total_saved / total_target) * 100, 1) if total_target > 0 else 0.0

    user_accounts = Account.query.filter_by(user_id=current_user.id).order_by(Account.name.asc()).all()
    goal_names = [g.goal_name for g in user_goals]
    goal_saved_amounts = [g.current_amount for g in user_goals]
    goal_target_amounts = [g.target_amount for g in user_goals]

    return render_template(
        'goals.html',
        page_title='Financial Goal Planning',
        active_page='goals',
        goals=user_goals,
        active_goals_count=active_goals_count,
        total_target=total_target,
        total_saved=total_saved,
        overall_progress=overall_progress,
        accounts=user_accounts,
        goal_names=goal_names,
        goal_saved_amounts=goal_saved_amounts,
        goal_target_amounts=goal_target_amounts,
        today_date=datetime.now().strftime('%Y-%m-%d')
    )


@app.route('/add-goal', methods=['POST'])
@login_required
def add_goal():
    goal_name = request.form.get('goal_name', '').strip()
    goal_type = request.form.get('goal_type', 'Other').strip()
    target_str = request.form.get('target_amount', '0').strip()
    curr_str = request.form.get('current_amount', '0').strip()
    target_date = request.form.get('target_date', '').strip()
    return_str = request.form.get('expected_return_rate', '10.0').strip()

    try:
        target_amount = float(target_str)
        current_amount = float(curr_str) if curr_str else 0.0
        expected_return_rate = float(return_str) if return_str else 10.0

        if not goal_name:
            flash('Goal name is required.', 'danger')
            return redirect(url_for('goals'))
        if target_amount <= 0:
            flash('Target corpus amount must be positive.', 'danger')
            return redirect(url_for('goals'))
        if not target_date:
            flash('Target completion date is required.', 'danger')
            return redirect(url_for('goals'))

        g = Goal(
            user_id=current_user.id,
            goal_name=goal_name,
            goal_type=goal_type,
            target_amount=target_amount,
            current_amount=current_amount,
            target_date=target_date,
            expected_return_rate=expected_return_rate,
            status='On Track'
        )
        db.session.add(g)
        db.session.flush()
        g.status = g.computed_status

        if current_amount > 0:
            gt = GoalTransaction(
                goal_id=g.id,
                amount=current_amount,
                date=datetime.now().strftime('%Y-%m-%d'),
                notes='Initial seed fund balance'
            )
            db.session.add(gt)

        db.session.commit()
        flash(f'Financial goal "{goal_name}" created with target projection tracking.', 'success')
    except ValueError:
        flash('Please enter valid numeric figures for financial targets.', 'danger')

    return redirect(url_for('goals'))


@app.route('/edit-goal/<int:goal_id>', methods=['POST'])
@login_required
def edit_goal(goal_id):
    goal = db.session.get(Goal, goal_id)
    if not goal or goal.user_id != current_user.id:
        flash('Financial goal not found or unauthorized access.', 'danger')
        return redirect(url_for('goals'))

    goal_name = request.form.get('goal_name', goal.goal_name).strip()
    goal_type = request.form.get('goal_type', goal.goal_type).strip()
    target_str = request.form.get('target_amount', str(goal.target_amount)).strip()
    curr_str = request.form.get('current_amount', str(goal.current_amount)).strip()
    target_date = request.form.get('target_date', goal.target_date).strip()
    return_str = request.form.get('expected_return_rate', str(goal.expected_return_rate)).strip()

    try:
        goal.goal_name = goal_name
        goal.goal_type = goal_type
        goal.target_amount = float(target_str)
        goal.current_amount = float(curr_str)
        goal.target_date = target_date
        goal.expected_return_rate = float(return_str)
        goal.status = goal.computed_status
        db.session.commit()
        flash(f'Goal "{goal.goal_name}" settings updated successfully.', 'success')
    except ValueError:
        flash('Please enter valid numeric values for goal targets.', 'danger')

    return redirect(url_for('goals'))


@app.route('/contribute-goal/<int:goal_id>', methods=['POST'])
@login_required
def contribute_goal(goal_id):
    goal = db.session.get(Goal, goal_id)
    if not goal or goal.user_id != current_user.id:
        flash('Financial goal not found or unauthorized access.', 'danger')
        return redirect(url_for('goals'))

    amount_str = request.form.get('amount', '0').strip()
    date_val = request.form.get('date', datetime.now().strftime('%Y-%m-%d')).strip()
    notes = request.form.get('notes', '').strip()
    account_id_str = request.form.get('account_id', '').strip()

    try:
        amount = float(amount_str)
        if amount <= 0:
            flash('Contribution amount must be greater than zero.', 'danger')
            return redirect(url_for('goals'))

        goal.current_amount = round(goal.current_amount + amount, 2)
        goal.status = goal.computed_status

        gt = GoalTransaction(
            goal_id=goal.id,
            amount=amount,
            date=date_val,
            notes=notes or f"Contribution to {goal.goal_name}"
        )
        db.session.add(gt)

        if account_id_str:
            acc = db.session.get(Account, int(account_id_str))
            if acc and acc.user_id == current_user.id:
                acc.balance = round(acc.balance - amount, 2)
                txn = Transaction(
                    user_id=current_user.id,
                    account_id=acc.id,
                    title=f"Goal Contribution: {goal.goal_name}",
                    category='Savings & Goals',
                    amount=amount,
                    txn_type='expense',
                    payment_mode='Bank Transfer',
                    date=date_val,
                    status='Completed',
                    notes=notes or f"Fund transfer to {goal.goal_name}"
                )
                db.session.add(txn)
                db.session.flush()
                gt.transaction_id = txn.id

        db.session.commit()
        flash(f'Added {format_money(amount)} contribution to {goal.goal_name} successfully!', 'success')
    except ValueError:
        flash('Please enter a valid numeric contribution amount.', 'danger')

    return redirect(url_for('goals'))


@app.route('/delete-goal/<int:goal_id>', methods=['POST'])
@login_required
def delete_goal(goal_id):
    goal = db.session.get(Goal, goal_id)
    if not goal or goal.user_id != current_user.id:
        flash('Financial goal not found or unauthorized access.', 'danger')
        return redirect(url_for('goals'))

    name = goal.goal_name
    db.session.delete(goal)
    db.session.commit()
    flash(f'Financial goal "{name}" deleted successfully.', 'success')
    return redirect(url_for('goals'))


@app.route('/settings')
@login_required
def settings():
    return render_template(
        'settings.html',
        active_page='settings',
        page_title='Settings',
        user=current_user
    )


@app.route('/settings/profile', methods=['POST'])
@login_required
def update_profile():
    fullname = request.form.get('fullname', '').strip()
    email = request.form.get('email', '').strip().lower()
    phone = request.form.get('phone', '').strip()
    country = request.form.get('country', 'India').strip()
    currency = request.form.get('currency', 'INR').strip()
    address = request.form.get('address', '').strip()
    age_str = request.form.get('age', '').strip()
    biz_name = request.form.get('business_name', '').strip()
    income_str = request.form.get('total_income', '0').strip()
    income_sources = request.form.get('income_sources', '').strip()
    financial_preferences = request.form.get('financial_preferences', '').strip()

    if not fullname:
        flash('Full name is required.', 'danger')
        return redirect(url_for('settings'))

    if not email or not validate_email_format(email):
        flash('Valid email address is required.', 'danger')
        return redirect(url_for('settings'))

    existing = User.query.filter(User.email == email, User.id != current_user.id).first()
    if existing:
        flash('This email address is already in use by another account.', 'danger')
        return redirect(url_for('settings'))

    is_valid_phone, formatted_phone = validate_phone(phone, country)
    if not is_valid_phone:
        if country == 'India':
            flash('Please enter a valid 10-digit Indian phone number starting with 6, 7, 8, or 9.', 'danger')
        else:
            flash('Please enter a valid international phone number (7 to 15 digits).', 'danger')
        return redirect(url_for('settings'))

    age = current_user.age
    if age_str:
        try:
            val = int(age_str)
            if 18 <= val <= 110:
                age = val
            else:
                flash('Age must be between 18 and 110.', 'danger')
                return redirect(url_for('settings'))
        except ValueError:
            flash('Invalid numeric age.', 'danger')
            return redirect(url_for('settings'))

    total_income = current_user.total_income
    if income_str:
        try:
            val = float(income_str)
            if val >= 0:
                total_income = val
        except ValueError:
            pass

    current_user.fullname = fullname
    current_user.email = email
    current_user.phone = formatted_phone
    current_user.country = country
    if currency in CURRENCIES:
        current_user.currency = currency
    current_user.address = address
    current_user.age = age
    current_user.business_name = biz_name if biz_name else None
    current_user.total_income = total_income
    current_user.income_sources = income_sources
    current_user.financial_preferences = financial_preferences

    db.session.commit()
    flash('Your profile and financial preferences have been updated.', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/security', methods=['POST'])
@login_required
def update_security():
    current_pw = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')

    if not check_password_hash(current_user.password, current_pw):
        flash('The current password entered is incorrect.', 'danger')
        return redirect(url_for('settings'))

    if len(new_pw) < 8:
        flash('New password must be at least 8 characters long.', 'danger')
        return redirect(url_for('settings'))

    if new_pw != confirm_pw:
        flash('New passwords do not match.', 'danger')
        return redirect(url_for('settings'))

    current_user.password = generate_password_hash(new_pw)
    db.session.commit()
    flash('Your password has been changed successfully.', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/theme', methods=['POST'])
@login_required
def update_theme():
    theme = request.form.get('theme', 'light').strip()
    if theme in ['light', 'dark']:
        current_user.theme = theme
        db.session.commit()
        flash(f'Theme changed to {theme.capitalize()} Mode.', 'success')
    return redirect(url_for('settings'))


@app.route('/toggle-theme', methods=['POST', 'GET'])
@login_required
def toggle_theme():
    current_user.theme = 'dark' if current_user.theme == 'light' else 'light'
    db.session.commit()
    return redirect(request.referrer or url_for('dashboard'))


@app.route('/add-transaction', methods=['POST'])
@login_required
def add_transaction():
    title = request.form.get('title', '').strip()
    category = request.form.get('category', '').strip()
    amount_str = request.form.get('amount', '0').strip()
    txn_type = request.form.get('txn_type', 'expense').strip().lower()
    payment_mode = request.form.get('payment_mode', 'UPI').strip()
    account_id_str = request.form.get('account_id', '').strip()
    date_val = request.form.get('date', datetime.now().strftime('%Y-%m-%d')).strip()
    notes = request.form.get('notes', '').strip()

    try:
        amount = float(amount_str)
        if amount <= 0:
            flash('Transaction amount must be greater than zero.', 'danger')
            return redirect(request.referrer or url_for('dashboard'))
    except ValueError:
        flash('Please enter a valid numeric transaction amount.', 'danger')
        return redirect(request.referrer or url_for('dashboard'))

    if not title or not category:
        flash('Transaction title and category are required.', 'danger')
        return redirect(request.referrer or url_for('dashboard'))

    account_id = None
    if account_id_str:
        try:
            account_id = int(account_id_str)
        except ValueError:
            pass

    new_txn = Transaction(
        user_id=current_user.id,
        account_id=account_id,
        title=title,
        category=category,
        amount=amount,
        txn_type=txn_type,
        payment_mode=payment_mode,
        date=date_val,
        status='Completed',
        notes=notes
    )
    db.session.add(new_txn)

    if account_id:
        acc = Account.query.filter_by(id=account_id, user_id=current_user.id).first()
        if acc:
            if txn_type == 'income':
                acc.balance += amount
            else:
                acc.balance -= amount

    if txn_type == 'expense':
        matched_budget = BudgetCategory.query.filter_by(user_id=current_user.id, name=category).first()
        if matched_budget:
            matched_budget.spent += amount

    db.session.commit()
    _, sym = get_user_currency_info()
    flash(f'Transaction "{title}" ({sym}{amount:,.2f}) recorded successfully.', 'success')
    return redirect(request.referrer or url_for('dashboard'))


@app.route('/delete-transaction/<int:txn_id>', methods=['POST'])
@login_required
def delete_transaction(txn_id):
    txn = Transaction.query.filter_by(id=txn_id, user_id=current_user.id).first()
    if txn:
        if txn.account_id:
            acc = Account.query.filter_by(id=txn.account_id, user_id=current_user.id).first()
            if acc:
                if txn.txn_type == 'income':
                    acc.balance -= txn.amount
                else:
                    acc.balance += txn.amount

        if txn.txn_type == 'expense':
            matched_budget = BudgetCategory.query.filter_by(user_id=current_user.id, name=txn.category).first()
            if matched_budget:
                matched_budget.spent = max(0.0, matched_budget.spent - txn.amount)

        db.session.delete(txn)
        db.session.commit()
        flash('Transaction removed from financial ledger.', 'info')
    return redirect(request.referrer or url_for('dashboard'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        fullname         = request.form.get('fullname', '').strip()
        email            = request.form.get('email', '').strip().lower()
        role             = request.form.get('role', 'user').strip()
        business_name    = request.form.get('business_name', '').strip()
        
        country          = request.form.get('country', 'India').strip()
        currency         = request.form.get('currency', 'INR').strip()
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
            is_valid_phone, formatted_phone = validate_phone(phone, country)
            if not is_valid_phone:
                if country == 'India':
                    error = 'Please enter a valid 10-digit Indian phone number starting with 6, 7, 8, or 9.'
                else:
                    error = 'Please enter a valid international phone number (7 to 15 digits).'
            elif formatted_phone is not None:
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

        if currency not in CURRENCIES:
            currency = 'INR'

        if error:
            flash(error, 'danger')
            return render_template(
                'register.html',
                fullname=fullname,
                email=email,
                role=role,
                business_name=business_name,
                country=country,
                currency=currency,
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
            country=country,
            currency=currency,
            theme='light',
            age=age,
            phone=phone,
            address=address,
            total_income=total_income
        )
        db.session.add(new_user)
        db.session.commit()

        seed_user_financial_profile(new_user)

        flash('Your FinSight account has been registered successfully! You may now sign in.', 'success')
        return redirect(url_for('login'))

    return render_template(
        'register.html',
        fullname='',
        email='',
        role='user',
        business_name='',
        country='India',
        currency='INR',
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
    flash('You have been securely logged out of FinSight.', 'success')
    return redirect(url_for('login'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_seed_demo_accounts()
        print(" * FinSight Platform Initialized (Multi-Currency & Multi-Month Seeded).")
    app.run(debug=True, port=5000)
