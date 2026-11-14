import os
import re

import pandas as pd
import psycopg2
import streamlit as st

st.set_page_config(page_title="Titanic PostgreSQL Learning App", page_icon="\U0001F6A2", layout="wide")
st.title("Titanic Dataset: PostgreSQL + Streamlit")
st.caption("Explore SQL, database connectivity, and Titanic data.")


# ---------- Database configuration ----------
def get_db_config():
    """Read credentials from Streamlit secrets, else environment variables."""
    try:
        db = st.secrets["db"]
        config = {
            "host": db["host"],
            "port": int(db.get("port", 5432)),
            "dbname": db["dbname"],
            "user": db["user"],
            "password": db["password"],
        }
        if "sslmode" in db:
            config["sslmode"] = db["sslmode"]
        return config
    except Exception:
        config = {
            "host": os.getenv("PGHOST", "localhost"),
            "port": int(os.getenv("PGPORT", "5432")),
            "dbname": os.getenv("PGDATABASE", "titanic_db"),
            "user": os.getenv("PGUSER", "titanic_app"),
            "password": os.getenv("PGPASSWORD", ""),
        }
        if os.getenv("PGSSLMODE"):
            config["sslmode"] = os.getenv("PGSSLMODE")
        return config


def get_connection():
    config = get_db_config()
    if not config.get("password"):
        raise ValueError("Database password is missing. Configure Streamlit secrets or PGPASSWORD.")
    return psycopg2.connect(**config, connect_timeout=5)


def read_query(sql, params=None):
    """Run a query in a read-only transaction and return a DataFrame."""
    conn = get_connection()
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            if cursor.description is None:
                raise ValueError("The query did not return a result set.")
            columns = [d[0] for d in cursor.description]
            return pd.DataFrame(cursor.fetchall(), columns=columns)
    finally:
        conn.rollback()
        conn.close()


@st.cache_data(ttl=30)
def get_database_status():
    result = read_query(
        "SELECT current_database() AS database_name, "
        "current_schema() AS current_schema, version() AS postgres_version"
    )
    return result.iloc[0].to_dict()


try:
    db_status = get_database_status()
    st.success("Connected to PostgreSQL: " + db_status["database_name"])
except Exception as error:
    st.error("Could not connect to PostgreSQL.")
    st.info("Check the host, port, database name, username, password, network access, and table permissions.")
    with st.expander("Connection error details"):
        st.code(str(error))
    st.stop()

st.sidebar.title("Navigation")
st.sidebar.caption("Database: " + db_status["database_name"])
st.sidebar.caption("Schema: titanic_project")
if st.sidebar.button("Refresh database status"):
    get_database_status.clear()
    st.rerun()

dashboard_tab, explorer_tab, sql_tab, test_tab = st.tabs(
    ["Dashboard", "Data Explorer", "SQL Lab", "Interactive Test"]
)

LABELS = {0: "Did Not Survive", 1: "Survived"}


def survival_pivot(df, index):
    pivot = df.pivot(index=index, columns="survived", values="passenger_count").fillna(0)
    return pivot.rename(columns=LABELS)


