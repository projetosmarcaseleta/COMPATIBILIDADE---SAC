# Guia de Implantação: Fiat ePER Web no Hostinger VPS

Este projeto utiliza **Playwright (Chromium)** e **Flask**. Para que ele funcione no Hostinger, você **deve usar um VPS** (Servidor Virtual Privado) e não a hospedagem compartilhada (hPanel comum), pois a hospedagem compartilhada não permite instalar as bibliotecas do sistema necessárias para rodar o navegador em segundo plano.

## Passo 1: Preparar o Servidor (SSH)

Conecte-se ao seu VPS via terminal e atualize o sistema:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv nginx -y
```

## Passo 2: Clonar o Repositório

```bash
git clone https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
cd SEU_REPOSITORIO
```

## Passo 3: Configurar o Ambiente Python

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
# INSTALAR DEPENDÊNCIAS DO SISTEMA PARA O CHROMIUM (CRÍTICO)
sudo playwright install-deps
```

## Passo 4: Configurar o Nginx

Use o arquivo `nginx_fiat_parts.conf` que criamos. 

1. Copie para a pasta do Nginx:
   ```bash
   sudo cp nginx_fiat_parts.conf /etc/nginx/sites-available/fiat_parts
   ```
2. Mude o `server_name` no arquivo para o seu domínio.
3. Ative o site:
   ```bash
   sudo ln -s /etc/nginx/sites-available/fiat_parts /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

## Passo 5: Manter o Servidor Online (PM2)

Para o servidor não fechar quando você sair do terminal:

```bash
sudo apt install npm -y
sudo npm install -g pm2
pm2 start fiat_server.py --name "fiat-eper" --interpreter ./venv/bin/python
pm2 save
pm2 startup
```

## Passo 6: Apontar o Domínio (DNS)

No painel do seu domínio (Hostinger ou Registro.br):
1. Adicione um **Registro A** apontando para o **IP do seu VPS**.
2. Aguarde a propagação.

---
💡 **Dica de SSL (HTTPS):**
Após apontar o domínio, rode:
`sudo apt install certbot python3-certbot-nginx -y`
`sudo certbot --nginx -d seu_dominio.com.br`
