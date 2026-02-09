from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import psycopg2
import psycopg2.extras
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests as http_requests
from dotenv import load_dotenv
from decimal import Decimal

# Load environment variables from .env
load_dotenv()

# Finnhub API configuration
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
FINNHUB_BASE = 'https://finnhub.io/api/v1'

# Simple in-memory cache (key -> (timestamp, data)) with 5-min TTL
_cache = {}
CACHE_TTL = 300  # 5 minutes

# Parallel fetch: max concurrent requests to Finnhub (avoids one-by-one slowness)
STOCKS_FETCH_WORKERS = 15

def finnhub_get(endpoint, params=None):
    """Make a cached GET request to Finnhub API."""
    cache_key = f"{endpoint}:{params}"
    now = time.time()
    if cache_key in _cache and (now - _cache[cache_key][0]) < CACHE_TTL:
        return _cache[cache_key][1]
    params = params or {}
    params['token'] = FINNHUB_API_KEY
    resp = http_requests.get(f"{FINNHUB_BASE}{endpoint}", params=params)
    data = resp.json()
    _cache[cache_key] = (now, data)
    return data

def yahoo_chart(symbol, period='1y', interval='1d'):
    """Fetch historical chart data directly from Yahoo Finance (no API key needed)."""
    cache_key = f"yahoo_chart:{symbol}:{period}:{interval}"
    now = time.time()
    if cache_key in _cache and (now - _cache[cache_key][0]) < CACHE_TTL:
        return _cache[cache_key][1]
    try:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        resp = http_requests.get(url, headers=headers, params={
            'range': period, 'interval': interval
        }, timeout=10)
        raw = resp.json()
        result = raw.get('chart', {}).get('result', [])
        if not result:
            return None
        chart = result[0]
        timestamps = chart.get('timestamp', [])
        quotes = chart.get('indicators', {}).get('quote', [{}])[0]
        closes = [c for c in quotes.get('close', []) if c is not None]
        volumes = [v if v is not None else 0 for v in quotes.get('volume', [])]
        dates = [datetime.fromtimestamp(t).strftime('%Y-%m-%d') for t in timestamps[:len(closes)]]
        chart_data = {'dates': dates, 'prices': closes, 'volumes': volumes[:len(closes)]}
        _cache[cache_key] = (now, chart_data)
        return chart_data
    except Exception as e:
        print(f"Error fetching Yahoo chart for {symbol}: {e}")
        return None

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your_secret_key')

# PostgreSQL connection setup
db = None

def get_db():
    """Get a database connection, reconnecting if the connection was dropped."""
    global db
    if db is None or db.closed:
        db = psycopg2.connect(os.getenv('DATABASE_URL'), sslmode='require')
        db.autocommit = True
    return db

def init_db():
    """Create tables if they don't exist and seed a demo user."""
    conn = get_db()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id SERIAL PRIMARY KEY,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    password VARCHAR(100) NOT NULL,
                    first_name VARCHAR(50) NOT NULL,
                    last_name VARCHAR(50) NOT NULL,
                    email VARCHAR(100) NOT NULL,
                    phone VARCHAR(15),
                    address VARCHAR(255),
                    wallet_balance DECIMAL(10,2) DEFAULT 10000.00,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admin (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    password VARCHAR(100) NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    email VARCHAR(100) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    watchlist_id SERIAL PRIMARY KEY,
                    user_id INT NOT NULL,
                    stock_symbol VARCHAR(10) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_id, stock_symbol),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS portfolios (
                    portfolio_id SERIAL PRIMARY KEY,
                    user_id INT,
                    stock_symbol VARCHAR(10),
                    company_name VARCHAR(50),
                    quantity INT,
                    sector VARCHAR(50),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id SERIAL PRIMARY KEY,
                    user_id INT,
                    stock_symbol VARCHAR(10),
                    transaction_type VARCHAR(4) CHECK (transaction_type IN ('buy', 'sell')),
                    quantity INT,
                    price DECIMAL(10, 2),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            # Seed demo user if not exists
            cur.execute("SELECT user_id FROM users WHERE username = 'demo'")
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO users (username, password, first_name, last_name, email, wallet_balance) "
                    "VALUES ('demo', 'demo123', 'Demo', 'User', 'demo@portfolioplus.com', 10000.00)"
                )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error initializing database: {e}")
    finally:
        conn.autocommit = True

