import os
import sys
import re
from app import app, db, init_seed_demo_accounts
from models import User, Investment, PortfolioHistory, Goal, GoalTransaction, Account, Transaction

def test_fintech_platform():
    with app.app_context():
        db.create_all()
        init_seed_demo_accounts()

        admin = User.query.filter_by(email='admin@finance.com').first()
        assert admin is not None
        assert len(admin.investments) >= 6
        assert len(admin.goals) >= 4
        assert len(admin.portfolio_history) >= 6

        user = User.query.filter_by(email='user@personal.com').first()
        assert user is not None
        assert user.currency == 'USD'
        assert len(user.investments) >= 6
        assert len(user.goals) >= 4

    with app.test_client() as client:
        resp = client.get('/login')
        assert resp.status_code == 200
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.get_data(as_text=True))
        assert match is not None
        csrf_token = match.group(1)

        login_resp = client.post('/login', data={
            'csrf_token': csrf_token,
            'email': 'user@personal.com',
            'password': 'user123',
            'role': 'user'
        }, follow_redirects=True)
        assert login_resp.status_code == 200
        assert 'Elena Rostova' in login_resp.get_data(as_text=True)

        inv_resp = client.get('/investments')
        assert inv_resp.status_code == 200
        inv_html = inv_resp.get_data(as_text=True)
        assert '$' in inv_html
        assert 'Total Portfolio Value' in inv_html

        for tab in ['holdings', 'transactions', 'allocation', 'performance']:
            r = client.get(f'/investments?tab={tab}')
            assert r.status_code == 200
            assert '$' in r.get_data(as_text=True)

        csv_resp = client.get('/export/investments-csv')
        assert csv_resp.status_code == 200
        assert 'text/csv' in csv_resp.content_type

        goals_resp = client.get('/goals')
        assert goals_resp.status_code == 200
        goals_html = goals_resp.get_data(as_text=True)
        assert 'Active Goals' in goals_html
        assert '$' in goals_html

        for route in ['/dashboard', '/expenses', '/income', '/budgets', '/accounts', '/categories', '/reports', '/settings']:
            r = client.get(route)
            assert r.status_code == 200

if __name__ == '__main__':
    test_fintech_platform()
    print("ALL TESTS PASSED")
