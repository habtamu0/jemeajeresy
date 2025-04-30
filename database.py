from flask import Flask, render_template, flash, redirect, url_for, request, g, session
import sqlite3
import random
from datetime import datetime, timedelta
from functools import wraps
import logging
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

# Initialize Flask app
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# Configuration
DATABASE = 'database.db'
REGISTRATION_DEADLINE = datetime(2025, 6, 30, 23, 59, 59)
MIN_PLAYERS_FOR_ASSIGNMENT = 5
MAX_JERSEY_NUMBER = 99

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('jersey_assignment.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Database connection management
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row  # Return rows as dictionaries
    return db


def close_db(e=None):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        # Create players table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            preferred1 INTEGER CHECK(preferred1 BETWEEN 1 AND ?),
            preferred2 INTEGER CHECK(preferred2 BETWEEN 1 AND ?),
            preferred3 INTEGER CHECK(preferred3 BETWEEN 1 AND ?),
            assigned INTEGER CHECK(assigned BETWEEN 1 AND ?),
            registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(phone),
            UNIQUE(email)
        )
        ''', (MAX_JERSEY_NUMBER, MAX_JERSEY_NUMBER, MAX_JERSEY_NUMBER, MAX_JERSEY_NUMBER))

        # Create admin users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_superadmin BOOLEAN DEFAULT 0
        )
        ''')

        # Create audit log table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details TEXT,
            user_id INTEGER,
            ip_address TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        db.commit()


# Decorators
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Admin access required', 'danger')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)

    return decorated_function


# Helper functions
def log_audit(action, details=None, user_id=None):
    try:
        ip_address = request.remote_addr
        db = get_db()
        db.execute(
            'INSERT INTO audit_log (action, details, user_id, ip_address) VALUES (?, ?, ?, ?)',
            (action, details, user_id, ip_address)
        )
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log audit: {str(e)}")


def get_available_numbers():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT assigned FROM players WHERE assigned IS NOT NULL')
    taken_numbers = {row['assigned'] for row in cursor.fetchall()}
    return [num for num in range(1, MAX_JERSEY_NUMBER + 1) if num not in taken_numbers]


def get_assigned_numbers():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT name, assigned FROM players WHERE assigned IS NOT NULL ORDER BY assigned')
    return cursor.fetchall()


def validate_preferences(prefs):
    # Ensure all preferences are unique and valid numbers
    unique_prefs = set()
    for p in prefs:
        if not p:
            continue
        try:
            num = int(p)
            if num < 1 or num > MAX_JERSEY_NUMBER:
                raise ValueError(f"Number must be between 1 and {MAX_JERSEY_NUMBER}")
            if num in unique_prefs:
                raise ValueError("Duplicate preferred numbers")
            unique_prefs.add(num)
        except ValueError as e:
            raise ValueError(f"Invalid jersey number: {str(e)}")
    return True


# Routes
@app.route('/')
def index():
    try:
        db = get_db()
        cursor = db.cursor()

        # Get registered players
        cursor.execute('''
            SELECT id, name, 
                   COALESCE(preferred1, '') || 
                   CASE WHEN preferred2 IS NOT NULL THEN ', ' || preferred2 ELSE '' END || 
                   CASE WHEN preferred3 IS NOT NULL THEN ', ' || preferred3 ELSE '' END as preferred_numbers,
                   assigned,
                   CASE WHEN assigned IS NOT NULL THEN 'Assigned: #' || assigned ELSE 'Pending' END as status
            FROM players
            ORDER BY registration_date DESC
        ''')
        players = [dict(row) for row in cursor.fetchall()]

        # Get stats
        total_players = len(players)
        assigned_count = sum(1 for p in players if p['assigned'] is not None)
        available_numbers = get_available_numbers()

        # Check if registration is closed
        registration_closed = datetime.now() > REGISTRATION_DEADLINE

        return render_template(
            'index.html',
            players=players,
            total_players=total_players,
            assigned_count=assigned_count,
            available_numbers_count=len(available_numbers),
            assigned_numbers=get_assigned_numbers(),
            registration_closed=registration_closed,
            registration_deadline=REGISTRATION_DEADLINE.strftime('%Y-%m-%d %H:%M:%S'),
            min_players=MIN_PLAYERS_FOR_ASSIGNMENT
        )
    except Exception as e:
        logger.error(f"Error in index route: {str(e)}")
        flash('An error occurred while loading the page', 'danger')
        return render_template('error.html'), 500


