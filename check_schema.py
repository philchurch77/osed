import psycopg2

conn = psycopg2.connect(
    "postgresql://osed_test_db_user:agpUdEHXCZBUxuQADKcCYHfGew2h6xW0@dpg-d7vjukfaqgkc739b0ng0-a.frankfurt-postgres.render.com/osed_test_db",
    sslmode="require",
)
cur = conn.cursor()

tables = [
    "review_indeptharea",
    "review_indepthsubsection",
    "review_indepthreview",
    "review_indepthresponse",
    "django_migrations",
]

for table in tables:
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position",
        [table],
    )
    cols = [r[0] for r in cur.fetchall()]
    print(f"\n{table}:")
    print("  " + ", ".join(cols) if cols else "  TABLE DOES NOT EXIST")

print("\n--- Applied migrations (review app) ---")
cur.execute("SELECT name FROM django_migrations WHERE app = 'review' ORDER BY id")
for r in cur.fetchall():
    print(" ", r[0])

conn.close()
