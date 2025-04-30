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

    cursor.execute("SELECT COUNT(*) FROM players")
    total = cursor.fetchone()[0]

    if total < 7:
        flash(f"Only {total} players registered. Need 5 to assign numbers.")
        conn.close()
        return redirect(url_for('index'))

    # Fetch unassigned players and their preferences
    cursor.execute("SELECT id, preferred1, preferred2, preferred3 FROM players WHERE assigned IS NULL")
    players = cursor.fetchall()

    # Step 1: Map numbers to the users who want them
    preference_map = {}
    for player in players:
        player_id, *prefs = player
        for number in prefs:
            if number:
                preference_map.setdefault(number, []).append(player_id)

    # Step 2: Assign exclusive numbers first
    assigned = {}
    for number, ids in preference_map.items():
        if len(ids) == 1:
            user_id = ids[0]
            if user_id not in assigned:
                assigned[user_id] = number

    # Step 3: Randomly assign remaining users
    taken_numbers = set(assigned.values())
    for player in players:
        player_id, p1, p2, p3 = player
        if player_id in assigned:
            continue
        for preferred in [p1, p2, p3]:
            if preferred and preferred not in taken_numbers:
                assigned[player_id] = preferred
                taken_numbers.add(preferred)
                break

    # Step 4: Update database
    for user_id, number in assigned.items():
        cursor.execute("UPDATE players SET assigned = ? WHERE id = ?", (number, user_id))

    conn.commit()
    conn.close()

    flash("Jersey numbers successfully assigned!")
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
