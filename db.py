
import psycopg2
import pandas as pd
import os

def get_connection():
    return psycopg2.connect(
        host="aws-1-ap-south-1.pooler.supabase.com",
        database="postgres",
        user="postgres.zsbzfuvsvkykgvmyuvxv",
        password=os.environ["SUPABASE_DB_PASSWORD"],
        port="5432",
        sslmode="require"
    )

if __name__ == "__main__":
    try:
        conn = get_connection()
        print("Supabase connection successful!")

        df = pd.read_sql_query(
            "SELECT current_database(), current_schema();",
            conn
        )
        print(df)
        conn.close()

    except Exception as e:
        print("Supabase connection failed:", e)