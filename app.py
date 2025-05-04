from flask import Flask, render_template, flash, redirect, url_for, request
import sqlite3

app = Flask(__name__)
app.secret_key = 'jemeajereseysecret!'


DATABASE = 'database.db'

def get_registered_players():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, preferred1, preferred2, preferred3, assigned FROM players")
    rows = cursor.fetchall()
    conn.close()

    players = []
    assigned_numbers = []
    
    for row in rows:
        player_id, name, p1, p2, p3, assigned = row
        preferred = [p for p in [p1, p2, p3] if p is not None]
        preferred_display = ', '.join(map(str, preferred))
        
        # Build status information
        if assigned:
            assigned_numbers.append(assigned)
            prefs = {p1, p2, p3}
            if assigned in prefs:
                status = f"Assigned: #{assigned}"
                status_class = "status-assigned"
            else:
                status = f"Assigned: #{assigned} (Not preferred)"
                status_class = "status-unlucky"
        else:
            status = "Pending"
            status_class = "status-pending"
        
        players.append({
            'id': player_id,
            'name': name,
            'preferred_numbers': preferred_display,
            'preferred_list': preferred,  # Keep as list for processing
            'assigned': assigned,
            'assigned_number': assigned,
            'status': status,
            'status_class': status_class
        })
    
    return {
        'players': players,
        'assigned_numbers': assigned_numbers
    }

@app.route('/')
def index():
    # Get registered players data
    data = get_registered_players()
    players = data['players']
    assigned_numbers = data['assigned_numbers']
    assigned_players = [p for p in players if p.get('assigned')]

    # Check if assignment has already been done
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT assigned FROM assignment_status WHERE id = 1")
        result = cursor.fetchone()
        assignment_done = bool(result[0]) if result else False
    except Exception as e:
        print(f"Error checking assignment status: {e}")
        assignment_done = False
    finally:
        conn.close()

    return render_template('index.html',
                           players=players,
                           assigned_numbers=assigned_numbers,
                           assigned_players=assigned_players,
                           current_user_numbers=[],
                           progress_percent=(len(players)/32*100),
                           assignment_done=assignment_done)

import sqlite3

conn = sqlite3.connect('database.db')
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    preferred1 INTEGER,
    preferred2 INTEGER,
    preferred3 INTEGER,
    assigned INTEGER
)
''')

conn.commit()
conn.close()

import random

@app.route('/assign', methods=['GET'])
def assign_numbers():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # Check if already assigned
    cursor.execute("SELECT assigned FROM assignment_status WHERE id = 1")
    already_assigned = cursor.fetchone()[0]

    if already_assigned:
        flash("Numbers have already been assigned.", "info")
        return redirect(url_for('index'))

    # Reset all assignments before assigning (first-time only)
    cursor.execute("UPDATE players SET assigned = NULL")

    # Get unassigned players
    cursor.execute("""
        SELECT id, name, preferred1, preferred2, preferred3 
        FROM players 
        ORDER BY RANDOM()
    """)
    players = cursor.fetchall()

    # Get all taken numbers
    cursor.execute("SELECT assigned FROM players WHERE assigned IS NOT NULL")
    taken_numbers = {row[0] for row in cursor.fetchall()}

    # Available jersey numbers
    all_numbers = set(range(1, 100))
    available_numbers = list(all_numbers - taken_numbers)
    random.shuffle(available_numbers)

    # Assignment logic
    assigned_count = 0
    for player in players:
        player_id, name, p1, p2, p3 = player
        prefs = [n for n in [p1, p2, p3] if n is not None and n in available_numbers]

        if prefs:
            assigned_number = random.choice(prefs)
        elif available_numbers:
            assigned_number = available_numbers.pop()
        else:
            break  # No numbers left

        cursor.execute("UPDATE players SET assigned = ? WHERE id = ?", (assigned_number, player_id))
        available_numbers.remove(assigned_number)
        assigned_count += 1

    # Mark as assigned
    cursor.execute("UPDATE assignment_status SET assigned = 1 WHERE id = 1")

    conn.commit()
    conn.close()

    flash(f"Assigned jersey numbers to {assigned_count} players!", "success")
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        preferred1 = request.form.get('preferred1')
        preferred2 = request.form.get('preferred2')
        preferred3 = request.form.get('preferred3')

        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO players (name, phone, preferred1, preferred2, preferred3)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, phone, preferred1, preferred2, preferred3))
        conn.commit()
        conn.close()

        flash('Registration successful!')
        return redirect(url_for('index'))

    return render_template('register.html')


# Create status table to track if numbers have been assigned
with app.app_context():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assignment_status (
            id INTEGER PRIMARY KEY,
            assigned BOOLEAN DEFAULT 0
        )
    ''')
    # Initialize with one row if not exists
    cursor.execute("INSERT OR IGNORE INTO assignment_status (id, assigned) VALUES (1, 0)")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    app.run(debug=True)
