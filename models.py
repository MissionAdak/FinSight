from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id                    = db.Column(db.Integer, primary_key=True)
    fullname              = db.Column(db.String(120), nullable=False)
    email                 = db.Column(db.String(150), unique=True, nullable=False)
    password              = db.Column(db.String(256), nullable=False)
    role                  = db.Column(db.String(50), nullable=False, default='user')
    business_name         = db.Column(db.String(150), nullable=True)
    
    age                   = db.Column(db.Integer, nullable=True)
    phone                 = db.Column(db.String(30), nullable=True)
    address               = db.Column(db.String(300), nullable=True)
    total_income          = db.Column(db.Float, nullable=True, default=0.0)

    country               = db.Column(db.String(100), default='India')
    currency              = db.Column(db.String(10), default='INR')
    theme                 = db.Column(db.String(10), default='light')
    income_sources        = db.Column(db.String(255), nullable=True)
    financial_preferences = db.Column(db.String(255), nullable=True)

    created_at            = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    transactions          = db.relationship('Transaction', backref='user', cascade="all, delete-orphan", lazy=True)
    budgets               = db.relationship('BudgetCategory', backref='user', cascade="all, delete-orphan", lazy=True)
    accounts              = db.relationship('Account', backref='user', cascade="all, delete-orphan", lazy=True)

    @property
    def role_title(self):
        titles = {
            'admin': 'Platform Administrator',
            'shop_owner': 'Shop Owner & Merchant',
            'user': 'Financial Analyst / User'
        }
        return titles.get(self.role, 'Standard User')

    @property
    def role_badge_class(self):
        badges = {
            'admin': 'badge-role-admin',
            'shop_owner': 'badge-role-shop',
            'user': 'badge-role-user'
        }
        return badges.get(self.role, 'badge-role-user')

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_shop_owner(self):
        return self.role == 'shop_owner'

    def __repr__(self):
        return f'<User {self.email} ({self.role})>'


class Account(db.Model):
    __tablename__ = 'accounts'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name         = db.Column(db.String(100), nullable=False)
    account_type = db.Column(db.String(50), default='Bank')
    balance      = db.Column(db.Float, default=0.0)

    transactions = db.relationship('Transaction', backref='account', lazy=True)

    def __repr__(self):
        return f'<Account {self.name} ({self.account_type}): {self.balance}>'


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    account_id   = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    title        = db.Column(db.String(150), nullable=False)
    category     = db.Column(db.String(80), nullable=False)
    amount       = db.Column(db.Float, nullable=False)
    txn_type     = db.Column(db.String(20), nullable=False)
    payment_mode = db.Column(db.String(50), default='UPI')
    date         = db.Column(db.String(50), nullable=False)
    status       = db.Column(db.String(30), default='Completed')
    notes        = db.Column(db.String(250), nullable=True)

    def __repr__(self):
        return f'<Transaction {self.title} {self.amount}>'


class BudgetCategory(db.Model):
    __tablename__ = 'budget_categories'

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name            = db.Column(db.String(100), nullable=False)
    allocated       = db.Column(db.Float, nullable=False)
    spent           = db.Column(db.Float, nullable=False, default=0.0)
    period          = db.Column(db.String(20), default='Monthly')
    alert_threshold = db.Column(db.Integer, default=80)

    @property
    def percentage(self):
        if self.allocated <= 0:
            return 0
        return round((self.spent / self.allocated) * 100, 1)

    @property
    def remaining(self):
        return round(self.allocated - self.spent, 2)

    @property
    def status(self):
        pct = (self.spent / self.allocated * 100) if self.allocated > 0 else 0
        if pct > 100:
            return 'Over Budget'
        elif pct >= self.alert_threshold:
            return 'Near Limit'
        return 'Healthy'

    @property
    def status_class(self):
        pct = (self.spent / self.allocated * 100) if self.allocated > 0 else 0
        if pct > 100:
            return 'status-danger'
        elif pct >= self.alert_threshold:
            return 'status-warning'
        return 'status-success'

    @property
    def is_alert(self):
        pct = (self.spent / self.allocated * 100) if self.allocated > 0 else 0
        return pct >= self.alert_threshold

    def __repr__(self):
        return f'<BudgetCategory {self.name}: {self.spent}/{self.allocated}>'