# Initialize database tables and seed data on startup
init_db()

def _market_cap_bucket(market_cap_usd):
    """Bucket market cap (USD) into Large / Mid / Small / Micro."""
    if market_cap_usd is None or market_cap_usd <= 0:
        return 'N/A'
    if market_cap_usd >= 10e9:
        return 'Large cap'
    if market_cap_usd >= 2e9:
        return 'Mid cap'
    if market_cap_usd >= 300e6:
        return 'Small cap'
    return 'Micro cap'


def _fetch_one_stock(symbol, watchlist_symbols=None):
    """Fetch quote + profile for one symbol; return dict or None. Used in parallel."""
    try:
        quote = finnhub_get('/quote', {'symbol': symbol})
        profile = finnhub_get('/stock/profile2', {'symbol': symbol})

        current_price = quote.get('c', 0)
        prev_price = quote.get('pc', 0)

        if not current_price or not prev_price or prev_price == 0:
            return None

        gain_loss = round(current_price - prev_price, 2)
        percent_change = round((gain_loss / prev_price) * 100, 2)
        company_name = profile.get('name', symbol)
        sector = profile.get('finnhubIndustry') or 'N/A'

        market_cap_usd = profile.get('marketCapitalization')
        if market_cap_usd is None and current_price:
            shares = profile.get('shareOutstanding')
            if shares is not None:
                market_cap_usd = current_price * shares
        if market_cap_usd and 0 < market_cap_usd < 1e7:
            market_cap_usd = market_cap_usd * 1e6
        market_cap = _market_cap_bucket(market_cap_usd) if market_cap_usd else 'N/A'

        return {
            'symbol': symbol,
            'company_name': company_name,
            'prev_price': round(prev_price, 2),
            'current_price': round(current_price, 2),
            'gain_loss': gain_loss,
            'percent_change': percent_change,
            'sector': sector,
            'market_cap': market_cap,
            'in_watchlist': (symbol in watchlist_symbols) if watchlist_symbols else False
        }
    except Exception as e:
        print(f"Error fetching data for {symbol}: {str(e)}")
        return None


