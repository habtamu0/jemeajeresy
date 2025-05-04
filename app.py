from flask import Flask, render_template, flash, redirect, url_for, request
import sqlite3
import random

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
        status = "Pending"
        status_class = "status-pending"

        if assigned:
            assigned_numbers.append(assigned)
            prefs = {p1, p2, p3}
            if assigned in prefs:
                status = f"Assigned: #{assigned}"
                status_class = "status-assigned"
            else:
                status = f"Assigned: #{assigned} (Not preferred)"
                status_class = "status-unlucky"

        players.append({
            'id': player_id,
            'name': name,
            'preferred_numbers': preferred_display,
            'preferred_list': preferred,
            'assigned': assigned,
            'assigned_number': assigned,
            'status': status,
            'status_class': status_class
        })

    return {
        'players': players,
        'assigned_numbers': assigned_numbers
    }

from flask import session

@app.route('/')
def index():
    data = get_registered_players()
    players = data['players']
    assigned_numbers = data['assigned_numbers']
    assigned_players = [p for p in players if p.get('assigned')]

    # Check if shuffle has been done
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT shuffled FROM shuffle_status WHERE id = 1")
    result = cursor.fetchone()
    shuffle_done = bool(result[0]) if result else False
    conn.close()

    return render_template(
        'index.html',
        players=players,
        assigned_numbers=assigned_numbers,
        assigned_players=assigned_players,
        current_user_numbers=[],
        progress_percent=(len(players)/32 * 100),
        shuffle_done=shuffle_done
    )

@app.route('/shuffle', methods=['GET'])
def shuffle_numbers():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # Check if already shuffled
    cursor.execute("SELECT shuffled FROM shuffle_status WHERE id = 1")
    result = cursor.fetchone()
    if result and result[0]:
        flash("Reshuffling is disabled after initial use.", "info")
        conn.close()
        return redirect(url_for('index'))

    # Reset all previous assignments
    cursor.execute("UPDATE players SET assigned = NULL")

    # Get all players (random order)
    cursor.execute("SELECT id, preferred1, preferred2, preferred3 FROM players")
    players = cursor.fetchall()

    # Get available numbers
    all_numbers = list(range(1, 100))
    random.shuffle(all_numbers)

    unassigned_players = []

    # First pass: Assign from preferences
    for player in players:
        player_id, p1, p2, p3 = player
        prefs = [n for n in [p1, p2, p3] if n is not None and n in all_numbers]

        if prefs:
            assigned_number = random.choice(prefs)
            cursor.execute("UPDATE players SET assigned = ? WHERE id = ?", (assigned_number, player_id))
            all_numbers.remove(assigned_number)
        else:
            unassigned_players.append(player_id)

    # Second pass: Assign remaining players with leftover numbers
    random.shuffle(unassigned_players)
    for player_id in unassigned_players:
        if all_numbers:
            assigned_number = random.choice(all_numbers)
            cursor.execute("UPDATE players SET assigned = ? WHERE id = ?", (assigned_number, player_id))
            all_numbers.remove(assigned_number)

    # Mark shuffle as done
    cursor.execute("UPDATE shuffle_status SET shuffled = 1 WHERE id = 1")
    conn.commit()
    conn.close()

    flash(f"Jersey numbers have been shuffled fairly among all players!", "success")
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


# Create tables on startup
with app.app_context():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # Players table
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

    # Shuffle status table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shuffle_status (
            id INTEGER PRIMARY KEY,
            shuffled BOOLEAN DEFAULT 0
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO shuffle_status (id, shuffled) VALUES (1, 0)")

    conn.commit()
    conn.close()


if __name__ == '__main__':
    app.run(debug=True)