# ---------- Tab 1: Dashboard ----------
with dashboard_tab:
    st.header("Passenger Dashboard")

    total_passengers = int(
        read_query("SELECT COUNT(*) AS n FROM titanic_project.passengers").iloc[0]["n"]
    )
    survivor_df = read_query(
        "SELECT survived, COUNT(*) AS passenger_count FROM titanic_project.passengers "
        "GROUP BY survived ORDER BY survived"
    )
    counts = {int(r["survived"]): int(r["passenger_count"]) for _, r in survivor_df.iterrows()}
    survived_count = counts.get(1, 0)
    not_survived_count = counts.get(0, 0)
    survival_rate = survived_count / total_passengers * 100 if total_passengers else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Passengers", f"{total_passengers:,}")
    c2.metric("Survived", f"{survived_count:,}")
    c3.metric("Did Not Survive", f"{not_survived_count:,}")
    c4.metric("Survival Rate", f"{survival_rate:.2f}%")

    st.divider()
    st.subheader("Survival by Passenger Class")
    class_df = read_query(
        "SELECT pclass, survived, COUNT(*) AS passenger_count FROM titanic_project.passengers "
        "GROUP BY pclass, survived ORDER BY pclass, survived"
    )
    class_pivot = survival_pivot(class_df, "pclass")
    class_pivot.index.name = "Passenger Class"
    st.bar_chart(class_pivot)
    st.caption("The chart shows passenger counts, not percentages.")

    st.subheader("Survival by Sex")
    sex_df = read_query(
        "SELECT sex, survived, COUNT(*) AS passenger_count FROM titanic_project.passengers "
        "GROUP BY sex, survived ORDER BY sex, survived"
    )
    st.bar_chart(survival_pivot(sex_df, "sex"))

    st.subheader("Missing Values")
    m = read_query(
        "SELECT COUNT(*) - COUNT(age) AS missing_age, "
        "COUNT(*) - COUNT(embarked) AS missing_embarked, "
        "COUNT(*) - COUNT(cabin) AS missing_cabin FROM titanic_project.passengers"
    ).iloc[0]
    st.dataframe(
        pd.DataFrame({
            "Column": ["Age", "Embarked", "Cabin"],
            "Missing Values": [int(m["missing_age"]), int(m["missing_embarked"]), int(m["missing_cabin"])],
        }),
        hide_index=True,
    )


# ---------- Tab 2: Data Explorer ----------
with explorer_tab:
    st.header("Passenger Data Explorer")

    selected_class = st.multiselect("Select Passenger Class", [1, 2, 3], default=[1, 2, 3])
    selected_sex = st.multiselect("Select Sex", ["female", "male"], default=["female", "male"])
    selected_survival = st.multiselect(
        "Select Survival Status", [0, 1], default=[0, 1], format_func=lambda x: LABELS[x]
    )
    row_limit = st.slider("Maximum records to display", 10, 891, 100, step=10)

    if st.button("Load Passenger Data"):
        if not selected_class or not selected_sex or not selected_survival:
            st.warning("Select at least one value in every filter.")
        else:
            query = """
                SELECT passengerid, name, sex, age, sibsp, parch, embarked,
                       ticket, fare, cabin, pclass, survived
                FROM titanic_project.passengers
                WHERE pclass = ANY(%s) AND sex = ANY(%s) AND survived = ANY(%s)
                ORDER BY passengerid
                LIMIT %s
            """
            try:
                filtered_df = read_query(query, (selected_class, selected_sex, selected_survival, row_limit))
                st.success(f"Retrieved {len(filtered_df)} records.")
                st.dataframe(filtered_df, hide_index=True)
                st.download_button(
                    "Download Displayed Data as CSV",
                    data=filtered_df.to_csv(index=False),
                    file_name="titanic_filtered_data.csv",
                    mime="text/csv",
                )
            except Exception as error:
                st.error("Unable to retrieve passenger data.")
                st.code(str(error))

    st.divider()
    st.subheader("Original Staging Data")
    if st.button("Load Staging Table Preview"):
        st.dataframe(
            read_query("SELECT * FROM titanic_project.titanic_staging ORDER BY passengerid LIMIT 20"),
            hide_index=True,
        )


# ---------- Tab 3: SQL Lab ----------
EXAMPLE_QUERIES = {
    "Show 10 passengers": "SELECT *\nFROM titanic_project.passengers\nLIMIT 10",
    "Count passengers": "SELECT COUNT(*) AS total_passengers\nFROM titanic_project.passengers",
    "Survival distribution": (
        "SELECT survived, COUNT(*) AS passenger_count\nFROM titanic_project.passengers\n"
        "GROUP BY survived\nORDER BY survived"
    ),
    "Average age by class": (
        "SELECT pclass, ROUND(AVG(age)::numeric, 2) AS average_age\n"
        "FROM titanic_project.passengers\nGROUP BY pclass\nORDER BY pclass"
    ),
    "Survival rate by sex": (
        "SELECT sex, COUNT(*) AS total_passengers, SUM(survived) AS survivors,\n"
        "       ROUND(100.0 * SUM(survived) / COUNT(*), 2) AS survival_percentage\n"
        "FROM titanic_project.passengers\nGROUP BY sex\nORDER BY sex"
    ),
    "Passengers with missing ages": (
        "SELECT passengerid, name, sex, age, pclass\nFROM titanic_project.passengers\n"
        "WHERE age IS NULL\nORDER BY passengerid\nLIMIT 50"
    ),
    "Fare statistics by class": (
        "SELECT pclass, COUNT(*) AS passenger_count,\n"
        "       ROUND(AVG(fare)::numeric, 2) AS average_fare,\n"
        "       ROUND(MIN(fare)::numeric, 2) AS minimum_fare,\n"
        "       ROUND(MAX(fare)::numeric, 2) AS maximum_fare\n"
        "FROM titanic_project.passengers\nGROUP BY pclass\nORDER BY pclass"
    ),
}

