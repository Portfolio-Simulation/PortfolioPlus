from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
import os
from dotenv import load_dotenv
import yfinance as yf
import time

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

def fetch_stock_data(stock_symbols, watchlist_symbols=None):
    stocks_data = []
    for symbol in stock_symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")

            if hist.empty or len(hist) < 2:
                continue  # Skip if there isn't enough data

            info = ticker.info
            company_name = info.get('longName') or info.get('shortName') or symbol
            current_price = hist['Close'][-1]
            prev_price = hist['Close'][-2]
            gain_loss = round(current_price - prev_price, 2)
            percent_change = round((gain_loss / prev_price) * 100, 2)

            stocks_data.append({
                'symbol': symbol,
                'company_name': company_name,
                'prev_price': round(prev_price, 2),
                'current_price': round(current_price, 2),
                'gain_loss': gain_loss,
                'percent_change': percent_change,
                'volume': int(hist['Volume'][-1]),
                'in_watchlist': (symbol in watchlist_symbols) if watchlist_symbols else False
            })
        except Exception as e:
            print(f"Error fetching data for {symbol}: {str(e)}")
            continue
    return stocks_data




@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')

    cursor.execute("SELECT user_id,username FROM users WHERE username = %s AND password = %s", (username, password))
    user = cursor.fetchone()

    if user:
        session['user'] = user[1]  # Store user in session
        session['user_id'] = user[0] 
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

@app.route('/check_username', methods=['POST'])
def check_username():
    """AJAX route to check if the username is available."""
    username = request.form.get('username')
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()

    if user:
        return jsonify({'available': False})
    else:
        return jsonify({'available': True})

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

@app.route('/stocks')
def stocks():
    if 'user_id' not in session:
        flash('Please log in to view stocks.', 'danger')
        return redirect(url_for('home'))

    user_id = session['user_id']
            # stock_symbols = [
    #     'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 
    #     'META', 'NVDA', 'JPM', 'V', 'WMT',
    #     'PG', 'JNJ', 'KO', 'DIS', 'NFLX',
    #     'ADBE', 'CSCO', 'INTC', 'PEP', 'BAC'
    # ]

    # Less stocks for development
    stock_symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']

    # Get the user's watchlist
    cursor.execute("SELECT stock_symbol FROM watchlist WHERE user_id = %s", (user_id,))
    watchlist_symbols = {row[0] for row in cursor.fetchall()}

    # Use the helper function to fetch stock data
    stocks_data = fetch_stock_data(stock_symbols, watchlist_symbols)
    return render_template('stocks.html', stocks=stocks_data)





@app.route('/get_stock_history/<symbol>')
def get_stock_history(symbol):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="1y")
        
        if history.empty:
            return jsonify({'error': 'No data available'}), 404
        
        data = {
            'dates': [date.strftime('%Y-%m-%d') for date in history.index],
            'prices': history['Close'].tolist(),
            'volume': history['Volume'].tolist(),
            'symbol': symbol
        }
        
        return jsonify(data)
    except Exception as e:
        print(f"Error fetching data for {symbol}: {str(e)}")
        return jsonify({'error': 'Failed to fetch stock data'}), 500

@app.route('/get_market_indices')
def get_market_indices():
    try:
        # Extended list of market indices
        indices = {
            'SPY': {'name': 'S&P 500', 'color': '#2E86DE'},
            'DIA': {'name': 'Dow Jones', 'color': '#10AC84'},
            'QQQ': {'name': 'NASDAQ', 'color': '#5758BB'},
            'IWM': {'name': 'Russell 2000', 'color': '#FF6B6B'},  # Small-cap index
            'VGK': {'name': 'FTSE Europe', 'color': '#A8E6CF'},  # European markets
            'EEM': {'name': 'Emerging Markets', 'color': '#FFD93D'}  # Emerging markets
        }
        
        data = {}
        for symbol, info in indices.items():
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1y")
            
            if not hist.empty:
                data[symbol] = {
                    'name': info['name'],
                    'color': info['color'],
                    'prices': hist['Close'].tolist(),
                    'dates': [date.strftime('%Y-%m-%d') for date in hist.index],
                    'current_price': round(hist['Close'][-1], 2),
                    'change': round(hist['Close'][-1] - hist['Close'][-2], 2),
                    'change_percent': round(((hist['Close'][-1] - hist['Close'][-2]) / hist['Close'][-2]) * 100, 2)
                }
            
        return jsonify(data)
    except Exception as e:
        print(f"Error fetching market data: {str(e)}")
        return jsonify({'error': 'Failed to fetch market data'}), 500
    
@app.route('/watchlist')
def watchlist():
    if 'user_id' not in session:
        flash('Please log in to view your watchlist.', 'danger')
        return redirect(url_for('home'))

    user_id = session['user_id']
    cursor.execute("SELECT stock_symbol FROM watchlist WHERE user_id = %s", (user_id,))
    watchlist_items = cursor.fetchall()

    # Extract stock symbols from the watchlist items
    stock_symbols = [item[0] for item in watchlist_items]  # Adjust the index if needed

    # Use the helper function to fetch stock data
    stocks_data = fetch_stock_data(stock_symbols)
    message = None if stocks_data else "You have no stocks in your watchlist."
    return render_template('watchlist.html', stocks=stocks_data, message=message)



@app.route('/toggle_watchlist/<symbol>', methods=['POST'])
def toggle_watchlist(symbol):
    if 'user' not in session:
        return jsonify({'error': 'User not logged in'}), 403

    user_id = session['user_id']

        # Check if the stock is already in the watchlist
    cursor.execute("SELECT * FROM watchlist WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))
    existing_entry = cursor.fetchone()

    if existing_entry:
            # Remove from watchlist
        cursor.execute("DELETE FROM watchlist WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))
        db.commit()
        return jsonify({'in_watchlist': False})
    else:
            # Add to watchlist
        cursor.execute("INSERT INTO watchlist (user_id, stock_symbol) VALUES (%s, %s)", (user_id, symbol))
        db.commit()
        return jsonify({'in_watchlist': True})
        
if __name__ == '__main__':
    app.run(debug=True, port=5001)  
