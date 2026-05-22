-- Enable the vector extension
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS nyse_securities (
    ticker VARCHAR(10),
    create_date DATE,
    nyse_security VARCHAR(50),
    sector VARCHAR(50),
    industry VARCHAR(50),
    headquarter VARCHAR(50),
    PRIMARY KEY (ticker)
);

CREATE TABLE IF NOT EXISTS nyse_prices (
    ticker VARCHAR(10),
    trade_date DATE,
    open_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    close_price NUMERIC,
    volume BIGINT,
    PRIMARY KEY (ticker, trade_date)
);

-- News Unstructured Headlines Schema (Using a 384-dim vector)
CREATE TABLE IF NOT EXISTS news_headlines (
    id SERIAL PRIMARY KEY,
    publish_date DATE,
    headline TEXT,
    embedding VECTOR(384) 
);
