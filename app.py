from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
import os
from dotenv import load_dotenv
import yfinance as yf

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
    stock_symbols = [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 
        'META', 'NVDA', 'JPM', 'V', 'WMT',
        'PG', 'JNJ', 'KO', 'DIS', 'NFLX',
        'ADBE', 'CSCO', 'INTC', 'PEP', 'BAC'
    ]
    stocks_data = []
    
    for symbol in stock_symbols:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            hist = ticker.history(period="5d")
            
            if len(hist) >= 2:
                company_name = info.get('longName', symbol)
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
                    'volume': int(hist['Volume'][-1])
                })
        except Exception as e:
            print(f"Error fetching data for {symbol}: {str(e)}")
            continue

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
    
if __name__ == '__main__':
    app.run(debug=True, port=5001)  
