CREATE DATABASE portfolio_plus;
USE portfolio_plus;

DROP TABLE IF EXISTS users;

CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(100) NOT NULL,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL,
    phone VARCHAR(15),
    address VARCHAR(255),
    wallet_balance DECIMAL(10,2) DEFAULT 10000.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);



Select * From users;


CREATE TABLE admin (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(100) NOT NULL,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

Select * From admin;

CREATE TABLE stocks (
    stock_symbol VARCHAR(10) PRIMARY KEY,
    date DATE NOT NULL,
    open_price DECIMAL(10, 2) NOT NULL,
    close_price DECIMAL(10, 2) NOT NULL
);

INSERT INTO stocks (stock_symbol, date, open_price, close_price)
VALUES 
('AAPL', '2024-11-01', 150.00, 155.00),
('MSFT', '2024-11-01', 295.00, 300.50),
('GOOGL', '2024-11-01', 2800.00, 2850.75),
('AMZN', '2024-11-01', 3450.00, 3500.10),
('TSLA', '2024-11-01', 800.00, 820.50);


Select * From stocks;