@app.route('/assign', methods=['GET'])
@admin_required
def assign_numbers():
    try:
        db = get_db()
        cursor = db.cursor()

        # Check if registration deadline has passed
        if datetime.now() < REGISTRATION_DEADLINE:
            flash('Cannot assign numbers before registration deadline', 'warning')
            return redirect(url_for('index'))

        # Check minimum player count
        cursor.execute("SELECT COUNT(*) FROM players")
        total_players = cursor.fetchone()[0]
        if total_players < MIN_PLAYERS_FOR_ASSIGNMENT:
            flash(f"Need at least {MIN_PLAYERS_FOR_ASSIGNMENT} players to assign numbers (currently {total_players})",
                  'warning')
            return redirect(url_for('index'))

        # Get all unassigned players with their preferences
        cursor.execute('''
            SELECT id, preferred1, preferred2, preferred3 
            FROM players 
            WHERE assigned IS NULL
        ''')
        unassigned_players = cursor.fetchall()

        # Get currently assigned numbers
        cursor.execute("SELECT assigned FROM players WHERE assigned IS NOT NULL")
        taken_numbers = {row['assigned'] for row in cursor.fetchall()}

        # Phase 1: Assign numbers with no conflicts
        assignments = {}
        number_requests = {}  # Map numbers to list of players requesting them

        for player in unassigned_players:
            prefs = [p for p in [player['preferred1'], player['preferred2'], player['preferred3']] if p is not None]
            for num in prefs:
                number_requests.setdefault(num, []).append(player['id'])

        # Assign numbers with only one request
        for num, reqs in number_requests.items():
            if len(reqs) == 1 and num not in taken_numbers:
                player_id = reqs[0]
                assignments[player_id] = num
                taken_numbers.add(num)

        # Phase 2: Assign remaining players
        remaining_players = [p for p in unassigned_players if p['id'] not in assignments]

        for player in remaining_players:
            # Try preferred numbers first
            prefs = [p for p in [player['preferred1'], player['preferred2'], player['preferred3']]
                     if p is not None and p not in taken_numbers]

            if prefs:
                # Randomly select from available preferences
                selected = random.choice(prefs)
                assignments[player['id']] = selected
                taken_numbers.add(selected)
            else:
                # Assign random available number
                available = [n for n in range(1, MAX_JERSEY_NUMBER + 1) if n not in taken_numbers]
                if not available:
                    flash('No more jersey numbers available!', 'danger')
                    return redirect(url_for('index'))

                selected = random.choice(available)
                assignments[player['id']] = selected
                taken_numbers.add(selected)

        # Update database with assignments
        for player_id, number in assignments.items():
            cursor.execute(
                "UPDATE players SET assigned = ? WHERE id = ?",
                (number, player_id)
            )

        db.commit()
        log_audit('number_assignment', f"Assigned {len(assignments)} jersey numbers")
        flash(f'Successfully assigned {len(assignments)} jersey numbers!', 'success')
        return redirect(url_for('index', assigned=1))

    except Exception as e:
        db.rollback()
        logger.error(f"Error in number assignment: {str(e)}")
        flash('An error occurred during number assignment', 'danger')
        return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if datetime.now() > REGISTRATION_DEADLINE:
        flash('Registration is closed', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            phone = request.form.get('phone', '').strip()
            email = request.form.get('email', '').strip().lower()
            prefs = [
                request.form.get('preferred1'),
                request.form.get('preferred2'),
                request.form.get('preferred3')
            ]

            # Validation
            if not name or len(name) < 2:
                flash('Please enter a valid name', 'danger')
                return redirect(url_for('register'))

            if not phone or len(phone) < 7:
                flash('Please enter a valid phone number', 'danger')
                return redirect(url_for('register'))

            if email and '@' not in email:
                flash('Please enter a valid email address', 'danger')
                return redirect(url_for('register'))

            try:
                validate_preferences(prefs)
            except ValueError as e:
                flash(str(e), 'danger')
                return redirect(url_for('register'))

            # Check for existing registration
            db = get_db()
            cursor = db.cursor()

            if email:
                cursor.execute("SELECT id FROM players WHERE email = ?", (email,))
                if cursor.fetchone():
                    flash('This email is already registered', 'danger')
                    return redirect(url_for('register'))

            cursor.execute("SELECT id FROM players WHERE phone = ?", (phone,))
            if cursor.fetchone():
                flash('This phone number is already registered', 'danger')
                return redirect(url_for('register'))

            # Insert new player
            cursor.execute('''
                INSERT INTO players (name, phone, email, preferred1, preferred2, preferred3)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, phone, email or None, prefs[0], prefs[1], prefs[2]))

            db.commit()
            log_audit('player_registration', f"New player: {name}", cursor.lastrowid)
            flash('Registration successful!', 'success')
            return redirect(url_for('index'))

        except sqlite3.IntegrityError as e:
            db.rollback()
            logger.error(f"Registration integrity error: {str(e)}")
            flash('Registration failed - possible duplicate entry', 'danger')
            return redirect(url_for('register'))

        except Exception as e:
            db.rollback()
            logger.error(f"Registration error: {str(e)}")
            flash('An error occurred during registration', 'danger')
            return redirect(url_for('register'))

    # GET request - show registration form
    available_numbers = get_available_numbers()
    return render_template(
        'register.html',
        available_numbers=available_numbers,
        max_jersey_number=MAX_JERSEY_NUMBER
    )


# Admin routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM admin_users WHERE username = ?", (username,))
        admin = cursor.fetchone()

        if admin and check_password_hash(admin['password_hash'], password):
            session['admin_logged_in'] = True
            session['admin_username'] = username
            session['is_superadmin'] = bool(admin['is_superadmin'])
            log_audit('admin_login', f"Admin {username} logged in")
            flash('Login successful', 'success')
            return redirect(url_for('admin_dashboard'))

        flash('Invalid credentials', 'danger')
        return redirect(url_for('admin_login'))

    return render_template('admin/login.html')


@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    db = get_db()
    cursor = db.cursor()

    # Get stats
    cursor.execute("SELECT COUNT(*) FROM players")
    total_players = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM players WHERE assigned IS NOT NULL")
    assigned_players = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM players WHERE assigned IS NULL")
    unassigned_players = cursor.fetchone()[0]

    # Get recent activity
    cursor.execute('''
        SELECT action, details, timestamp, ip_address 
        FROM audit_log 
        ORDER BY timestamp DESC 
        LIMIT 10
    ''')
    recent_activity = cursor.fetchall()

    return render_template(
        'admin/dashboard.html',
        total_players=total_players,
        assigned_players=assigned_players,
        unassigned_players=unassigned_players,
        recent_activity=recent_activity,
        registration_deadline=REGISTRATION_DEADLINE,
        now=datetime.now()
    )


@app.route('/admin/players')
@admin_required
def admin_players():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        SELECT id, name, phone, email, 
               preferred1, preferred2, preferred3, assigned,
               registration_date
        FROM players
        ORDER BY registration_date DESC
    ''')
    players = cursor.fetchall()
    return render_template('admin/players.html', players=players)


@app.route('/admin/logout')
def admin_logout():
    username = session.get('admin_username')
    session.clear()
    log_audit('admin_logout', f"Admin {username} logged out")
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))


# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', error="Page not found"), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('error.html', error="Internal server error"), 500


# Application setup
app.teardown_appcontext(close_db)

if __name__ == '__main__':
    init_db()

    # Create initial admin user if none exists
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM admin_users")
        if cursor.fetchone()[0] == 0:
            password_hash = generate_password_hash('admin123')
            cursor.execute(
                "INSERT INTO admin_users (username, password_hash, is_superadmin) VALUES (?, ?, ?)",
                ('admin', password_hash, 1)
            )
            db.commit()
            logger.info("Created default admin user: admin/admin123")

    app.run(debug=True)
