import os
import polars as pl
import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "agent_warehouse")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "local_dev_password")

CONN_STR = (
    f"host={POSTGRES_HOST} "
    f"port={POSTGRES_PORT} "
    f"dbname={POSTGRES_DB} "
    f"user={POSTGRES_USER} "
    f"password={POSTGRES_PASSWORD}"
)
DATA_DIR = os.environ.get("DATA_DIR", "./data")
HEADLINE_SAMPLE_SIZE = int(os.environ.get("HEADLINE_SAMPLE_SIZE", "200000"))

ENCODER_MODEL = os.environ.get("ENCODER_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# Initialize the local embedding model
print(f"Loading local embedding model ({ENCODER_MODEL})")
model = SentenceTransformer(ENCODER_MODEL,)

# load datasets using Polars
securities_df = (
    pl.read_csv(os.path.join(DATA_DIR, "nyse_securities.csv"), null_values=[""])
    .select([
        pl.col("Ticker symbol").alias("ticker").cast(pl.String),
        pl.col("Date first added").alias("create_date").cast(pl.Utf8).str.to_date("%Y-%m-%d"),
        pl.col("Security").alias("nyse_security").cast(pl.String),
        pl.col("GICS Sector").alias("sector").cast(pl.String),
        pl.col("GICS Sub Industry").alias("industry").cast(pl.String),
        pl.col("Address of Headquarters").alias("headquarter").cast(pl.String),
    ])
)

prices_df = (
    pl.read_csv(os.path.join(DATA_DIR, "nyse_prices.csv"), null_values=[""],)
    .select([
        pl.col("symbol").alias("ticker").cast(pl.String),
        pl.col("date").alias("trade_date").cast(pl.Utf8).str.to_date("%Y-%m-%d"),
        pl.col("open").alias("open_price").cast(pl.Float64),
        pl.col("close").alias("close_price").cast(pl.Float64),
        pl.col("high").alias("high_price").cast(pl.Float64),
        pl.col("low").alias("low_price").cast(pl.Float64),
        pl.col("volume").cast(pl.Int64),
    ])
)

headlines_df = (
    pl.read_csv(os.path.join(DATA_DIR, "news_headlines.csv"))
    .sample(n=HEADLINE_SAMPLE_SIZE, seed=42)
    .select([
        pl.col("publish_date").cast(pl.Utf8).str.to_date("%Y%m%d").alias("publish_date"),
        pl.col("headline_text").alias("headline").cast(pl.String),
    ])
    .filter(~pl.col("headline").str.contains("news exchange")) # filter out text with no significant infomation
)

print(f"Vectorizing headlines (time consuming)")
headlines_list = headlines_df["headline"].to_list()
embeddings = model.encode(headlines_list, show_progress_bar=True)

# 4. Bulk Load into pgvector using Binary Copy
with psycopg.connect(CONN_STR) as conn:
    # Crucial step to let psycopg know how to serialize Python lists to pgvector arrays
    register_vector(conn)
    
    with conn.cursor() as cur:
        # Clear existing data to allow safe pipeline re-runs
        cur.execute("TRUNCATE nyse_securities, nyse_prices, news_headlines RESTART IDENTITY;")
        
        # Load NYSE Securities
        print("Bulk loading nyse_securities...")
        with cur.copy("COPY nyse_securities (ticker, create_date, nyse_security, sector, industry, headquarter) FROM STDIN") as copy:
            for row in securities_df.iter_rows():
                copy.write_row(row)


        # Load NYSE Prices
        print("Bulk loading nyse_prices...")
        with cur.copy("COPY nyse_prices (ticker, trade_date, open_price, close_price, high_price, low_price, volume) FROM STDIN") as copy:
            for row in prices_df.iter_rows():
                copy.write_row(row)
                
        # Load News Headlines with Embeddings
        print("Bulk loading news_headlines with vectors...")
        with cur.copy("COPY news_headlines (publish_date, headline, embedding) FROM STDIN") as copy:
            for i, row in enumerate(headlines_df.iter_rows()):
                # row is (publish_date, headline), we append the corresponding numpy array converted to a list
                copy.write_row((row[0], row[1], embeddings[i]))

        print("Building HNSW vector index all at once...")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS hnsw_headline_idx 
            ON news_headlines 
            USING hnsw (embedding vector_cosine_ops);
        """)
        print("HNSW graph built successfully!")

    conn.commit()