BLOCKED = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE",
    "COPY", "CALL", "DO", "SET", "RESET", "PG_SLEEP", "PG_READ_FILE", "PG_WRITE_FILE",
    "LO_IMPORT", "LO_EXPORT",
]


def validate_read_only_query(sql):
    cleaned = sql.strip()
    if not cleaned:
        return False, "Enter a SQL query."
    cleaned = cleaned.rstrip(";").strip()
    if ";" in cleaned:
        return False, "Enter one SQL statement at a time."
    if not re.match(r"^(SELECT|WITH)\b", cleaned, flags=re.IGNORECASE):
        return False, "Only SELECT and WITH queries are allowed."
    for word in BLOCKED:
        if re.search(rf"\b{word}\b", cleaned, flags=re.IGNORECASE):
            return False, "The query contains a restricted keyword or function."
    return True, cleaned


with sql_tab:
    st.header("SQL Practice Lab")
    st.write("Execute read-only SELECT and WITH queries against the Titanic database.")
    st.warning("This is a basic learning interface, not a production-grade SQL sandbox.")

    selected_example = st.selectbox("Choose an example query", list(EXAMPLE_QUERIES))
    sql_text = st.text_area(
        "SQL Query", value=EXAMPLE_QUERIES[selected_example], height=220, key=f"sql_{selected_example}"
    )

    if st.button("Run SQL Query"):
        ok, sql_or_msg = validate_read_only_query(sql_text)
        if not ok:
            st.error(sql_or_msg)
        else:
            try:
                result_df = read_query(sql_or_msg)
                st.success(f"Query executed successfully. Rows returned: {len(result_df)}")
                st.dataframe(result_df, hide_index=True)
                st.download_button(
                    "Download Query Result",
                    data=result_df.to_csv(index=False),
                    file_name="sql_query_result.csv",
                    mime="text/csv",
                )
            except Exception as error:
                st.error("The query could not be executed. Check the SQL syntax and permissions.")
                with st.expander("Error details"):
                    st.code(str(error))

    st.divider()
    st.subheader("Practice Questions")
    st.markdown(
        """
1. Display the first 20 passengers.
2. Count passengers in each passenger class.
3. Calculate the average fare.
4. Find passengers whose age is missing.
5. Calculate survival rates by sex.
6. Count passengers by embarkation port.
7. Find the maximum fare in each class.
8. Compare survivors and non-survivors by class.
"""
    )


