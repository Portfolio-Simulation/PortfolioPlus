from flask import Flask, render_template, request, redirect, url_for, flash, session
import mysql.connector
import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure random key

# MySQL connection setup
db = mysql.connector.connect(
    host=os.getenv('MYSQL_HOST'),
    user=os.getenv('MYSQL_USER'),
    password=os.getenv('MYSQL_PASSWORD'),
    database=os.getenv('MYSQL_DB')
)
cursor = db.cursor()

@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')

    cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
    user = cursor.fetchone()

    if user:
        session['user'] = username  # Store user in session
        flash(f'Welcome, {username}!', 'success')
        return redirect(url_for('dashboard'))
    else:
        flash('Invalid username or password.', 'danger')
        return redirect(url_for('home'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        address = request.form.get('address')
        username = request.form.get('username')
        password = request.form.get('password')

        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        existing_user = cursor.fetchone()

        if existing_user:
            flash('Username already taken. Please choose another.', 'danger')
        else:
            cursor.execute(
                "INSERT INTO users (name, email, phone, address, username, password) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (name, email, phone, address, username, password)
            )
            db.commit()
            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('home'))

    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        flash('Please log in to access the dashboard.', 'danger')
        return redirect(url_for('home'))

    username = session.get('user')
    return render_template('dashboard.html', username=username)

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)
