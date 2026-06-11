# Frontend image: Streamlit UI (E10-S1 AC-1).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY frontend-requirements.txt ./
RUN pip install --no-cache-dir -r frontend-requirements.txt

COPY frontend ./frontend

EXPOSE 8501

# BACKEND_URL is injected by compose so the UI can reach the backend service
# over the shared network (E10-S1 AC-3). Bind to all interfaces for the container.
CMD ["streamlit", "run", "frontend/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true"]
