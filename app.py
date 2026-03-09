import pymysql
pymysql.install_as_MySQLdb()
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
from flask_cors import CORS
from flask_mysqldb import MySQL
from MySQLdb.cursors import DictCursor
import os
import time
import random
import string
import smtplib
import csv
import io
import html
from email.message import EmailMessage


def load_env_file(env_path='.env'):
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


# Load .env from project folder reliably (independent of current working dir)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_env_file(os.path.join(BASE_DIR, '.env'))
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)


app.config['MYSQL_HOST'] = os.getenv("mysql.railway.internal")
app.config['MYSQL_USER'] = os.getenv("root")
app.config['MYSQL_PASSWORD'] = os.getenv("PcUXlJhHUounEufrtkuUoQXHItLKEYIt")
app.config['MYSQL_DB'] = os.getenv("railway")
app.config['MYSQL_PORT'] = int(os.getenv("MYSQLPORT", 3306))

mysql = MySQL(app)

@app.route('/')
def home():
    return redirect(url_for('login'))

# -------------------------
# CONFIG
# -------------------------
app.secret_key = os.getenv('FLASK_SECRET', 'shahi_secret_key')

def get_db():
    return mysql.connection


def generate_login_captcha(length=5):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def generate_otp(length=6):
    return ''.join(random.choice(string.digits) for _ in range(length))


def send_otp_email(to_email, otp_code):
    smtp_host = (os.getenv('SMTP_HOST') or '').strip()
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = (os.getenv('SMTP_USER') or '').strip()
    smtp_pass = (os.getenv('SMTP_PASS') or '').strip()
    # Google App Password often copied with spaces every 4 chars.
    smtp_pass = smtp_pass.replace(' ', '')
    smtp_from = os.getenv('SMTP_FROM', smtp_user or '')
    smtp_use_tls = os.getenv('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes')

    missing = []
    if not smtp_host:
        missing.append('SMTP_HOST')
    if not smtp_user:
        missing.append('SMTP_USER')
    if not smtp_pass:
        missing.append('SMTP_PASS')
    if missing:
        return False, "Email service not configured. Missing: " + ", ".join(missing)

    msg = EmailMessage()
    msg['Subject'] = 'Shahi Mutton Khanawal - Password Reset OTP'
    msg['From'] = smtp_from
    msg['To'] = to_email
    msg.set_content(
        f"Your OTP for password reset is: {otp_code}\n"
        f"This OTP will expire in 5 minutes."
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            if smtp_use_tls:
                server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True, None
    except Exception as e:
        err_text = str(e)
        if smtp_host.lower() == 'smtp.gmail.com' and '535' in err_text:
            return False, (
                "Gmail rejected login (535). Use Google App Password (16 chars), "
                "not your normal Gmail password. Also ensure 2-Step Verification is ON."
            )
        return False, f"Failed to send OTP email: {e}"


def users_has_email_column():
    try:
        cur = mysql.connection.cursor(DictCursor)
        cur.execute("SHOW COLUMNS FROM users LIKE 'email'")
        row = cur.fetchone()
        cur.close()
        return bool(row)
    except Exception:
        return False

#--------------------
#  Menu connection
#--------------------
def fetch_all_menu():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, item_name, category, price FROM menu")
    rows = cur.fetchall()

    items = []
    for r in rows:
        items.append({
            "id": r[0],
            "item_name": r[1],
            "category": r[2],
            "price": float(r[3])
        })

    cur.close()
    return items



# -------------------------
# LOGIN / LOGOUT
# -------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'login_captcha' not in session:
        session['login_captcha'] = generate_login_captcha()
    success_msg = request.args.get('success')

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        captcha_input = (request.form.get('captcha') or '').strip().upper()
        expected_captcha = (session.get('login_captcha') or '').upper()

        if captcha_input != expected_captcha:
            session['login_captcha'] = generate_login_captcha()
            return render_template(
                'login.html',
                error="Invalid captcha",
                captcha_code=session['login_captcha'],
                username=username
            )

        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT * FROM users WHERE username=%s AND password=%s",
            (username, password)
        )
        user = cur.fetchone()
        cur.close()

        if user:
            session['user'] = username
            session.pop('login_captcha', None)
            return redirect(url_for('dashboard'))
        else:
            session['login_captcha'] = generate_login_captcha()
            return render_template(
                'login.html',
                error="Invalid credentials",
                captcha_code=session['login_captcha'],
                username=username
            )

    session['login_captcha'] = generate_login_captcha()
    return render_template(
        'login.html',
        captcha_code=session['login_captcha'],
        success=success_msg
    )


