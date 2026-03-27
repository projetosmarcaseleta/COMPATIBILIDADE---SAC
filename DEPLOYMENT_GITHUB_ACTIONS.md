# Guia: Deploy Automático do GitHub para a Hostinger VPS

Para que toda vez que você faça um `git push` no seu computador o servidor da Hostinger atualize sozinho, usaremos o **GitHub Actions**.

Existem duas partes nisso:
1. Dar permissão para o Hostinger baixar do GitHub (Deploy Key).
2. Dar permissão para o GitHub avisar o Hostinger para atualizar as peças (GitHub Secrets & Actions).

---

## 🚀 PASSO 1: Fazer o servidor "falar" com o GitHub (Deploy Key)

Como seu repositório é privado, o servidor precisa de uma chave especial para rodar o `git pull` sem ficar pedindo sua senha.

No terminal da **Hostinger (SSH)**, rode este comando apertando `ENTER` para todas as perguntas (não digite nenhuma senha):
```bash
ssh-keygen -t ed25519 -C "vps-deploy"
```

Agora, **leia** a chave pública gerada rodando isto no terminal da Hostinger:
```bash
cat ~/.ssh/id_ed25519.pub
```
Gere copiar o texto enorme que vai aparecer (começa com `ssh-ed25519...`).

**No GitHub:**
1. Vá na tela do seu print (**Deploy keys**).
2. Clique em **"Add deploy key"**.
3. **Title:** Coloque `Hostinger VPS`.
4. **Key:** Cole o texto enorme que você copiou.
5. Clique em **Add key**.

---

## 🚀 PASSO 2: Fazer o GitHub "avisar" o servidor (Secrets)

Agora precisamos fazer o inverso: dar a "chave" do seu servidor para que o robô do GitHub Modules possa entrar lá e rodar `git pull`.

No terminal da **Hostinger (SSH)**, vamos ler a chave PRIVADA:
```bash
cat ~/.ssh/id_ed25519
```
Copie TODO o bloco de texto (incluindo as linhas `-----BEGIN OPENSSH PRIVATE KEY-----` e o bloco inteiro até o `-----END OPENSSH PRIVATE KEY-----`).

**No GitHub:**
1. No menu lateral das configurações (o mesmo do seu print), vá em **Secrets and variables** > **Actions** (logo abaixo de Deploy keys).
2. Clique no botão verde **"New repository secret"**.
3. Vamos criar 3 segredos:

* **Segredo 1 (A Chave):**
  * **Name:** `VPS_SSH_KEY`
  * **Secret:** Cole o bloco enorme da chave privada que você acabou de copiar.
* **Segredo 2 (O IP do Servidor):**
  * **Name:** `VPS_HOST`
  * **Secret:** Cole o IP numérico do seu servidor Hostinger (ex: `193.123.1.20`).
* **Segredo 3 (O Usuário):**
  * **Name:** `VPS_USERNAME`
  * **Secret:** Escreva `root`

Nesta mesma etapa, como você quer dar acesso usando essa chave, no termial da **Hostinger**, precisamos autorizar a própria chave de acessar a máquina. Rode:
```bash
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
```

---

## 🚀 PASSO 3: Criar o Robô Automático (Action Flow)

No seu computador, no seu projeto local (o VSCode), vamos criar o arquivo de automação.

1. Na raiz do projeto, crie uma pasta chamada `.github`.
2. Dentro dela, crie uma pasta chamada `workflows`.
3. Dentro dessa pasta `workflows`, crie um arquivo chamado `deploy.yml`.

O caminho ficará: `.github/workflows/deploy.yml`

Cole este conteúdo dentro do `deploy.yml`:

```yaml
name: Deploy Automático Hostinger

on:
  push:
    branches:
      - main  # Se o seu branch principal for 'master', troque aqui.

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
    - name: Executando Comandos no Servidor VPS via SSH
      uses: appleboy/ssh-action@v1.0.3
      with:
        host: ${{ secrets.VPS_HOST }}
        username: ${{ secrets.VPS_USERNAME }}
        key: ${{ secrets.VPS_SSH_KEY }}
        script: |
          cd ~/projetos/COMPATIBILIDADE---SAC
          git pull origin main
          source venv/bin/activate
          pip install -r requirements.txt
          pm2 restart fiat-eper
```

## 🚀 Como testar?

Basta você **commitar** esse novo arquivo `deploy.yml` e fazer um `git push` no seu computador.
Assim que enviar para o GitHub, clique na aba **"Actions"** no menuzinho superior do GitHub. Você vai ver o seu robô trabalhando, acessando o servidor Hostinger e atualizando o site sozinho! 🎉
