from flask import Flask, render_template, flash, redirect, url_for, request
import sqlite3

app = Flask(__name__)
app.secret_key = 'jemeajereseysecret!'


DATABASE = 'database.db'

def get_registered_players():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT name, preferred1, preferred2, preferred3, assigned FROM players")
    rows = cursor.fetchall()
    conn.close()

    players = []
    for row in rows:
        name = row[0]
        preferred = ', '.join([str(p) for p in row[1:4] if p])
        status = f"Assigned: #{row[4]}" if row[4] else "Pending"
        players.append({'name': name, 'preferred_numbers': preferred, 'status': status})
    return players

@app.route('/')
@app.route('/')
def index():
    players = get_registered_players()
    progress_percent = (len(players) / 7) * 100
    return render_template('index.html',
                         players=players,
                         progress_percent=progress_percent)


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

    # Reset all assignments first if we're doing a reshuffle
    if request.args.get('reshuffle'):
        cursor.execute("UPDATE players SET assigned = NULL")
        flash("All assignments have been reset for reshuffling", "info")

    # Get all unassigned players and their preferences
    cursor.execute("""
        SELECT id, name, preferred1, preferred2, preferred3 
        FROM players 
        WHERE assigned IS NULL
        ORDER BY RANDOM()  # Randomize the order for fairness
    """)
    players = cursor.fetchall()

    # Get all taken numbers
    cursor.execute("SELECT assigned FROM players WHERE assigned IS NOT NULL")
    taken_numbers = {row[0] for row in cursor.fetchall()}

    # Get all possible numbers (1-99)
    all_numbers = set(range(1, 100))
    available_numbers = all_numbers - taken_numbers

    # Assignment process
    unassigned_players = []
    assigned_count = 0

    for player in players:
        player_id, name, p1, p2, p3 = player
        preferred = [p for p in [p1, p2, p3] if p is not None and p in available_numbers]

        if preferred:
            # Assign a random preferred number
            assigned_number = random.choice(preferred)
            cursor.execute(
                "UPDATE players SET assigned = ? WHERE id = ?",
                (assigned_number, player_id)
            )
            available_numbers.remove(assigned_number)
            assigned_count += 1
        else:
            # No preferred numbers available
            unassigned_players.append((player_id, name))

    # Assign remaining numbers to unassigned players
    if available_numbers and unassigned_players:
        remaining_numbers = list(available_numbers)
        random.shuffle(remaining_numbers)

        for player_id, name in unassigned_players:
            if remaining_numbers:
                assigned_number = remaining_numbers.pop()
                cursor.execute(
                    "UPDATE players SET assigned = ? WHERE id = ?",
                    (assigned_number, player_id)
                )
                assigned_count += 1
            else:
                break

    conn.commit()
    conn.close()

    # Prepare feedback message
    if assigned_count:
        msg = f"Assigned {assigned_count} numbers! "
        if unassigned_players:
            msg += f"{len(unassigned_players)} players couldn't get preferred numbers."
        flash(msg, "success")
    else:
        flash("No new assignments made", "info")

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


if __name__ == '__main__':
    app.run(debug=True)
