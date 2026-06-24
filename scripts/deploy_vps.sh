#!/bin/bash
# Deploy na VPS (sem git pull — rode git pull antes ou use deploy remoto completo)
set -e

APP_DIR="${APP_DIR:-$HOME/projetos/COMPATIBILIDADE---SAC}"
cd "$APP_DIR"

echo "=== Commit atual ==="
git rev-parse --short HEAD
grep -o 'Versão: [^|]*' fiat_server.py | head -1 || true

echo "=== Dependencias ==="
source venv/bin/activate
pip install -r requirements.txt -q

echo "=== Nginx ==="
if [ -f nginx_fiat_parts.conf ]; then
  # Copia para sites-available
  cp nginx_fiat_parts.conf /etc/nginx/sites-available/fiat_parts
  # Garante que sites-enabled tambem esta atualizado (arquivo direto ou symlink)
  if [ -L /etc/nginx/sites-enabled/fiat_parts ]; then
    echo "sites-enabled/fiat_parts eh symlink, sites-available atualizado."
  elif [ -f /etc/nginx/sites-enabled/fiat_parts ]; then
    cp nginx_fiat_parts.conf /etc/nginx/sites-enabled/fiat_parts
    echo "sites-enabled/fiat_parts atualizado diretamente."
  else
    ln -sf /etc/nginx/sites-available/fiat_parts /etc/nginx/sites-enabled/fiat_parts
    echo "Symlink sites-enabled/fiat_parts criado."
  fi
  nginx -t && nginx -s reload && echo "Nginx recarregado com sucesso." || echo "AVISO: nginx -t falhou, config nao aplicada"
fi

echo "=== PM2 ==="
export EPER_READ_TIMEOUT=60
export EPER_BATCH_WORKERS=3
export WAITRESS_CHANNEL_TIMEOUT=300
pm2 delete fiat-eper 2>/dev/null || true
pm2 start fiat_server.py \
  --name fiat-eper \
  --interpreter "$APP_DIR/venv/bin/python" \
  --cwd "$APP_DIR"
pm2 save

sleep 3
HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5002/ || echo "000")
LIVE=$(curl -s http://127.0.0.1:5002/ | grep -o 'Versão: [^|]*' | head -1 || echo "nao detectada")
echo "HTTP: $HTTP | Versao: $LIVE"

if [ "$HTTP" != "200" ]; then
  pm2 logs fiat-eper --lines 30 --nostream
  exit 1
fi

echo "Deploy concluido."