# ---------- Tab 4: Interactive Test ----------
QUESTIONS = [
    ("1. What is a database used for?",
     ["Storing and managing data", "Designing slides", "Replacing an operating system", "Compiling Python code"],
     0, "A database stores and organizes data for retrieval and management."),
    ("2. What is a PostgreSQL schema?",
     ["A CSV file", "A namespace for database objects", "A Python variable", "A password"],
     1, "A schema organizes tables and other database objects."),
    ("3. Which command creates a schema?",
     ["MAKE SCHEMA", "NEW SCHEMA", "CREATE SCHEMA", "INSERT SCHEMA"],
     2, "CREATE SCHEMA creates a schema in PostgreSQL."),
    ("4. What does psql \\copy do?",
     ["Deletes a table", "Imports or exports data through the client", "Creates a database", "Changes a password"],
     1, "\\copy transfers file data through the psql client process."),
    ("5. What does HEADER TRUE mean?",
     ["The first CSV row contains column names", "The first data row is deleted",
      "Every column is a primary key", "NULL values are forbidden"],
     0, "HEADER TRUE skips the CSV column-name row."),
    ("6. How many original records exist?", ["714", "889", "891", "204"],
     2, "The original dataset contains 891 records."),
    ("7. How many ages are missing?", ["177", "204", "687", "2"],
     0, "891 total rows minus 714 available ages equals 177 missing values."),
    ("8. What does a primary key enforce?",
     ["All rows have the same value", "Unique, non-NULL key values", "Every column stores text",
      "Every passenger has an age"],
     1, "Primary keys uniquely identify records and cannot contain NULL values."),
    ("9. Which function counts rows?", ["TOTAL()", "NUMBER()", "COUNT(*)", "ROWS()"],
     2, "COUNT(*) counts all rows in the result."),
    ("10. What does GROUP BY do?",
     ["Groups rows with matching values", "Deletes duplicate rows", "Creates a database", "Imports a CSV file"],
     0, "GROUP BY forms groups for aggregate calculations."),
    ("11. Which SQL command retrieves data?", ["SHOW ROWS", "SELECT", "DISPLAY", "FETCH TABLE"],
     1, "SELECT retrieves data from tables and queries."),
    ("12. What is Streamlit used for?",
     ["Building interactive Python web applications", "Replacing PostgreSQL",
      "Automatically creating schemas", "Replacing the operating system"],
     0, "Streamlit provides tools for interactive Python web applications."),
    ("13. Which library connects Python to PostgreSQL?", ["matplotlib", "psycopg2", "turtle", "random"],
     1, "psycopg2 is the PostgreSQL adapter used here."),
    ("14. What does COUNT(age) count?",
     ["All rows including NULL ages", "Only NULL ages", "Non-NULL age values", "Only ages equal to zero"],
     2, "COUNT(column) excludes NULL values."),
    ("15. What does survived = 1 mean?",
     ["The passenger survived", "The passenger did not survive", "The age is missing",
      "The passenger travelled first class"],
     0, "A value of 1 represents survival in this dataset."),
]

with test_tab:
    st.header("PostgreSQL and Streamlit Test")
    st.write("Answer all questions and submit the test to view the score and explanations.")

    with st.form("titanic_quiz"):
        answers = []
        for i, (text, options, _, _) in enumerate(QUESTIONS):
            answers.append(
                st.radio(text, options=list(range(len(options))),
                         format_func=lambda j, o=options: o[j], index=None, key=f"question_{i}")
            )
            st.divider()
        submitted = st.form_submit_button("Submit Test")

    if submitted:
        unanswered = [i + 1 for i, a in enumerate(answers) if a is None]
        if unanswered:
            st.warning("Answer all questions before submitting. Unanswered questions: "
                       + ", ".join(map(str, unanswered)))
        else:
            score = sum(1 for i, a in enumerate(answers) if a == QUESTIONS[i][2])
            st.session_state["quiz_result"] = {
                "score": score, "percentage": score / len(QUESTIONS) * 100, "answers": answers,
            }

    if "quiz_result" in st.session_state:
        res = st.session_state["quiz_result"]
        st.subheader("Test Results")
        c1, c2, c3 = st.columns(3)
        c1.metric("Correct Answers", f"{res['score']} / {len(QUESTIONS)}")
        c2.metric("Percentage", f"{res['percentage']:.2f}%")
        if res["percentage"] >= 80:
            feedback = "Excellent work!"
        elif res["percentage"] >= 60:
            feedback = "Good effort! Review the explanations."
        else:
            feedback = "Keep practicing SQL and PostgreSQL."
        c3.metric("Feedback", feedback)
        st.progress(res["percentage"] / 100)

        st.subheader("Answer Review")
        for i, (text, options, correct, explanation) in enumerate(QUESTIONS):
            user_answer = res["answers"][i]
            if user_answer == correct:
                st.success(f"Question {i + 1}: Correct")
            else:
                st.error(f"Question {i + 1}: Incorrect")
                st.write("Your answer: " + options[user_answer])
                st.write("Correct answer: " + options[correct])
            st.info(explanation)

        if st.button("Retake Test"):
            del st.session_state["quiz_result"]
            st.rerun()

st.divider()
st.caption("Titanic Dataset Learning Project | Python + Streamlit + PostgreSQL")
