cd C:\project\heritage-rag-agent\backend
python -m venv venv
venv\Scripts\activate
pip install requests pandas google-genai psycopg2-binary python-dotenv
pip install -r requirements.txt
uvicorn main:app --reload --port 8000