import psycopg2
import requests
import json

###
#
# Diese Funktion ist ein Beispiel wie Daten aus einer Postgresdatenbank in den Solrcore geladen werden.
# Auch sehr große Datensätze können durch den Streaming Ansatz in Chunks übertragen werden, was eine hohe Performanz erlaubt.
# Wichtig ist, dass die Felder, die bei der SQL-Anfrage zurückgeliefert werden namentlich mit den Feldern im Solr-Core übereinstimmen.
#
###

# ---- CONFIG ----
PG_HOST = "PG_HOST"
PG_DB = "PG_DB"
PG_USER = "PG_USER"
PG_PASSWORD = "PG_PASSWORD"
PG_PORT = 5432

SOLR_URL = "http://127.0.0.1:8983/solr/addresses/update?commit=true"

CHUNK_SIZE = 10000

# ---- POSTGRES QUERY ----
# Adjust to your real table/column names
SQL = """
select * from schema.table;
"""

def stream_pg_chunks(cur, chunk_size=10000):
    """Generator that yields results in chunks."""
    while True:
        rows = cur.fetchmany(chunk_size)
        if not rows:
            break
        yield rows

def push_to_solr(docs):
    headers = {"Content-Type": "application/json"}
    r = requests.post(SOLR_URL, data=json.dumps(docs), headers=headers)
    if r.status_code != 200:
        print("Solr error:", r.text)
    else:
        print(f"Sent {len(docs)} docs to Solr.")

def main():
    print("Connecting to PostgreSQL...")

    conn = psycopg2.connect(
        host=PG_HOST,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
        port=PG_PORT,
    )

    # Server-side cursor (important for huge tables)
    cur = conn.cursor(name="address_cursor")
    cur.itersize = CHUNK_SIZE

    cur.execute(SQL)

    # Fetch the first chunk to get description
    first_chunk = cur.fetchmany(CHUNK_SIZE)
    colnames = [desc[0] for desc in cur.description]

    # Process first chunk
    if first_chunk:
        docs = [dict(zip(colnames, row)) for row in first_chunk]
        push_to_solr(docs)
        total = len(first_chunk)
        chunk_counter = 1
    else:
        total = 0
        chunk_counter = 0

    for chunk in stream_pg_chunks(cur, CHUNK_SIZE):
        docs = []
        for row in chunk:
            row_dict = dict(zip(colnames, row))
            docs.append(row_dict)

        push_to_solr(docs)

        chunk_counter += 1
        total += len(chunk)
        print(f"Chunk {chunk_counter} done — total {total}")

    cur.close()
    conn.close()

    print("All data processed.")

if __name__ == "__main__":
    main()
