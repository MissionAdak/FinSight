from datetime import datetime, timezone
from typing import Any
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

CASCADE_ALL_DELETE_ORPHAN = 'all, delete-orphan'
USERS_ID_FK = 'users.id'


class BaseModel(db.Model):
    __abstract__ = True

    def __init__(self, **kwargs: Any) -> None:
        cls_ = type(self)
        for key, value in kwargs.items():
            if not hasattr(cls_, key):
                raise TypeError(f'{key!r} is an invalid keyword argument for {cls_.__name__}')
            setattr(self, key, value)


class User(UserMixin, BaseModel):
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

    transactions          = db.relationship('Transaction', backref='user', cascade=CASCADE_ALL_DELETE_ORPHAN, lazy=True)
    budgets               = db.relationship('BudgetCategory', backref='user', cascade=CASCADE_ALL_DELETE_ORPHAN, lazy=True)
    accounts              = db.relationship('Account', backref='user', cascade=CASCADE_ALL_DELETE_ORPHAN, lazy=True)
    investments           = db.relationship('Investment', backref='user', cascade=CASCADE_ALL_DELETE_ORPHAN, lazy=True)
    portfolio_history     = db.relationship('PortfolioHistory', backref='user', cascade=CASCADE_ALL_DELETE_ORPHAN, lazy=True)
    goals                 = db.relationship('Goal', backref='user', cascade=CASCADE_ALL_DELETE_ORPHAN, lazy=True)

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


class Account(BaseModel):
    __tablename__ = 'accounts'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey(USERS_ID_FK), nullable=False)
    name         = db.Column(db.String(100), nullable=False)
    account_type = db.Column(db.String(50), default='Bank')
    balance      = db.Column(db.Float, default=0.0)

    transactions = db.relationship('Transaction', backref='account', lazy=True)

    def __repr__(self):
        return f'<Account {self.name} ({self.account_type}): {self.balance}>'


class Transaction(BaseModel):
    __tablename__ = 'transactions'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey(USERS_ID_FK), nullable=False)
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


class BudgetCategory(BaseModel):
    __tablename__ = 'budget_categories'

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey(USERS_ID_FK), nullable=False)
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


class Investment(BaseModel):
    __tablename__ = 'investments'

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey(USERS_ID_FK), nullable=False)
    asset_name     = db.Column(db.String(150), nullable=False)
    ticker         = db.Column(db.String(30), nullable=True)
    asset_type     = db.Column(db.String(40), nullable=False)
    quantity       = db.Column(db.Float, nullable=False, default=1.0)
    purchase_price = db.Column(db.Float, nullable=False)
    current_price  = db.Column(db.Float, nullable=False)
    day_change_pct = db.Column(db.Float, default=0.0)
    purchase_date  = db.Column(db.String(50), nullable=False)
    notes          = db.Column(db.String(250), nullable=True)
    created_at     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    history        = db.relationship('PortfolioHistory', backref='investment', passive_deletes=False, lazy=True)

    @property
    def invested_value(self):
        return round(self.quantity * self.purchase_price, 2)

    @property
    def current_value(self):
        return round(self.quantity * self.current_price, 2)

    @property
    def absolute_return(self):
        return round(self.current_value - self.invested_value, 2)

    @property
    def return_pct(self):
        if self.invested_value > 0:
            return round((self.absolute_return / self.invested_value) * 100, 2)
        return 0.0

    @property
    def day_change_value(self):
        return round(self.current_value * ((self.day_change_pct or 0.0) / 100.0), 2)

    def __repr__(self):
        return f'<Investment {self.asset_name} ({self.asset_type}): {self.current_value}>'


class PortfolioHistory(BaseModel):
    __tablename__ = 'portfolio_history'

    id                   = db.Column(db.Integer, primary_key=True)
    user_id              = db.Column(db.Integer, db.ForeignKey(USERS_ID_FK), nullable=False)
    investment_id        = db.Column(db.Integer, db.ForeignKey('investments.id'), nullable=True)
    date                 = db.Column(db.String(50), nullable=False)
    invested_total       = db.Column(db.Float, nullable=False)
    portfolio_value      = db.Column(db.Float, nullable=False)
    portfolio_return_pct = db.Column(db.Float, default=0.0)
    benchmark_return_pct = db.Column(db.Float, default=0.0)
    created_at           = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<PortfolioHistory {self.date}: Val {self.portfolio_value}>'


