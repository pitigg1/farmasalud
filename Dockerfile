# Imagen de producción (Render): compila el frontend y lo sirve junto con la API.
# Para desarrollo local se sigue usando backend/Dockerfile con docker compose.
FROM node:22-slim AS frontend
WORKDIR /front
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/main.py .
COPY --from=frontend /front/dist ./static
# Render indica el puerto en la variable PORT.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
