from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
import os
from dotenv import load_dotenv
import yfinance as yf
from decimal import Decimal

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

# Function to fetch stock data#
def fetch_stock_data(stock_symbols, watchlist_symbols=None):
    stocks_data = []
    for symbol in stock_symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            if hist.empty or len(hist) < 2:
                continue

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

    cursor = db.cursor()
    cursor.execute("SELECT user_id, username FROM users WHERE username = %s AND password = %s", (username, password))
    user = cursor.fetchone()

    if user:
        session['user'] = user[1]
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

        cursor = db.cursor()

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
    if 'user_id' not in session:
        flash('Please log in to access the dashboard.', 'danger')
        return redirect(url_for('home'))

    user_id = session['user_id']
    cursor = db.cursor()
    cursor.execute("SELECT wallet_balance FROM users WHERE user_id = %s", (user_id,))
    wallet_balance = cursor.fetchone()[0]

    username = session.get('user')
    return render_template('dashboard.html', username=username, wallet_balance=wallet_balance,invested_amount=0,portfolio_value=0)

def get_all_stocks():
    return [
        'GOOGL',  # Alphabet
        'AAPL',   # Apple
        'AMZN',   # Amazon
        'BAC',    # Bank of America
        'DIS',    # Disney
        'JNJ',    # Johnson & Johnson
        'JPM',    # JPMorgan Chase
        'META',   # Meta
        'MSFT',   # Microsoft
        'NFLX',   # Netflix
        'NVDA',   # NVIDIA
        'TSLA',   # Tesla
        'UNH',    # UnitedHealth
        'V',      # Visa
        'WMT',    # Walmart
    ]
 