def fetch_stock_data(stock_symbols, watchlist_symbols=None):
    """Fetch stock data for all symbols in parallel for much faster load."""
    stocks_data = []
    watchlist_symbols = watchlist_symbols or set()
    max_workers = min(STOCKS_FETCH_WORKERS, len(stock_symbols)) or 1
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_symbol = {
            executor.submit(_fetch_one_stock, sym, watchlist_symbols): sym
            for sym in stock_symbols
        }
        for future in as_completed(future_to_symbol):
            result = future.result()
            if result is not None:
                stocks_data.append(result)
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

    cursor = get_db().cursor()
    cursor.execute("SELECT user_id, username,first_name FROM users WHERE username = %s AND password = %s", (username, password))
    user = cursor.fetchone()

    if user:
        session['user'] = user[1]
        session['user_id'] = user[0]
        session['first_name'] = user[2]
        flash(f'Welcome, {username}!', 'success')
        return redirect(url_for('dashboard'))
    else:
        flash('Invalid username or password.', 'danger')
        return redirect(url_for('home'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        address = request.form.get('address')
        username = request.form.get('username')
        password = request.form.get('password')

        cursor = get_db().cursor()

        # Server-side validation for username
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        existing_user = cursor.fetchone()
        if existing_user:
            flash('Username is already taken. Please choose another.', 'danger')
            return redirect(url_for('register'))

        # Server-side validation for email
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_email = cursor.fetchone()
        if existing_email:
            flash('Email is already registered. Please use another email.', 'danger')
            return redirect(url_for('register'))

        # If both checks pass, register the user
        cursor.execute(
            "INSERT INTO users (first_name, last_name, email, phone, address, username, password) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (first_name, last_name, email, phone, address, username, password)
        )
        get_db().commit()
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('home'))

    return render_template('register.html')
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Please log in to access the dashboard.', 'danger')
        return redirect(url_for('home'))

    user_id = session['user_id']
    cursor = get_db().cursor()
    cursor.execute("SELECT wallet_balance FROM users WHERE user_id = %s", (user_id,))
    wallet_balance = float(cursor.fetchone()[0])

    # Calculate portfolio value
    cursor.execute("SELECT stock_symbol, quantity FROM portfolios WHERE user_id = %s", (user_id,))
    holdings = cursor.fetchall()
    portfolio_value = 0.0
    for stock_symbol, quantity in holdings:
        try:
            quote = finnhub_get('/quote', {'symbol': stock_symbol})
            portfolio_value += quote.get('c', 0) * quantity
        except Exception:
            pass

    username = session.get('user')
    first_name = session.get('first_name')
    return render_template('dashboard.html', username=username, wallet_balance=wallet_balance,
                           first_name=first_name, portfolio_value=portfolio_value)

def get_all_stocks():
    """Top ~100 US stocks (large/mid cap, liquid names)."""
    return [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'BRK.B', 'TSLA', 'JPM', 'V',
        'UNH', 'JNJ', 'WMT', 'XOM', 'PG', 'MA', 'HD', 'CVX', 'ABBV', 'MRK',
        'PEP', 'KO', 'COST', 'LLY', 'AVGO', 'MCD', 'ABT', 'DHR', 'TMO', 'ACN',
        'NEE', 'WFC', 'DIS', 'PM', 'BMY', 'CSCO', 'ADBE', 'CRM', 'NKE', 'VZ',
        'TXN', 'CMCSA', 'NFLX', 'AMD', 'INTC', 'QCOM', 'HON', 'AMGN', 'RTX',
        'INTU', 'AMAT', 'SBUX', 'AXP', 'LOW', 'BKNG', 'GILD', 'MDLZ', 'ADI',
        'LMT', 'REGN', 'C', 'BLK', 'DE', 'SYK', 'CVS', 'GS', 'CAT', 'BA',
        'PLD', 'ISRG', 'VRTX', 'MO', 'MMC', 'ZTS', 'CB', 'SO', 'DUK', 'BDX',
        'BSX', 'EOG', 'SLB', 'CL', 'EQIX', 'ITW', 'APD', 'SHW', 'MCK', 'APTV',
        'PSA', 'ORLY', 'AON', 'SNPS', 'CDNS', 'KLAC', 'WM', 'CME', 'ICE',
        'MNST', 'CTAS', 'MAR', 'AIG', 'ECL', 'NXPI', 'A', 'HCA', 'TT', 'FIS',
        'GE', 'SPGI', 'PGR', 'AJG', 'MET', 'IQV', 'APH', 'ROST', 'TRP', 'HLT',
    ]
 

@app.route('/get_market_movers')
def get_market_movers():
    try:
        symbols = get_all_stocks()
        gainers = []
        losers = []
        
        for symbol in symbols:
            try:
                quote = finnhub_get('/quote', {'symbol': symbol})
                profile = finnhub_get('/stock/profile2', {'symbol': symbol})

                current_price = quote.get('c', 0)
                prev_close = quote.get('pc', 0)
                
                if current_price and prev_close and prev_close > 0:
                    change_pct = ((current_price - prev_close) / prev_close) * 100
                    stock_data = {
                        'symbol': symbol,
                        'name': profile.get('name', symbol),
                        'price': round(current_price, 2),
                        'change': round(change_pct, 2)
                    }
                    
                    if change_pct > 0:
                        gainers.append(stock_data)
                    elif change_pct < 0:
                        losers.append(stock_data)
            except Exception as e:
                print(f"Error processing {symbol}: {str(e)}")
                continue
        
        # Sort and get top 3 gainers and losers
        gainers = sorted(gainers, key=lambda x: x['change'], reverse=True)[:3]
        losers = sorted(losers, key=lambda x: x['change'])[:3]
        
        return jsonify({
            'gainers': gainers,
            'losers': losers
        })
    except Exception as e:
        print(f"Error in get_market_movers: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))


@app.after_request
def add_cache_control(response):
    """Prevent browser from caching authenticated pages (fixes back-button access after logout)."""
    if 'user_id' in session:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

@app.route('/stocks')
def stocks():
    if 'user_id' not in session:
        flash('Please log in to view stocks.', 'danger')
        return redirect(url_for('home'))

    user_id = session['user_id']
    stock_symbols = get_all_stocks()

    cursor = get_db().cursor()
    cursor.execute("SELECT stock_symbol FROM watchlist WHERE user_id = %s", (user_id,))
    watchlist_symbols = {row[0] for row in cursor.fetchall()}
    cursor.execute("SELECT wallet_balance FROM users WHERE user_id = %s", (user_id,))
    wallet_balance = cursor.fetchone()[0]
    cursor.execute("SELECT stock_symbol, quantity FROM portfolios WHERE user_id = %s", (user_id,))
    holdings = {row[0]: row[1] for row in cursor.fetchall()}

    stocks_data = fetch_stock_data(stock_symbols, watchlist_symbols)
    unique_sectors = sorted({s.get('sector') or 'N/A' for s in stocks_data})
    _cap_order = {'Large cap': 0, 'Mid cap': 1, 'Small cap': 2, 'Micro cap': 3, 'N/A': 4}
    unique_market_caps = sorted(
        {s.get('market_cap') or 'N/A' for s in stocks_data},
        key=lambda x: (_cap_order.get(x, 5), x)
    )
    return render_template('stocks.html', stocks=stocks_data, wallet_balance=wallet_balance, holdings=holdings,
                          unique_sectors=unique_sectors, unique_market_caps=unique_market_caps)

@app.route('/get_stock_history/<symbol>')
def get_stock_history(symbol):
    try:
        chart_data = yahoo_chart(symbol, period='1y', interval='1d')
        if not chart_data:
            return jsonify({'error': 'No data available'}), 404

        return jsonify({
            'dates': chart_data['dates'],
            'prices': chart_data['prices'],
            'volume': chart_data['volumes'],
            'symbol': symbol
        })
    except Exception as e:
        print(f"Error fetching data for {symbol}: {str(e)}")
        return jsonify({'error': 'Failed to fetch stock data'}), 500

# @app.route('/portfolio')
# def portfolio():
#     if 'user_id' not in session:
#         flash('Please log in to view your portfolio.', 'danger')
#         return redirect(url_for('home'))

#     user_id = session['user_id']
#     cursor = get_db().cursor()
#     cursor.execute("SELECT stock_symbol, company_name, quantity, sector FROM portfolios WHERE user_id = %s", (user_id,))
#     stocks = cursor.fetchall()
#     cursor.execute("SELECT wallet_balance FROM users WHERE user_id = %s", (user_id,))
#     wallet_balance = cursor.fetchone()[0]

#     stock_list = [{'symbol': stock[0], 'company_name': stock[1], 'quantity': stock[2], 'sector': stock[3]} for stock in stocks]
#     return render_template('portfolio.html', stocks=stock_list, wallet_balance=wallet_balance)

@app.route('/portfolio')
def portfolio():
    if 'user_id' not in session:
        flash('Please log in to view your portfolio.', 'danger')
        return redirect(url_for('home'))
 
    user_id = session['user_id']
    cursor = get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Modified query to explicitly select all needed fields
    cursor.execute("""
        SELECT
            p.stock_symbol,
            p.company_name,
            p.quantity,
            p.sector,
            (SELECT wallet_balance FROM users WHERE user_id = %s) as wallet_balance
        FROM Portfolios p
        WHERE p.user_id = %s
    """, (user_id, user_id))
    
    portfolio_data = cursor.fetchall()
    
    # Get wallet balance even if portfolio is empty
    if not portfolio_data:
        cursor.execute("SELECT wallet_balance FROM users WHERE user_id = %s", (user_id,))
        wallet_balance = float(cursor.fetchone()['wallet_balance'])
    else:
        wallet_balance = float(portfolio_data[0]['wallet_balance'])
 
    # Update current prices and calculate totals
    total_value = 0
    for stock in portfolio_data:
        try:
            quote = finnhub_get('/quote', {'symbol': stock['stock_symbol']})
            current_price = quote.get('c', 0)
            stock['current_price'] = current_price
            stock['total_value'] = current_price * stock['quantity']
            total_value += stock['total_value']
            
            # Update company name and sector if they're missing
            if not stock['company_name'] or stock['company_name'] == 'None':
                profile = finnhub_get('/stock/profile2', {'symbol': stock['stock_symbol']})
                stock['company_name'] = profile.get('name', stock['stock_symbol'])
                stock['sector'] = profile.get('finnhubIndustry', 'Technology')
                
                # Update the database with correct information
                cursor.execute("""
                    UPDATE Portfolios
                    SET company_name = %s, sector = %s
                    WHERE user_id = %s AND stock_symbol = %s
                """, (stock['company_name'], stock['sector'], user_id, stock['stock_symbol']))
                get_db().commit()
                
        except Exception as e:
            print(f"Error getting price for {stock['stock_symbol']}: {str(e)}")
            stock['current_price'] = 0
            stock['total_value'] = 0
 
    return render_template('portfolio.html',
                         stocks=portfolio_data,
                         wallet_balance=wallet_balance,
                         total_value=total_value)

@app.route('/get_portfolio_analytics')
def get_portfolio_analytics():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
        
    try:
        user_id = session['user_id']
        cursor = get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get user's portfolio
        cursor.execute("""
            SELECT stock_symbol, quantity, sector
            FROM portfolios
            WHERE user_id = %s
        """, (user_id,))
        portfolio = cursor.fetchall()
        
        # Calculate sector distribution
        sector_distribution = {}
        total_value = 0
        
        for stock in portfolio:
            quote = finnhub_get('/quote', {'symbol': stock['stock_symbol']})
            current_price = quote.get('c', 0)
            stock_value = current_price * stock['quantity']
            total_value += stock_value
            
            sector = stock['sector']
            if sector in sector_distribution:
                sector_distribution[sector] += stock_value
            else:
                sector_distribution[sector] = stock_value
        
        # Convert to percentages
        for sector in sector_distribution:
            sector_distribution[sector] = round((sector_distribution[sector] / total_value) * 100, 2)
        
        # Calculate basic risk metrics
        risk_analysis = {
            'total_value': round(total_value, 2),
            'num_stocks': len(portfolio),
            'diversification_score': min(100, len(portfolio) * 10)  # Simple diversification metric
        }
        
        # Calculate performance
        performance = {
            'daily_change': 0,
            'weekly_change': 0,
            'monthly_change': 0
        }
        
        return jsonify({
            'sector_distribution': sector_distribution,
            'risk_analysis': risk_analysis,
            'performance': performance
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/watchlist')
def watchlist():
    if 'user_id' not in session:
        flash('Please log in to view your watchlist.', 'danger')
        return redirect(url_for('home'))

    user_id = session['user_id']
    cursor = get_db().cursor()
    cursor.execute("SELECT stock_symbol FROM watchlist WHERE user_id = %s", (user_id,))
    watchlist_items = cursor.fetchall()
    cursor.execute("SELECT wallet_balance FROM users WHERE user_id = %s", (user_id,))
    wallet_balance = cursor.fetchone()[0]

    stock_symbols = [item[0] for item in watchlist_items]
    stocks_data = fetch_stock_data(stock_symbols)
    message = None if stocks_data else "You have no stocks in your watchlist."
    return render_template('watchlist.html', stocks=stocks_data, message=message, wallet_balance=wallet_balance)

@app.route('/toggle_watchlist/<symbol>', methods=['POST'])
def toggle_watchlist(symbol):
    if 'user' not in session:
        return jsonify({'error': 'User not logged in'}), 403

    user_id = session['user_id']
    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM watchlist WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))
    existing_entry = cursor.fetchone()

    if existing_entry:
        cursor.execute("DELETE FROM watchlist WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))
        get_db().commit()
        return jsonify({'in_watchlist': False})
    else:
        cursor.execute("INSERT INTO watchlist (user_id, stock_symbol) VALUES (%s, %s)", (user_id, symbol))
        get_db().commit()
        return jsonify({'in_watchlist': True})

@app.route('/process_transaction', methods=['POST'])
def process_transaction():
    data = request.get_json()
    symbol = data.get('symbol').strip()
    transaction_type = data.get('transaction_type')
    quantity = Decimal(data.get('quantity'))
    amount = Decimal(data.get('amount'))

    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 403

    user_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT wallet_balance FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    if not result:
        return jsonify({'error': 'User not found'}), 404

    wallet_balance = Decimal(result[0])

    if transaction_type == 'buy':
        if wallet_balance < amount:
            return jsonify({'error': 'Insufficient balance'}), 400

        new_balance = wallet_balance - amount

        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET wallet_balance = %s WHERE user_id = %s", (new_balance, user_id))
                cur.execute(
                    "INSERT INTO transactions (user_id, stock_symbol, transaction_type, quantity, price) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (user_id, symbol, transaction_type, quantity, amount)
                )
                cur.execute("SELECT quantity FROM portfolios WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))
                portfolio_item = cur.fetchone()

                if portfolio_item:
                    new_quantity = Decimal(portfolio_item[0]) + quantity
                    cur.execute("UPDATE portfolios SET quantity = %s WHERE user_id = %s AND stock_symbol = %s",
                                   (new_quantity, user_id, symbol))
                else:
                    cur.execute("INSERT INTO portfolios (user_id, stock_symbol, quantity) VALUES (%s, %s, %s)",
                                   (user_id, symbol, quantity))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error: {str(e)}")
            return jsonify({'error': 'Transaction failed'}), 500
        finally:
            conn.autocommit = True

    elif transaction_type == 'sell':
        conn.autocommit = False
        try:
            cur = conn.cursor()
            cur.execute("SELECT quantity FROM portfolios WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))
            portfolio_entry = cur.fetchone()
            if not portfolio_entry or Decimal(portfolio_entry[0]) < quantity:
                conn.rollback()
                return jsonify({'error': 'Insufficient stock quantity'})

            new_quantity = Decimal(portfolio_entry[0]) - quantity
            if new_quantity > 0:
                cur.execute("UPDATE portfolios SET quantity = %s WHERE user_id = %s AND stock_symbol = %s",
                               (new_quantity, user_id, symbol))
            else:
                cur.execute("DELETE FROM portfolios WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))

            new_balance = wallet_balance + amount
            cur.execute("UPDATE users SET wallet_balance = %s WHERE user_id = %s", (new_balance, user_id))

            cur.execute(
                "INSERT INTO transactions (user_id, stock_symbol, transaction_type, quantity, price) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, symbol, transaction_type, quantity, amount)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error: {str(e)}")
            return jsonify({'error': 'Transaction failed'}), 500
        finally:
            conn.autocommit = True

    return jsonify({'success': True})

@app.route('/get_market_indices')
def get_market_indices():
    # Get the 'timeframe' query parameter from the request
    timeframe = request.args.get('timeframe', '1Y')  # Default to 1 year if not specified
    
    # Map timeframes to Yahoo Finance range values
    range_map = {
        '1M': '1mo',
        '3M': '3mo',
        '6M': '6mo',
        '1Y': '1y'
    }
    period = range_map.get(timeframe, '1y')

    try:
        indices = {
            'SPY': {'name': 'S&P 500', 'color': '#2E86DE'},
            'DIA': {'name': 'Dow Jones', 'color': '#10AC84'},
            'QQQ': {'name': 'NASDAQ', 'color': '#5758BB'},
            'IWM': {'name': 'Russell 2000', 'color': '#FF6B6B'}, 
            'VGK': {'name': 'FTSE Europe', 'color': '#A8E6CF'},  
            'EEM': {'name': 'Emerging Markets', 'color': '#FFD93D'}
        }
        data = {}
        for symbol, info in indices.items():
            chart_data = yahoo_chart(symbol, period=period, interval='1d')
            if not chart_data or len(chart_data['prices']) < 2:
                continue
            prices = chart_data['prices']
            data[symbol] = {
                'name': info['name'],
                'color': info['color'],
                'dates': chart_data['dates'],
                'prices': prices,
                'current_price': round(prices[-1], 2),
                'change': round(prices[-1] - prices[-2], 2),
                'change_percent': round(((prices[-1] - prices[-2]) / prices[-2]) * 100, 2)
            }
        return jsonify(data)
    except Exception as e:
        print(f"Error fetching market data: {str(e)}")
        return jsonify({'error': 'Failed to fetch market data'}), 500



@app.route('/get_dashboard_holdings')
def get_dashboard_holdings():
    """Return current holdings with real cost basis computed from transactions."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    try:
        user_id = session['user_id']
        cursor = get_db().cursor()

        # Get current holdings
        cursor.execute("SELECT stock_symbol, quantity FROM portfolios WHERE user_id = %s", (user_id,))
        holdings = cursor.fetchall()

        if not holdings:
            return jsonify({'empty': True, 'holdings': []})

        # For each holding, compute average cost from buy transactions
        result = []
        for symbol, quantity in holdings:
            # Sum total spent on buys and total shares bought
            cursor.execute("""
                SELECT COALESCE(SUM(price), 0), COALESCE(SUM(quantity), 0)
                FROM transactions
                WHERE user_id = %s AND stock_symbol = %s AND transaction_type = 'buy'
            """, (user_id, symbol))
            total_spent, total_bought = cursor.fetchone()
            total_spent = float(total_spent)
            total_bought = float(total_bought)

            avg_cost_per_share = (total_spent / total_bought) if total_bought > 0 else 0

            # Get current price
            quote = finnhub_get('/quote', {'symbol': symbol})
            current_price = quote.get('c', 0)

            # Get company name
            profile = finnhub_get('/stock/profile2', {'symbol': symbol})
            company_name = profile.get('name', symbol)

            current_value = current_price * quantity
            cost_basis = avg_cost_per_share * quantity
            gain_loss = current_value - cost_basis
            gain_loss_pct = ((gain_loss / cost_basis) * 100) if cost_basis > 0 else 0

            result.append({
                'symbol': symbol,
                'name': company_name,
                'quantity': quantity,
                'current_price': round(current_price, 2),
                'current_value': round(current_value, 2),
                'avg_cost': round(avg_cost_per_share, 2),
                'cost_basis': round(cost_basis, 2),
                'gain_loss': round(gain_loss, 2),
                'gain_loss_pct': round(gain_loss_pct, 2)
            })

        return jsonify({'empty': False, 'holdings': result})
    except Exception as e:
        print(f"Error fetching dashboard holdings: {str(e)}")
        return jsonify({'error': 'Failed to fetch holdings data'}), 500


@app.route('/check_username', methods=['POST'])
def check_username():
    data = request.get_json()  # Use get_json() to parse JSON data
    username = data.get('username')
    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    if user:
        return jsonify({'available': False})
    else:
        return jsonify({'available': True})

@app.route('/check_email', methods=['POST'])
def check_email():
    data = request.get_json()  # Use get_json() to parse JSON data
    email = data.get('email')  # Retrieve the email from the JSON data

    if not email:
        return jsonify({'error': 'Email not provided'}), 400

    cursor = get_db().cursor()
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    
    # Fetch all results to clear any unread results
    user = cursor.fetchone()
    cursor.fetchall()  # This ensures all results are read, even if not used

    cursor.close()

    if user:
        return jsonify({'available': False})
    else:   
        return jsonify({'available': True})

@app.route('/get_stock_price/<symbol>')
def get_stock_price(symbol):
    try:
        quote = finnhub_get('/quote', {'symbol': symbol})
        current_price = quote.get('c')
        
        if not current_price:
            return jsonify({'error': 'Price not available'}), 404
            
        return jsonify({
            'price': current_price
        })
    except Exception as e:
        print(f"Error fetching price for {symbol}: {str(e)}")
        return jsonify({'error': 'Failed to fetch stock price'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5002)
