# Job Tracker (Firebase)
1. Firebase console -> create project -> Build -> Firestore Database -> Create database.
2. Project settings -> Service accounts -> Generate new private key (downloads a JSON).
3. Copy the JSON values into `.streamlit/secrets.toml` under [firebase].
4. `pip install -r requirements.txt`
5. `streamlit run app.py`
