import streamlit as st
from fastapi.testclient import TestClient
from backend import app

# Buat client FastAPI untuk simulasi HTTP lokal
client = TestClient(app)

st.title("Streamlit + FastAPI (tanpa uvicorn)")

st.write("Klik tombol untuk memanggil endpoint `/test` dari FastAPI:")

if st.button("Call /test"):
    response = client.get("/test")  # sama seperti: curl http://localhost/test
    st.json(response.json())