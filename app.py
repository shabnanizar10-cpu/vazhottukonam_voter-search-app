import streamlit as st
import sqlite3
import pandas as pd
import os

# --- CONFIGURATION & DATABASE SETUP ---
DB_FILE = "voter_data.db"

# Map the CSV headers (on the right) to the database column names (on the left)
CSV_COLUMNS_TO_READ = {
    'part_serial_number_raw': 'Serial No.',             
    'name': 'Name',
    'ward_house_raw': 'OldWard No/ House No.',        
    'house_name': 'House Name',  # <--- NEW MAPPING
    'gender_age_raw': 'Gender / Age',                  
    'sec_id': 'New SEC ID No.'
}

def init_db():
    """Initialize the SQLite database with the required schema."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS voters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sec_id TEXT UNIQUE,
            part_serial_number TEXT,
            ward TEXT,
            polling_station TEXT,
            name TEXT,
            gender TEXT,
            age INTEGER,
            house_name TEXT,  -- <--- NEW COLUMN IN DB
            source_file TEXT
        )
    ''')
    conn.commit()
    conn.close()


def process_csv_file(uploaded_file):
    """
    Reads data from a CSV file, performs necessary transformations, 
    and prepares it for database insertion.
    """
    try:
        # 1. Read the CSV file
        df = pd.read_csv(uploaded_file, encoding='latin1')
        
        # 2. Rename columns for internal processing
        df_clean = df.rename(columns={v: k for k, v in CSV_COLUMNS_TO_READ.items()})
        
        # 3. Data Extraction and Transformation
        
        # 3.1. Extract Polling Station Name from the filename
        file_name = uploaded_file.name
        polling_station_raw = file_name.rsplit('_', 1)[-1].rsplit('-', 1)[-1].replace('.csv', '')
        df_clean['polling_station'] = polling_station_raw

        # 3.2. Split Gender / Age
        df_clean[['gender', 'age_raw']] = df_clean['gender_age_raw'].astype(str).str.split(' / ', n=1, expand=True)
        df_clean['gender'] = df_clean['gender'].str.upper().str.strip()
        df_clean['age'] = pd.to_numeric(df_clean['age_raw'], errors='coerce').fillna(0).astype(int)

        # 3.3. Extract Ward Number
        df_clean['ward'] = df_clean['ward_house_raw'].astype(str).str.split('/', n=1, expand=True)[0]
        
        # 3.4. Finalize other columns
        df_clean['part_serial_number'] = df_clean['part_serial_number_raw'].astype(str)
        df_clean['sec_id'] = df_clean['sec_id'].astype(str).str.upper().str.strip()
        df_clean['source_file'] = uploaded_file.name
        
        # 4. Select final required columns in DB order (House Name added here)
        final_db_columns = [
            'sec_id', 'part_serial_number', 'ward', 'polling_station', 
            'name', 'gender', 'age', 'house_name', 'source_file' 
        ]
        
        df_final = df_clean[final_db_columns]

        # Convert DataFrame to a list of tuples for SQLite insertion
        voters_list = [tuple(row) for row in df_final.itertuples(index=False)]
        
        return voters_list

    except Exception as e:
        st.error(f"Error processing {uploaded_file.name}. Please check the file's header names or data format.")
        st.error(f"Details: {e}")
        return []

def save_to_db(voters):
    """Saves a list of voter tuples to the database, ignoring duplicates by SEC ID."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # SQL query is updated to include 'house_name' and use 9 placeholders
    insert_sql = f'''
        INSERT OR IGNORE INTO voters 
        (sec_id, part_serial_number, ward, polling_station, name, gender, age, house_name, source_file)
        VALUES ({', '.join(['?'] * 9)})
    '''
    
    try:
        c.executemany(insert_sql, voters)
        conn.commit()
        count = c.rowcount
    except sqlite3.Error as e:
        st.error(f"Database error during insert: {e}")
        count = 0
    finally:
        conn.close()
    return count

# --- SEARCH LOGIC ---
def search_voter(query_type, query_value):
    # This selects all columns, including the new 'house_name'
    conn = sqlite3.connect(DB_FILE)
    
    if query_type == "By SEC ID":
        df = pd.read_sql_query("SELECT * FROM voters WHERE sec_id = ?", conn, params=(query_value.upper(),))
    else:
        df = pd.read_sql_query("SELECT * FROM voters WHERE name LIKE ?", conn, params=(f'%{query_value}%',))
    
    conn.close()
    return df

# --- USER INTERFACE (STREAMLIT) ---
def main():
    st.set_page_config(page_title="Voter Data Extractor", layout="wide")
    st.title("🗳️ Voter List Search System")
    st.subheader("Centralized Database for Polling Stations")

    # Initialize DB (This will create the 'house_name' column if the DB file doesn't exist yet)
    init_db()

    # Create Tabs
    tab1, tab2 = st.tabs(["📂 Upload/Manage Data", "🔍 Search Voter"])

    # --- TAB 1: UPLOAD ---
    with tab1:
        st.header("Bulk Upload CSV Files")
        st.warning("Upload your CSV files **one time** to build the master database.")
        
        uploaded_files = st.file_uploader("Choose your CSV files", type=["csv"], accept_multiple_files=True)
        
        if uploaded_files:
            if st.button(f"Process {len(uploaded_files)} CSV Files and Load Database"):
                total_new_records = 0
                st.info("Starting batch processing...")
                
                for file in uploaded_files:
                    voter_data = process_csv_file(file)
                    if voter_data:
                        inserted_count = save_to_db(voter_data)
                        total_new_records += inserted_count
                        st.success(f"File **{file.name}** processed: **{inserted_count}** new unique records added.")
                    else:
                        st.warning(f"File **{file.name}** processed, but no valid data could be inserted.")

                st.balloons()
                st.success(f"**Batch Complete!** Total new unique records added: **{total_new_records}**.")
                
        st.subheader("Database Status")
        conn = sqlite3.connect(DB_FILE)
        count_df = pd.read_sql_query("SELECT COUNT(*) AS Total_Records FROM voters", conn)
        conn.close()
        st.metric(label="Total Records in Database", value=count_df['Total_Records'].iloc[0])


    # --- TAB 2: SEARCH ---
    with tab2:
        st.header("Search Database")
        
        col1, col2 = st.columns([1, 2])
        with col1:
            search_mode = st.radio("Search By:", ["By Name", "By SEC ID"])
        with col2:
            search_input = st.text_input("Enter Name or ID")
            search_btn = st.button("Find Voter")

        if search_btn and search_input:
            results = search_voter(search_mode, search_input)
            
            if not results.empty:
                st.success(f"Found {len(results)} record(s).")
                # Drop only the internal DB id and source file for clean display
                display_results = results.drop(columns=['id', 'source_file'])
                st.dataframe(display_results)
                
                # Download option
                csv = display_results.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "Download Results as CSV",
                    csv,
                    "search_results.csv",
                    "text/csv",
                    key='download-csv'
                )
            else:
                st.warning(f"No records found matching '{search_input}'.")

if __name__ == "__main__":
    main()