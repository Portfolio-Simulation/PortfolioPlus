from flask import Flask, render_template, request, redirect, url_for, flash
import mysql.connector

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # For session management

# MySQL connection configuration
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="portfolio_plus"
)

cursor = db.cursor()

# Route for the login page
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Insert user data into the MySQL database
        try:
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)",
                (username, password)
            )
            db.commit()
            flash('User registered successfully!', 'success')
        except mysql.connector.Error as err:
            flash(f"Error: {err}", 'danger')

        return redirect(url_for('login'))

    return render_template('login.html')

if __name__ == '__main__':
    app.run(debug=True)
