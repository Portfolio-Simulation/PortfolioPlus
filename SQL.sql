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

CREATE TABLE watchlist (
    watchlist_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    stock_symbol VARCHAR(5) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, stock_symbol), 
    FOREIGN KEY (user_id) REFERENCES users(user_id)  
);

Select * From watchlist;
-- Creating the Portfolios Table
CREATE TABLE Portfolios (
    portfolio_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT,
    stock_symbol VARCHAR(10),
    quantity INT,
    sector VARCHAR(50),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

Select * From Portfolios;

-- Creating the Transactions Table
CREATE TABLE Transactions (
    transaction_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT,
    stock_symbol VARCHAR(10),
    transaction_type ENUM('buy', 'sell'),
    quantity INT,
    price DECIMAL(10, 2),
    transaction_date DATETIME,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
Select * From Transactions;
