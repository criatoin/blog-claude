# Dockerfile — +blog autonomo
# Base: Python 3.12 slim

FROM python:3.12-slim

WORKDIR /app

# Dependências do sistema necessárias para Pillow e outras libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libjpeg-dev \
    libpng-dev \
    libwebp-dev \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código do projeto
COPY . .

# Cria diretório de temporários
RUN mkdir -p .tmp

# Variáveis de ambiente são injetadas via .env ou env_file no docker-compose
# Não copie .env para a imagem

RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]