class Goal(BaseModel):
    __tablename__ = 'goals'

    id                   = db.Column(db.Integer, primary_key=True)
    user_id              = db.Column(db.Integer, db.ForeignKey(USERS_ID_FK), nullable=False)
    goal_name            = db.Column(db.String(150), nullable=False)
    goal_type            = db.Column(db.String(50), nullable=False)
    target_amount        = db.Column(db.Float, nullable=False)
    current_amount       = db.Column(db.Float, nullable=False, default=0.0)
    target_date          = db.Column(db.String(50), nullable=False)
    expected_return_rate = db.Column(db.Float, default=10.0)
    status               = db.Column(db.String(30), default='On Track')
    created_at           = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at           = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    contributions        = db.relationship('GoalTransaction', backref='goal', cascade=CASCADE_ALL_DELETE_ORPHAN, lazy=True)

    @property
    def progress_pct(self):
        curr = self.current_amount or 0.0
        tgt = self.target_amount or 0.0
        if tgt > 0:
            return min(round((curr / tgt) * 100, 1), 100.0)
        return 0.0

    @property
    def remaining_amount(self):
        curr = self.current_amount or 0.0
        tgt = self.target_amount or 0.0
        return max(round(tgt - curr, 2), 0.0)

    @property
    def months_remaining(self):
        try:
            t_date = datetime.strptime(self.target_date, '%Y-%m-%d').date()
            today = datetime.now(timezone.utc).date()
            months = (t_date.year - today.year) * 12 + (t_date.month - today.month)
            return max(months, 1)
        except Exception:
            return 1

    @property
    def time_left_label(self):
        if (self.current_amount or 0.0) >= (self.target_amount or 0.0):
            return 'Target Reached'
        m = self.months_remaining
        if m >= 12:
            if m == 12:
                return '1 yr left'
            yrs = round(m / 12, 1)
            return f'{yrs} yrs left'
        return f'{m} mos left' if m != 1 else '1 mo left'

    @property
    def recommended_monthly_saving(self):
        if (self.current_amount or 0.0) >= (self.target_amount or 0.0):
            return 0.0
        m = self.months_remaining
        r = (self.expected_return_rate or 10.0) / 100.0 / 12.0
        rem = self.remaining_amount
        if r > 0 and m > 1:
            try:
                fv_factor = ((1 + r) ** m - 1) / r
                if fv_factor > 0:
                    return round(rem / fv_factor, 2)
            except Exception:
                pass
        return round(rem / max(m, 1), 2)

    @property
    def projected_value(self):
        m = self.months_remaining
        r = (self.expected_return_rate or 10.0) / 100.0 / 12.0
        pmt = self.recommended_monthly_saving
        curr = self.current_amount or 0.0
        try:
            pv = curr * ((1 + r) ** m)
            if r > 0 and pmt > 0:
                pv += pmt * (((1 + r) ** m - 1) / r)
            return round(pv, 2)
        except Exception:
            return round(self.target_amount or 0.0, 2)

    @property
    def computed_status(self):
        if (self.current_amount or 0.0) >= (self.target_amount or 0.0):
            return 'Completed'
        try:
            t_date = datetime.strptime(self.target_date, '%Y-%m-%d').date()
            today = datetime.now(timezone.utc).date()
            if today > t_date:
                return 'At Risk'
            c_date = self.created_at.date() if self.created_at else today
            total_days = max((t_date - c_date).days, 1)
            elapsed_days = max((today - c_date).days, 0)
            expected_pct = (elapsed_days / total_days) * 100
            actual_pct = self.progress_pct
            if expected_pct - actual_pct > 20:
                return 'At Risk'
        except Exception:
            pass
        return 'On Track'

    def __repr__(self):
        return f'<Goal {self.goal_name}: {self.current_amount}/{self.target_amount}>'


class GoalTransaction(BaseModel):
    __tablename__ = 'goal_transactions'

    id             = db.Column(db.Integer, primary_key=True)
    goal_id        = db.Column(db.Integer, db.ForeignKey('goals.id'), nullable=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    amount         = db.Column(db.Float, nullable=False)
    date           = db.Column(db.String(50), nullable=False)
    notes          = db.Column(db.String(250), nullable=True)
    created_at     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<GoalTransaction Goal {self.goal_id}: {self.amount}>'
