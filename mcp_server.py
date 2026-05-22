import os
import psycopg
from fastmcp import FastMCP
from sentence_transformers import SentenceTransformer

# define database connection
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

# Set hard limits for query results
MAX_ROWS = int(os.environ.get("MAX_ROWS", "50")) # max allowed rows
MAX_CELL_CHARS = int(os.environ.get("MAX_CELL_CHARS", "20")) # character limit per cell value
MAX_RESPONSE_CHARS = int(os.environ.get("MAX_RESPONSE_CHARS", "4000")) # total output character limit

# define sentence encoder
ENCODER_MODEL = os.environ.get("ENCODER_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# initialize mcp and sentence encoder
mcp = FastMCP("financial_data_server")
model = SentenceTransformer(ENCODER_MODEL)

def _normalize_sql_query(sql_query: str) -> str:
    # remove whitespace and semicolon
    return sql_query.strip().rstrip(";").strip()


def _validate_read_only_sql(sql_query: str, conn: psycopg.Connection | None = None) -> str | None:
    normalized_query = _normalize_sql_query(sql_query)
    if not normalized_query:
        return "Error: SQL query is empty."

    lowered_query = normalized_query.lower()
    # prevent multiple calls
    if ";" in normalized_query:
        return "Error: Only a single SQL statement is permitted."

    if not lowered_query.startswith(("select", "with")):
        return "Error: Only read-only SELECT queries are permitted."

    forbidden_keywords = ["insert", "update", "delete", "drop", "truncate", "alter"]
    if any(keyword in lowered_query for keyword in forbidden_keywords):
        return "Error: Read-only access permitted. Modifications are strictly blocked."

    owns_connection = conn is None

    try:
        validation_conn = conn or psycopg.connect(CONN_STR)
        with validation_conn.cursor() as cur:
            cur.execute(f"EXPLAIN {normalized_query}")
    except Exception as exc:
        return f"Invalid SQL query: {str(exc)}"
    finally:
        if owns_connection:
            validation_conn.close()

    return None

def _truncate_text(value: object, limit: int = MAX_CELL_CHARS) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."

# Tool 1: Structured SQL Engine for NYSE Data
@mcp.tool()
def query_nyse_market_data(sql_query: str) -> str:
    """
    Executes a read-only SQL query against the NYSE tables.
        Use this tool to fetch financial fundamentals or price history.

        Input:
        - sql_query: A single PostgreSQL read-only query that starts with SELECT or WITH.
            The query must only read data and must not contain multiple statements.
            Prefer adding your own LIMIT when you only need a small sample.

        Available tables and columns:
        - nyse_securities (ticker, create_date, nyse_security, sector, industry, headquarter)
        - nyse_prices (ticker, trade_date, open_price, close_price, high_price, low_price, volume)

        Output:
        - On success, returns pipe-delimited text with a header row, separator line, and data rows.
        - Large results are truncated by server-side limits on row count, cell length, and total response length.
        - If truncation happens, the output includes a final line indicating that rows were truncated.
        - On failure, returns a plain-text error string beginning with Error:, Invalid SQL query:, or Database Error:.

        Example output:
        ticker | trade_date | close_price
        ----------------------------------------
        AAPL | 2024-01-02 | 185.64
        MSFT | 2024-01-02 | 374.22
    """
    try:
        with psycopg.connect(CONN_STR) as conn:
            validation_error = _validate_read_only_sql(sql_query, conn)
            if validation_error:
                return validation_error

            with conn.cursor() as cur:
                cur.execute(_normalize_sql_query(sql_query))
                # Fetch headers to make data highly legible for the LLM
                colnames = [desc[0] for desc in cur.description]
                rows = cur.fetchmany(MAX_ROWS + 1) # fetch limited amount
                
                if not rows:
                    return "Query returned 0 results."
                
                truncated = len(rows) > MAX_ROWS
                rows = rows[:MAX_ROWS]

                # initialize first lines with column names
                lines = [" | ".join(colnames), "-" * 40]

                # append each row, truncate if needed
                for row in rows:
                    lines.append(" | ".join(_truncate_text(val) for val in row))
                
                # indicate that rows were truncated
                if truncated:
                    lines.append(f"... output truncated to {MAX_ROWS} rows")

                result_str = "\n".join(lines)
                if len(result_str) > MAX_RESPONSE_CHARS:
                    result_str = result_str[: MAX_RESPONSE_CHARS - 3] + "..."
                return result_str
    except Exception as e:
        return f"Database Error: {str(e)}"

# Tool 2: Unstructured Semantic Search for News Headlines
@mcp.tool()
def search_news_headlines(
        query: str, 
        start_date: str | None = None,
        end_date: str | None = None, 
        limit: int = 5) -> str:
    """
    Performs a semantic vector search across historical news headlines.
    Use this to identify market sentiment, news events, or trends for a topic.

        Input:
        - query: A natural-language description of the company, topic, event, or theme to search for.
        - start_date: Optional start date in YYYY-MM-DD format. If provided, only headlines on or after this date are considered.
        - end_date: Optional end date in YYYY-MM-DD format. If provided, only headlines on or before this date are considered.
        - limit: Maximum number of matching headlines to return.

        Output:
        - On success, returns a plain-text list beginning with 'Relevant News Headlines Found:'
            followed by one bullet per match in this format:
            - [publish_date] headline text (Match Confidence: 87.5%)
        - If no matches are found, returns 'No matching headlines found.'
        - On failure, returns a plain-text error string beginning with 'Vector Search Error:'.
    """
    try:
        # Vectorize the incoming user query using the same embedding space
        query_vector = model.encode(query).tolist()
        
        # build SQL query
        # <=> cosine distance operator to scan our HNSW index
        sql = """
            SELECT publish_date, headline, (embedding <=> %s::vector) AS distance
            FROM news_headlines
        """
        params = [query_vector]

        filters = []
        if start_date is not None:
            filters.append("publish_date >= %s")
            params.append(start_date)

        if end_date is not None:
            filters.append("publish_date <= %s")
            params.append(end_date)

        if filters:
            sql += " WHERE " + " AND ".join(filters)

        sql += """
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
        """
        params.extend([query_vector, limit])

        with psycopg.connect(CONN_STR) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

                if not rows:
                    return "No matching headlines found."
                    
                # format the outputs for better interpretation
                output = "Relevant News Headlines Found:\n"
                for row in rows:
                    date, headline, distance = row
                    confidence = round((1 - distance) * 100, 1)
                    output += f"- [{date}] {headline} (Match Confidence: {confidence}%)\n"
                return output
    except Exception as e:
        return f"Vector Search Error: {str(e)}"

if __name__ == "__main__":
    # start server locally (used for test purposes)
    mcp.run(transport="http", host="0.0.0.0", port=8000)