@app.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template('forgot.html', step='email')

    action = request.form.get('action', 'send_otp')

    if action == 'send_otp':
        email = (request.form.get('email') or '').strip().lower()
        if not email:
            return render_template(
                'forgot.html',
                step='email',
                error='Please enter your email address.'
            )

        if not users_has_email_column():
            return render_template(
                'forgot.html',
                step='email',
                email=email,
                error="Database setup missing: 'users.email' column not found. Please add email column first."
            )

        try:
            cur = mysql.connection.cursor(DictCursor)
            cur.execute("SELECT id FROM users WHERE email=%s LIMIT 1", (email,))
            user = cur.fetchone()
            cur.close()
        except Exception as e:
            return render_template(
                'forgot.html',
                step='email',
                error=f'Unable to validate email: {e}'
            )

        if not user:
            return render_template(
                'forgot.html',
                step='email',
                error='Email is not registered.'
            )

        otp_code = generate_otp()
        session['forgot_email'] = email
        session['forgot_otp'] = otp_code
        session['forgot_otp_exp'] = int(time.time()) + 300

        ok, err = send_otp_email(email, otp_code)
        if not ok:
            return render_template(
                'forgot.html',
                step='email',
                email=email,
                error=err
            )

        return render_template(
            'forgot.html',
            step='verify',
            email=email,
            message='OTP sent to your email.'
        )

    if action == 'verify_reset':
        email = (request.form.get('email') or '').strip().lower()
        otp_input = (request.form.get('otp') or '').strip()
        new_password = request.form.get('new_password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not email or not otp_input or not new_password or not confirm_password:
            return render_template(
                'forgot.html',
                step='verify',
                email=email,
                error='All fields are required.'
            )

        if new_password != confirm_password:
            return render_template(
                'forgot.html',
                step='verify',
                email=email,
                error='Passwords do not match.'
            )

        if not users_has_email_column():
            return render_template(
                'forgot.html',
                step='email',
                error="Database setup missing: 'users.email' column not found. Please add email column first."
            )

        session_email = (session.get('forgot_email') or '').lower()
        session_otp = session.get('forgot_otp')
        session_exp = int(session.get('forgot_otp_exp') or 0)

        if email != session_email or otp_input != session_otp:
            return render_template(
                'forgot.html',
                step='verify',
                email=email,
                error='Invalid OTP.'
            )

        if int(time.time()) > session_exp:
            session.pop('forgot_email', None)
            session.pop('forgot_otp', None)
            session.pop('forgot_otp_exp', None)
            return render_template(
                'forgot.html',
                step='email',
                error='OTP expired. Please request a new OTP.'
            )

        try:
            cur = mysql.connection.cursor()
            cur.execute(
                "UPDATE users SET password=%s WHERE email=%s",
                (new_password, email)
            )
            mysql.connection.commit()
            cur.close()
        except Exception as e:
            return render_template(
                'forgot.html',
                step='verify',
                email=email,
                error=f'Unable to reset password: {e}'
            )

        session.pop('forgot_email', None)
        session.pop('forgot_otp', None)
        session.pop('forgot_otp_exp', None)
        return redirect(url_for('login', success='Password reset successful. Please login.'))

    return render_template(
        'forgot.html',
        step='email',
        error='Invalid request.'
    )



@app.route('/logout')
def logout():
    session.pop('user', None)   # session remove karega
    return redirect(url_for('login'))


# -------------------------
# DASHBOARD PAGE
# -------------------------
@app.route('/dashboard')
def dashboard():

    # 🔐 SECURE CODE (login check)
    if 'user' not in session:
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT SUM(amount)
        FROM billing
        WHERE status = 'Paid'
    """)

    result = cur.fetchone()
    cur.close()

    today_revenue = result[0] if result and result[0] else 0

    return render_template(
        'dashboard.html',
        username=session.get('user'),
        today_revenue=today_revenue
    )


@app.route('/today-orders')
def today_orders():
    cur = mysql.connection.cursor(DictCursor)

    cur.execute("""
        SELECT bill_no, table_number, amount, status
        FROM billing
        ORDER BY id DESC
    """)

    data = cur.fetchall()
    cur.close()

    return jsonify(data)


@app.route('/reports/bills.csv')
def export_bills_csv():
    if 'user' not in session:
        return redirect(url_for('login'))

    cur = mysql.connection.cursor(DictCursor)
    cur.execute("""
        SELECT id, bill_no, table_number, amount
        FROM billing
        ORDER BY id ASC
    """)
    rows = cur.fetchall()
    cur.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Bill No', 'Bill Invoice', 'Table Number', 'Bill Amount'])

    for row in rows:
        bill_id = row.get('id') or ''
        bill_no = (row.get('bill_no') or '').strip()
        table_no = row.get('table_number') or ''
        amount = row.get('amount') or 0
        try:
            amount = f"{float(amount):.2f}"
        except Exception:
            amount = "0.00"

        writer.writerow([bill_id, bill_no, table_no, amount])

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': 'attachment; filename=billing_report_till_date.csv'
        }
    )


@app.route('/reports/bills/pdf')
def export_bills_pdf():
    if 'user' not in session:
        return redirect(url_for('login'))

    cur = mysql.connection.cursor(DictCursor)
    cur.execute("""
        SELECT id, bill_no, table_number, amount
        FROM billing
        ORDER BY id ASC
    """)
    rows = cur.fetchall()
    cur.close()

    total_amount = 0.0
    body_rows = []
    for row in rows:
        bill_id = html.escape(str(row.get('id') or ''))
        bill_no = html.escape(str(row.get('bill_no') or '').strip())
        table_no = html.escape(str(row.get('table_number') or ''))
        try:
            amount_num = float(row.get('amount') or 0)
        except Exception:
            amount_num = 0.0
        total_amount += amount_num
        amount_text = f"{amount_num:.2f}"
        body_rows.append(
            f"<tr><td>{bill_id or '-'}</td><td>{bill_no or '-'}</td><td>{table_no or '-'}</td><td>{amount_text}</td></tr>"
        )

    if not body_rows:
        body_rows.append("<tr><td colspan='4'>No billing records found.</td></tr>")

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Till Date Billing Report</title>
  <style>
    body{{font-family:Arial,sans-serif;padding:24px;color:#111}}
    h1{{margin:0 0 4px 0;font-size:24px}}
    .meta{{margin-bottom:16px;color:#555}}
    table{{width:100%;border-collapse:collapse}}
    th,td{{border:1px solid #d1d5db;padding:8px;text-align:left}}
    th{{background:#f3f4f6}}
    tfoot td{{font-weight:700;background:#fafafa}}
  </style>
</head>
<body>
  <h1>Billing Till Date Report</h1>
  <div class="meta">Columns: Bill No, Bill Invoice, Table Number, Bill Amount</div>
  <table>
    <thead>
      <tr>
        <th>Bill No</th>
        <th>Bill Invoice</th>
        <th>Table Number</th>
        <th>Bill Amount</th>
      </tr>
    </thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
    <tfoot>
      <tr>
        <td colspan="3">Total</td>
        <td>{total_amount:.2f}</td>
      </tr>
    </tfoot>
  </table>
  <script>
    window.onload = function() {{
      window.print();
    }};
  </script>
</body>
</html>"""

    return Response(html_doc, mimetype='text/html; charset=utf-8')
#-----------------------------
@app.route("/billing")
def billing():
    if 'user' not in session:
        return redirect(url_for('login'))

    return render_template("billing.html")


#------------------------------



@app.route("/waiter")
def waiter():
    return render_template("waiter.html")

import time
from flask import request, jsonify

@app.route("/api/waiter/order", methods=["POST"])
def waiter_order():
    data = request.get_json()

    table = data.get("table")
    items = data.get("items")
    amount = data.get("amount")

    bill_no = "INV" + str(int(time.time()))

    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO billing
        (bill_no, table_number, items, amount, status)
        VALUES (%s,%s,%s,%s,%s)
    """, (bill_no, table, items, amount, "Pending"))

    # Waiter order aate hi table ko on-dine mark karo (upsert)
    cur.execute("SELECT 1 FROM tables WHERE table_no = %s", (table,))
    exists = cur.fetchone()
    if exists:
        cur.execute(
            "UPDATE tables SET status=%s WHERE table_no=%s",
            ("ondine", table)
        )
    else:
        cur.execute(
            "INSERT INTO tables (table_no, status) VALUES (%s, %s)",
            (table, "ondine")
        )

    mysql.connection.commit()
    cur.close()

    # Dashboard ke format me response
    return jsonify({
        "bill_no": bill_no,
        "table_number": table,
        "amount": amount,
        "status": "Pending"
    })



    # IMPORTANT: dashboard format return karo
    return jsonify({
        "bill_no": bill_no,
        "table_number": table,
        "amount": amount,
        "status": "Pending"
    })

# -------------------------
# MENU PAGE (OPTIONAL)
# -------------------------
@app.route('/menu')
def menu_page():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('menu.html', items=[])


# -------------------------
# ✅ API: MENU FETCH (FOR BILLING)
# -------------------------
@app.route('/api/items', methods=['GET'])
def api_items():
    try:
        items = fetch_all_menu()
        return jsonify(items), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# -------------------------
# ✅ ✅ ✅ API: GET PENDING BILL BY TABLE
@app.route('/api/billing/pending/<int:table_no>', methods=['GET'])
def get_pending_bill(table_no):
    try:
        cur = mysql.connection.cursor(DictCursor)

        cur.execute("""
            SELECT items, status
            FROM billing
            WHERE table_number=%s
            ORDER BY id DESC
            LIMIT 1
        """, (table_no,))

        row = cur.fetchone()
        cur.close()

        # ⭐ IMPORTANT LOGIC
        if row and row["status"].lower() == "pending":
            return jsonify({
                "items": row["items"],
                "status": row["status"]
            }), 200

        # Paid ya koi aur status ho → empty bhejo
        return jsonify({"items": None}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# -------------------------
# ✅ PAY BILL + TABLE AUTO FREE
# -------------------------
@app.route('/api/billing/pay/<bill_no>', methods=['POST'])
def pay_bill(bill_no):
    try:
        cur = mysql.connection.cursor(DictCursor)

        # bill ka table number nikaalo
        cur.execute(
            "SELECT table_number FROM billing WHERE bill_no=%s ORDER BY id DESC LIMIT 1",
            (bill_no,)
        )
        row = cur.fetchone()

        if not row:
            return jsonify({"error": "Bill not found"}), 404

        table_number = row["table_number"]

        # billing status = Paid
        cur.execute(
            "UPDATE billing SET status='Paid' WHERE bill_no=%s",
            (bill_no,)
        )

        # ⭐ table auto free
        cur.execute(
            "UPDATE tables SET status='Free' WHERE table_no=%s",
            (table_number,)
        )

        mysql.connection.commit()
        cur.close()

        return jsonify({"ok": True})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------------------------
# ✅ API: MENU ADD
# -------------------------
@app.route('/api/menu/add', methods=['POST'])
def api_menu_add():
    try:
        data = request.get_json(force=True)

        name = data.get('item_name')
        category = data.get('category', '')
        price = data.get('price', 0)

        if not name or price is None:
            return jsonify({'error': 'Missing item name or price'}), 400

        cur = mysql.connection.cursor(DictCursor)
        cur.execute(
            "INSERT INTO menu (item_name, category, price) VALUES (%s, %s, %s)",
            (name, category, float(price))
        )
        mysql.connection.commit()
        cur.close()

        items = fetch_all_menu()
        return jsonify({'items': items}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# -------------------------
# ✅ API: MENU DELETE
# -------------------------
@app.route('/api/menu/delete', methods=['POST'])
def api_menu_delete():
    try:
        data = request.get_json(force=True)
        item_id = data.get('id')

        if not item_id:
            return jsonify({'error': 'Missing id'}), 400

        cur = mysql.connection.cursor(DictCursor)
        cur.execute("DELETE FROM menu WHERE id = %s", (item_id,))
        mysql.connection.commit()
        cur.close()

        items = fetch_all_menu()
        return jsonify({'items': items}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# -------------------------
# ✅ ✅ ✅ API: BILLING / POS SAVE
# -------------------------
@app.route('/api/billing', methods=['POST'])
def api_billing():
    try:
        data = request.get_json(force=True)

        bill_no = data.get('bill_no') or f"INV{int(time.time())}"
        table_number = data.get('table_number')
        items_text = data.get('items')
        amount = float(data.get('amount', 0) or 0)
        status = data.get('status', 'Pending')

        cur = mysql.connection.cursor(DictCursor)
        cur.execute(
            "INSERT INTO billing (bill_no, table_number, items, amount, status) VALUES (%s, %s, %s, %s, %s)",
            (bill_no, table_number, items_text, amount, status)
        )
        mysql.connection.commit()

        cur.execute("SELECT * FROM billing ORDER BY id DESC")
        saved = cur.fetchone()
        cur.close()

        if saved and saved.get('amount') is not None:
            try:
                saved['amount'] = float(saved['amount'])
            except:
                pass

        return jsonify({'ok': True, 'data': saved}), 200

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
   
   
    fetch('/api/billing/pay/' + bill_no, {
    method: "POST"
});

# -------------------------
# ✅ API: TABLE STATUS
# -------------------------
@app.route('/api/tables', methods=['GET'])
def api_tables():
    try:
        cur = mysql.connection.cursor(DictCursor)
        cur.execute("SELECT table_no, status FROM tables ORDER BY table_no ASC")
        rows = cur.fetchall()
        cur.close()
        return jsonify(rows), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

@app.route('/api/tables/<int:table_no>', methods=['POST'])
def api_tables_update(table_no):
    try:
        data = request.get_json(force=True)
        status = data.get('status')

        if status is None:
            return jsonify({'error': 'Missing status'}), 400

        cur = mysql.connection.cursor(DictCursor)
        cur.execute("SELECT 1 FROM tables WHERE table_no = %s", (table_no,))
        exists = cur.fetchone()

        if exists:
            cur.execute(
                "UPDATE tables SET status = %s WHERE table_no = %s",
                (status, table_no)
            )
        else:
            cur.execute(
                "INSERT INTO tables (table_no, status) VALUES (%s, %s)",
                (table_no, status)
            )

        mysql.connection.commit()
        cur.close()
        return jsonify({'ok': True}), 200

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# -------------------------
# HEALTH CHECK
# -------------------------
@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

# -------------------------
# RUN SERVER
# -------------------------
import os

port = int(os.environ.get("PORT", 5000))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port, debug=True)