@app.route('/get_market_movers')
def get_market_movers():
    try:
        symbols = get_all_stocks()
        gainers = []
        losers = []
        
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d")
                if hist.empty or len(hist) < 2:
                    continue
                info = ticker.info
                current_price = hist['Close'][-1]
                prev_close = hist['Close'][-2]
                
                # Ensure valid data is retrieved
                if current_price is not None and prev_close is not None and prev_close > 0:
                    change_pct = ((current_price - prev_close) / prev_close) * 100
                    stock_data = {
                        'symbol': symbol,
                        'name': info.get('shortName', symbol),
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
        
        # Sort and get top 5 gainers and losers
        gainers = sorted(gainers, key=lambda x: x['change'], reverse=True)[:5]
        losers = sorted(losers, key=lambda x: x['change'])[:5]
        
        return jsonify({
            'gainers': gainers,
            'losers': losers
        })
    except Exception as e:
        print(f"Error in get_market_movers: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
    stock_symbols = get_all_stocks()

    cursor = db.cursor()
    cursor.execute("SELECT stock_symbol FROM watchlist WHERE user_id = %s", (user_id,))
    watchlist_symbols = {row[0] for row in cursor.fetchall()}
    cursor.execute("SELECT wallet_balance FROM users WHERE user_id = %s", (user_id,))
    wallet_balance = cursor.fetchone()[0]  

    stocks_data = fetch_stock_data(stock_symbols, watchlist_symbols)
    return render_template('stocks.html', stocks=stocks_data, wallet_balance=wallet_balance)

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

# @app.route('/portfolio')
# def portfolio():
#     if 'user_id' not in session:
#         flash('Please log in to view your portfolio.', 'danger')
#         return redirect(url_for('home'))

#     user_id = session['user_id']
#     cursor = db.cursor()
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
    cursor = db.cursor(dictionary=True)
    
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
        wallet_balance = cursor.fetchone()['wallet_balance']
    else:
        wallet_balance = portfolio_data[0]['wallet_balance']
 
    # Update current prices and calculate totals
    total_value = 0
    for stock in portfolio_data:
        try:
            ticker = yf.Ticker(stock['stock_symbol'])
            info = ticker.info
            current_price = info.get('regularMarketPrice', 0)
            stock['current_price'] = current_price
            stock['total_value'] = current_price * stock['quantity']
            total_value += stock['total_value']
            
            # Update company name and sector if they're missing
            if not stock['company_name'] or stock['company_name'] == 'None':
                stock['company_name'] = info.get('longName') or info.get('shortName') or stock['stock_symbol']
                stock['sector'] = info.get('sector') or 'Technology'
                
                # Update the database with correct information
                cursor.execute("""
                    UPDATE Portfolios
                    SET company_name = %s, sector = %s
                    WHERE user_id = %s AND stock_symbol = %s
                """, (stock['company_name'], stock['sector'], user_id, stock['stock_symbol']))
                db.commit()
                
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
        cursor = db.cursor(dictionary=True)
        
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
            ticker = yf.Ticker(stock['stock_symbol'])
            current_price = ticker.info.get('regularMarketPrice', 0)
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
    cursor = db.cursor()
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
    cursor = db.cursor()
    cursor.execute("SELECT * FROM watchlist WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))
    existing_entry = cursor.fetchone()

    if existing_entry:
        cursor.execute("DELETE FROM watchlist WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))
        db.commit()
        return jsonify({'in_watchlist': False})
    else:
        cursor.execute("INSERT INTO watchlist (user_id, stock_symbol) VALUES (%s, %s)", (user_id, symbol))
        db.commit()
        return jsonify({'in_watchlist': True})

@app.route('/process_transaction', methods=['POST'])
def process_transaction():
    data = request.get_json()
    symbol = data.get('symbol')
    transaction_type = data.get('transaction_type')
    quantity = Decimal(data.get('quantity'))
    amount = Decimal(data.get('amount'))

    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 403

    user_id = session['user_id']
    cursor = db.cursor()
    cursor.execute("SELECT wallet_balance FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    if not result:
        return jsonify({'error': 'User not found'}), 404

    wallet_balance = Decimal(result[0])

    if transaction_type == 'buy':
        if wallet_balance < amount:
            return jsonify({'error': 'Insufficient balance'}), 400

        new_balance = wallet_balance - amount

        try:
            with db.cursor() as cursor:
                cursor.execute("UPDATE users SET wallet_balance = %s WHERE user_id = %s", (new_balance, user_id))
                cursor.execute(
                    "INSERT INTO transactions (user_id, stock_symbol, transaction_type, quantity, price) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (user_id, symbol, transaction_type, quantity, amount)
                )
                cursor.execute("SELECT quantity FROM portfolios WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))
                portfolio_item = cursor.fetchone()

                if portfolio_item:
                    new_quantity = Decimal(portfolio_item[0]) + quantity
                    cursor.execute("UPDATE portfolios SET quantity = %s WHERE user_id = %s AND stock_symbol = %s",
                                   (new_quantity, user_id, symbol))
                else:
                    cursor.execute("INSERT INTO portfolios (user_id, stock_symbol, quantity) VALUES (%s, %s, %s)",
                                   (user_id, symbol, quantity))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Error: {str(e)}")
            return jsonify({'error': 'Transaction failed'}), 500

    elif transaction_type == 'sell':
        cursor.execute("SELECT quantity FROM portfolios WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))
        portfolio_entry = cursor.fetchone()
        if not portfolio_entry or Decimal(portfolio_entry[0]) < quantity:
            return jsonify({'error': 'Insufficient stock quantity'})

        new_quantity = Decimal(portfolio_entry[0]) - quantity
        if new_quantity > 0:
            cursor.execute("UPDATE portfolios SET quantity = %s WHERE user_id = %s AND stock_symbol = %s",
                           (new_quantity, user_id, symbol))
        else:
            cursor.execute("DELETE FROM portfolios WHERE user_id = %s AND stock_symbol = %s", (user_id, symbol))

        new_balance = wallet_balance + amount
        cursor.execute("UPDATE users SET wallet_balance = %s WHERE user_id = %s", (new_balance, user_id))

        cursor.execute(
            "INSERT INTO transactions (user_id, stock_symbol, transaction_type, quantity, price) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, symbol, transaction_type, quantity, amount)
        )
        db.commit()

    return jsonify({'success': True})

@app.route('/get_market_indices')
def get_market_indices():
    # Get the 'timeframe' query parameter from the request
    timeframe = request.args.get('timeframe', '1y')  # Default to 1 year if not specified
    
    # Map the accepted timeframes to periods for yfinance
    periods = {
        '1M': '1mo',
        '3M': '3mo',
        '6M': '6mo',
        '1Y': '1y'
    }
    period = periods.get(timeframe, '1y')  # Default to 1 year if timeframe is invalid

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
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period)
            if hist.empty:
                continue
            data[symbol] = {
                'name': info['name'],
                'color': info['color'],
                'dates': [date.strftime('%Y-%m-%d') for date in hist.index],
                'prices': hist['Close'].tolist(),
                'current_price': round(hist['Close'][-1], 2),
                'change': round(hist['Close'][-1] - hist['Close'][-2], 2),
                'change_percent': round(((hist['Close'][-1] - hist['Close'][-2]) / hist['Close'][-2]) * 100, 2)
            }
        return jsonify(data)
    except Exception as e:
        print(f"Error fetching market data: {str(e)}")
        return jsonify({'error': 'Failed to fetch market data'}), 500



@app.route('/check_username', methods=['POST'])
def check_username():
    data = request.get_json()  # Use get_json() to parse JSON data
    username = data.get('username')
    cursor = db.cursor()
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

    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    
    # Fetch all results to clear any unread results
    user = cursor.fetchone()
    cursor.fetchall()  # This ensures all results are read, even if not used

    cursor.close()

    if user:
        return jsonify({'available': False})
    else:   
        return jsonify({'available': True})


if __name__ == '__main__':
    app.run(debug=True, port=5001)
