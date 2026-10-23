(
echo # Spcher
echo.
echo Aplicação web baseada em Python (Flask) utilizando `yt-dlp` e `ffmpeg` para download e processamento de mídias do YouTube.
echo.
echo ## Nota sobre Hospedagem (Vercel)
echo Os arquivos de configuração para nuvem (`vercel.json` e `api/index.py`) estão presentes no repositório com o objetivo de deploy na **Vercel**. No entanto, **os servidores da Vercel e de outras plataformas de nuvem são bloqueados pelo YouTube**. Portanto, para testes e uso atual, a aplicação deve ser executada localmente na sua máquina ou servidor dedicado.
echo.
echo ---
echo.
echo ## Instalação e Configuração
echo.
echo Siga os passos abaixo no terminal (CMD, PowerShell ou Linux) dentro da pasta do projeto para configurar o ambiente:
echo.
echo 1. **Criar o ambiente virtual (venv):**
echo    ```cmd
echo    python -m venv venv
echo    ```
echo.
echo 2. **Ativar o ambiente virtual:**
echo    - No Windows (CMD):
echo      ```cmd
echo      venv\Scripts\activate.bat
echo      ```
echo    - No Windows (PowerShell):
echo      ```cmd
echo      .\venv\Scripts\Activate.ps1
echo      ```
echo.
echo 3. **Instalar as dependências:**
echo    ```cmd
echo    pip install -r requirements.txt
echo    ```
echo    *(Nota: Certifique-se de que o **FFmpeg** também está instalado e configurado nas variáveis de ambiente do seu sistema).*
echo.
echo ---
echo.
echo ## Como Executar o Programa
echo.
echo Com o ambiente virtual ativado e na pasta raiz do projeto, execute o comando:
echo.
echo ```cmd
echo python baixar_musicas_servidor_7428.py
echo ```
echo.
echo Após iniciar, abra o seu navegador e acesse:
echo - **Local:** `http://localhost:7428`
) > README.md