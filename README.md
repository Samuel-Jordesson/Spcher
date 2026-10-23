# Spcher

Aplicação web baseada em Python (Flask) utilizando `yt-dlp` e `ffmpeg` para download e processamento de mídias do YouTube.

## Nota sobre Hospedagem (Vercel)

Os arquivos de configuração para nuvem (`vercel.json` e `api/index.py`) estão presentes no repositório com o objetivo de deploy na **Vercel**. No entanto, **os servidores da Vercel e de outras plataformas de nuvem são bloqueados pelo YouTube**. Portanto, para testes e uso atual, a aplicação deve ser executada localmente na sua máquina ou servidor dedicado.

---

## Instalação e Configuração

Siga os passos abaixo no terminal (CMD, PowerShell ou Linux) dentro da pasta do projeto para configurar o ambiente.

### 1. Criar o ambiente virtual

```cmd
python -m venv venv
```

### 2. Ativar o ambiente virtual

**Windows (CMD):**

```cmd
venv\Scripts\activate.bat
```

**Windows (PowerShell):**

```powershell
.\venv\Scripts\Activate.ps1
```

### 3. Instalar as dependências

```cmd
pip install -r requirements.txt
```

> **Nota:** Certifique-se de que o **FFmpeg** também está instalado e configurado nas variáveis de ambiente do seu sistema.

---

## Como Executar o Programa

Com o ambiente virtual ativado e na pasta raiz do projeto, execute:

```cmd
python baixar_musicas_servidor_7428.py
```

Após iniciar, abra o navegador e acesse:

- **Local:** http://localhost:7428
