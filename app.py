import pymysql
pymysql.install_as_MySQLdb()
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_cors import CORS
from flask_mysqldb import MySQL
import os
import time
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)
app.secret_key = "shahi_secret_123"

app.config['MYSQL_HOST'] = 'sql12.freesqldatabase.com'
app.config['MYSQL_USER'] = 'sql12816099'
app.config['MYSQL_PASSWORD'] = '6VWzxBYCs4'
app.config['MYSQL_DB'] = 'sql12816099'

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
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT * FROM users WHERE username=%s AND password=%s",
            (username, password)
        )
        user = cur.fetchone()
        cur.close()

        if user:
            session['user'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid credentials")

    return render_template('login.html')


# -------------------------
# DASHBOARD PAGE
# -------------------------
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', username=session.get('user'))


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
# -------------------------
@app.route('/api/billing/pending/<int:table_no>', methods=['GET'])
def get_pending_bill(table_no):
    try:
        cur = mysql.connection.cursor(dictionary=True)

        cur.execute("""
            SELECT items, status 
            FROM billing
            WHERE table_number = %s AND status = 'Pending'
            ORDER BY id DESC
            LIMIT 1
        """, (table_no,))

        row = cur.fetchone()
        cur.close()

        if row:
            return jsonify({
                "items": row["items"],
                "status": row["status"]
            }), 200

        return jsonify({"items": None}), 200

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

        cur = mysql.connection.cursor(dictionary=True)
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

        cur = mysql.connection.cursor(dictionary=True)
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

        cur = mysql.connection.cursor(dictionary=True)
        cur.execute(
            "INSERT INTO billing (bill_no, table_number, items, amount, status) VALUES (%s, %s, %s, %s, %s)",
            (bill_no, table_number, items_text, amount, status)
        )
        mysql.connection.commit()

        cur.execute("SELECT * FROM billing WHERE id = LAST_INSERT_ID()")
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

# -------------------------
# ✅ ✅ ✅ API: TABLE STATUS
# -------------------------
@app.route('/api/tables', methods=['GET'])
def api_tables():
    try:
        cur = mysql.connection.cursor(dictionary=True)
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

        cur = mysql.connection.cursor(dictionary=True)
        cur.execute("SELECT 1 FROM tables WHERE table_no = %s", (table_no,))
        exists = cur.fetchone()

        if exists:
            cur.execute("UPDATE tables SET status = %s WHERE table_no = %s", (status, table_no))
        else:
            cur.execute("INSERT INTO tables (table_no, status) VALUES (%s, %s)", (table_no, status))

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
    app.run(host="0.0.0.0", port=port)

