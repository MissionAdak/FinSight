# Finance Analytics Platform for Financial Reporting and Budget Tracking

Enterprise and retail financial analytics web application built with Python (Flask) and SQLite, denominated in Indian Rupees (INR).

## Features

- Role-enforced authentication: Standard User, Shop Owner & Merchant, Platform Administrator
- Registration validation: RFC 5322 email checking, Indian 10-digit mobile number format (+91), age, address, and annual income
- Financial telemetry: 4 KPI indicators, 6-month visual cashflow trajectory, and P&L income statement
- Dynamic budget tracking: Departmental spending caps, burn rate meters, and variance telemetry
- Double-submit CSRF token validation on all form submissions
- Brute-force protection: Automated 60-second lockout after 5 consecutive failed sign-in attempts
- Cryptographically signed self-service password reset workflow with timed HMAC tokens

## Project Structure

- `app.py`: Flask application routes, session security, CSRF protection, and financial calculations
- `models.py`: SQLAlchemy database models (User, Transaction, BudgetCategory)
- `requirements.txt`: Python package dependencies
- `templates/`: Jinja2 templates
  - `base.html`: Common layout and font typography
  - `login.html`: Role-enforced sign in interface
  - `register.html`: Registration form with contact and income fields
  - `dashboard.html`: Financial reporting and budget tracking portal
  - `forgot_password.html`: Password reset request interface
  - `reset_password.html`: New password submission form
- `static/style.css`: Corporate fintech stylesheet (White primary, Blue and Orange accents)

## Installation & Setup

1. Create and activate a Python virtual environment:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python app.py
   ```

4. Open the application in your browser:
   ```
   http://127.0.0.1:5000
   ```

## Default Test Accounts

- Standard User: `user@personal.com` / `user123`
- Shop Owner: `shop@metrostore.com` / `shop123`
- Administrator: `admin@finance.com` / `admin123`
