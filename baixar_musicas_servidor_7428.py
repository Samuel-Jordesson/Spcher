#!/usr/bin/env python3
"""
Baixador de mídia para terminal (YouTube -> mp4, mp3, ogg, wav...).

Requisitos:
    pip install -U yt-dlp      (dentro de um venv)
    ffmpeg instalado no sistema (sudo apt install ffmpeg)

Uso:
    python baixar_musicas.py                 # inicia o servidor web
    python baixar_musicas.py --porta 9000    # servidor em outra porta
    python baixar_musicas.py --terminal      # menu interativo no terminal

Navegação: setas ↑ ↓ (ou j/k) e Enter. Também dá para apertar o número da opção.
Ctrl+C sai a qualquer momento.
"""

import argparse
import atexit
import glob
import json
import mimetypes
import os
import queue
import re
import shutil
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

try:
    import yt_dlp
    from yt_dlp.utils import DownloadError
except ImportError:
    # rodou com o python do sistema: tenta de novo com o python do venv ao lado do script
    _pasta = Path(__file__).resolve().parent
    for _py in (_pasta / "venv" / "bin" / "python", _pasta / "venv" / "Scripts" / "python.exe"):
        if _py.is_file() and Path(sys.prefix).resolve() != (_pasta / "venv").resolve():
            os.execv(str(_py), [str(_py), str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.exit("yt-dlp não está instalado. Rode:\n"
             "  python3 -m venv venv && venv/bin/pip install -U \"yt-dlp[default]\"")

try:
    import readline  # Tab completa caminhos de arquivo (Linux/macOS)
except ImportError:
    readline = None

# ───────────────────────── cores ─────────────────────────
if os.name == "nt":
    os.system("chcp 65001 >nul")  # UTF-8 no console
    os.system("")  # habilita ANSI no terminal do Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

FROZEN = getattr(sys, "frozen", False)  # True quando rodando como executável
BASE_DIR = Path(sys.executable).parent if FROZEN else Path.cwd()

VERDE = "\033[38;5;78m"
DIM = "\033[2m"
BOLD = "\033[1m"
VERMELHO = "\033[38;5;167m"
R = "\033[0m"

TTY = sys.stdout.isatty() and sys.stdin.isatty()
if TTY:
    atexit.register(lambda: sys.stdout.write("\033[?25h"))  # garante cursor visível

# ───────────────────────── opções ─────────────────────────
PASTA_SAIDA = BASE_DIR / "downloads"

FORMATOS = [
    ("mp4", "vídeo com áudio"),
    ("mp3", "áudio · toca em tudo"),
    ("ogg", "áudio · ideal para jogos"),
    ("wav", "áudio · sem compressão"),
    ("m4a", "áudio · AAC"),
    ("flac", "áudio · sem perdas"),
    ("opus", "áudio · leve e moderno"),
]

# formato -> (codec do ffmpeg, qualidade)
CODECS = {
    "mp3": ("mp3", "192"),
    "ogg": ("vorbis", "5"),
    "wav": ("wav", None),
    "m4a": ("m4a", "192"),
    "flac": ("flac", None),
    "opus": ("opus", "128"),
}

RESOLUCOES = [
    ("Baixa", "480p"),
    ("Média", "720p"),
    ("Alta", "1080p"),
]
ALTURAS = [480, 720, 1080]


# ───────────────────────── ffmpeg ─────────────────────────
def achar_ffmpeg() -> str | None:
    """Pasta do ffmpeg embutido/ao lado; "" se estiver no PATH; None se não achar."""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    pastas = [Path(__file__).resolve().parent / "bin"]
    if FROZEN:
        pastas = [Path(getattr(sys, "_MEIPASS", "")) / "bin", Path(sys.executable).parent]
    for pasta in pastas:
        if (pasta / exe).is_file():
            return str(pasta)
    return "" if shutil.which("ffmpeg") else None


FFMPEG_DIR = achar_ffmpeg()


def pausar() -> None:
    """Mantém a janela aberta (útil quando o executável é aberto com duplo clique)."""
    if FROZEN and TTY:
        try:
            input(f"\n{DIM}Pressione Enter para fechar...{R}")
        except (EOFError, KeyboardInterrupt):
            pass


# ───────────────────────── interface ─────────────────────────
def cabecalho() -> None:
    largura = 40
    linhas = ["✻ Baixador de mídia", "  yt-dlp · ffmpeg"]
    print(f"{VERDE}╭{'─' * largura}╮")
    for i, texto in enumerate(linhas):
        cor = BOLD if i == 0 else DIM
        print(f"{VERDE}│{R}{cor} {texto.ljust(largura - 1)}{R}{VERDE}│")
    print(f"{VERDE}╰{'─' * largura}╯{R}")


def ler_tecla() -> str:
    """Lê uma tecla: 'up', 'down', 'enter' ou o próprio caractere."""
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "")
        if ch == "\r":
            return "enter"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch

    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    antigo = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = os.read(fd, 1)
        if ch == b"\x1b":
            if select.select([fd], [], [], 0.05)[0]:
                seq = os.read(fd, 2)
                return {b"[A": "up", b"[B": "down"}.get(seq, "")
            return ""
        if ch in (b"\r", b"\n"):
            return "enter"
        return ch.decode(errors="ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, antigo)


def menu(titulo: str, opcoes: list[tuple[str, str]]) -> int:
    """Menu com setas. Retorna o índice escolhido."""
    n = len(opcoes)

    if not TTY:  # fallback simples (sem setas)
        print(f"? {titulo}")
        for i, (nome, desc) in enumerate(opcoes, 1):
            print(f"  {i}. {nome}  {desc}")
        while True:
            resp = input("> ").strip()
            if resp.isdigit() and 1 <= int(resp) <= n:
                return int(resp) - 1

    idx = 0
    print(f"{VERDE}?{R} {BOLD}{titulo}{R}")
    sys.stdout.write("\033[?25l")  # esconde cursor
    primeira = True
    try:
        while True:
            if not primeira:
                sys.stdout.write(f"\033[{n}A")
            primeira = False
            for i, (nome, desc) in enumerate(opcoes):
                if i == idx:
                    linha = f"{VERDE}❯ {nome}{R}  {DIM}{desc}{R}"
                else:
                    linha = f"  {DIM}{nome}{R}"
                sys.stdout.write(f"\033[2K\r{linha}\n")
            sys.stdout.flush()

            tecla = ler_tecla()
            if tecla in ("up", "k"):
                idx = (idx - 1) % n
            elif tecla in ("down", "j"):
                idx = (idx + 1) % n
            elif tecla.isdigit() and 1 <= int(tecla) <= n:
                idx = int(tecla) - 1
                break
            elif tecla == "enter":
                break
    finally:
        sys.stdout.write("\033[?25h")

    # recolhe o menu e deixa só a resposta
    sys.stdout.write(f"\033[{n + 1}A\033[J")
    print(f"{VERDE}✔{R} {titulo} {DIM}›{R} {VERDE}{opcoes[idx][0]}{R}")
    return idx


def _completar(texto: str, estado: int):
    texto = os.path.expanduser(texto)
    achados = [m + "/" if os.path.isdir(m) else m for m in glob.glob(texto + "*")]
    return achados[estado] if estado < len(achados) else None


def perguntar(titulo: str, dica: str = "", completar_arquivo: bool = False) -> str:
    if readline and completar_arquivo:
        readline.set_completer_delims(" \t\n;")
        readline.set_completer(_completar)
        readline.parse_and_bind("tab: complete")
    elif readline:
        readline.set_completer(None)

    print(f"{VERDE}?{R} {BOLD}{titulo}{R} {DIM}{dica}{R}")
    prompt = f"\001{VERDE}\002❯\001{R}\002 " if (readline and TTY) else "❯ "
    return input(prompt).strip()


def erro(msg: str) -> None:
    print(f"{VERMELHO}✘ {msg}{R}")


# ───────────────────────── entrada de links ─────────────────────────
def limpar_caminho(texto: str) -> Path:
    texto = texto.strip().strip("'\"").replace("\\ ", " ")
    return Path(os.path.expanduser(texto))


def ler_links(caminho: Path) -> tuple[list[str], int]:
    links, vistos, ignorados = [], set(), 0
    for linha in caminho.read_text(encoding="utf-8", errors="ignore").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if not linha.lower().startswith("http"):
            ignorados += 1
            continue
        if linha not in vistos:
            vistos.add(linha)
            links.append(linha)
    return links, ignorados


def pedir_link() -> list[str] | None:
    while True:
        resp = perguntar("Cole o link", "(vazio volta)")
        if not resp:
            return None
        if resp.lower().startswith("http"):
            return [resp]
        erro("isso não parece um link (precisa começar com http)")


def pedir_arquivo() -> list[str] | None:
    while True:
        resp = perguntar("Caminho do arquivo de links", "(Tab completa · vazio volta)", True)
        if not resp:
            return None
        caminho = limpar_caminho(resp)
        if not caminho.is_file():
            erro(f"arquivo não encontrado: {caminho}")
            continue
        links, ignorados = ler_links(caminho)
        if not links:
            erro("nenhum link válido nesse arquivo")
            continue
        extra = f" · {ignorados} linha(s) ignorada(s)" if ignorados else ""
        print(f"{DIM}  {len(links)} link(s) encontrado(s){extra}{R}")
        return links


# ───────────────────────── download ─────────────────────────
def fmt_tam(b) -> str:
    if not b:
        return "--"
    for unidade in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f}{unidade}"
        b /= 1024
    return f"{b:.1f}TB"


def fmt_tempo(s) -> str:
    if s is None:
        return "--:--"
    return f"{int(s) // 60:02d}:{int(s) % 60:02d}"


class LoggerMudo:
    """Silencia as mensagens do yt-dlp (o erro é mostrado pelo nosso layout)."""

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class Progresso:
    def __init__(self, total: int):
        self.total = total
        self.atual = 0
        self.titulo_mostrado = False

    def novo(self, i: int, link: str) -> None:
        self.atual = i
        self.link = link
        self.titulo_mostrado = False

    def mostrar_titulo(self, titulo: str) -> None:
        if self.titulo_mostrado:
            return
        self.titulo_mostrado = True
        largura = shutil.get_terminal_size().columns - 12
        if len(titulo) > largura:
            titulo = titulo[: largura - 1] + "…"
        print(f"{VERDE}[{self.atual}/{self.total}]{R} {titulo}")

    def baixando(self, d: dict) -> None:
        self.mostrar_titulo(d.get("info_dict", {}).get("title") or self.link)
        if d["status"] != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        feito = d.get("downloaded_bytes", 0)
        frac = min(feito / total, 1) if total else 0
        cheio = int(frac * 24)
        barra = f"{VERDE}{'█' * cheio}{DIM}{'░' * (24 - cheio)}{R}"
        linha = (
            f"  {barra} {frac * 100:5.1f}%  "
            f"{DIM}{fmt_tam(d.get('speed'))}/s · {fmt_tempo(d.get('eta'))}{R}"
        )
        sys.stdout.write(f"\r\033[2K{linha}")
        sys.stdout.flush()

    def processando(self, d: dict) -> None:
        if d["status"] != "started":
            return
        nome = d.get("postprocessor", "")
        if "Audio" in nome:
            msg = "convertendo..."
        elif "Merger" in nome:
            msg = "juntando vídeo e áudio..."
        else:
            return
        sys.stdout.write(f"\r\033[2K  {DIM}{msg}{R}")
        sys.stdout.flush()


def opcoes_base() -> dict:
    """Opções comuns a toda chamada do yt-dlp."""
    return {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "logger": LoggerMudo(),
        # o YouTube exige um runtime JS para liberar os formatos; usa o que estiver instalado
        "js_runtimes": {"deno": {}, "node": {}, "bun": {}},
    }


def opcoes_ydl(fmt: str, altura: int | None, pasta: Path, hooks: list, pp_hooks: list) -> dict:
    opcoes = {
        **opcoes_base(),
        "outtmpl": str(pasta / "%(title).150B.%(ext)s"),
        "noprogress": True,
        "windowsfilenames": True,
        "progress_hooks": hooks,
        "postprocessor_hooks": pp_hooks,
        # vídeos longos (2h+): resiste a quedas de conexão e ao limite de velocidade do YouTube
        "retries": 20,
        "fragment_retries": 20,
        "extractor_retries": 5,
        "file_access_retries": 5,
        "retry_sleep_functions": {"http": lambda n: min(2 ** n, 30), "fragment": lambda n: min(2 ** n, 30)},
        "socket_timeout": 30,
        "http_chunk_size": 10 * 1024 * 1024,
        "concurrent_fragment_downloads": 4,
        "continuedl": True,
    }
    if FFMPEG_DIR:
        opcoes["ffmpeg_location"] = FFMPEG_DIR
    if fmt == "mp4":
        # Alta (altura=None) busca a melhor resolução disponível; baixa/média limitam a altura.
        limite = f"[height<={altura}]" if altura else ""
        opcoes["format"] = (
            f"bv*{limite}[ext=mp4]+ba[ext=m4a]"
            f"/b{limite}[ext=mp4]"
            f"/bv*{limite}+ba"
            f"/b{limite}/b"
        )
        opcoes["merge_output_format"] = "mp4"
    else:
        codec, qualidade = CODECS[fmt]
        pp = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
        if qualidade:
            pp["preferredquality"] = qualidade
        opcoes["format"] = "bestaudio/best"
        opcoes["postprocessors"] = [pp]
    return opcoes


def limpar_erro(e: Exception) -> str:
    msg = str(e).replace("ERROR: ", "")
    for sep in ("\n",):
        msg = msg.split(sep)[0]
    return msg[:160]


def baixar(links: list[str], fmt: str, altura: int | None) -> None:
    pasta = PASTA_SAIDA / fmt
    pasta.mkdir(parents=True, exist_ok=True)
    prog = Progresso(len(links))
    ok, falhas = 0, []

    print()
    try:
        with yt_dlp.YoutubeDL(opcoes_ydl(fmt, altura, pasta, [prog.baixando], [prog.processando])) as ydl:
            for i, link in enumerate(links, 1):
                prog.novo(i, link)
                try:
                    ydl.download([link])
                    ok += 1
                    sys.stdout.write(f"\r\033[2K  {VERDE}✔ salvo{R}\n")
                except DownloadError as e:
                    prog.mostrar_titulo(link)
                    sys.stdout.write("\r\033[2K")
                    erro(f"falhou: {limpar_erro(e)}")
                    falhas.append(link)
    except KeyboardInterrupt:
        print(f"\n{VERMELHO}✘ interrompido{R}")

    print(f"\n{VERDE}✔ {ok} baixado(s){R}", end="")
    if falhas:
        print(f"  {VERMELHO}· {len(falhas)} falhou(aram){R}", end="")
    print(f"\n{DIM}  pasta: {pasta.resolve()}{R}")


# ───────────────────────── servidor web ─────────────────────────
PORTA_PADRAO = 7428
MAX_LINKS = 200
_LOCK_PRINT = threading.Lock()

PAGINA = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spcher</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%230a0b0a'/%3E%3Cpath d='M32 14v26m0 0-10-10m10 10 10-10M18 50h28' stroke='%234ade80' stroke-width='6' stroke-linecap='round' stroke-linejoin='round' fill='none'/%3E%3C/svg%3E">
<style>
:root{
  --bg:#0a0b0a;--surface:#101311;--line:#212622;--line-2:#2f3631;
  --txt:#e9f0eb;--dim:#7f8c84;--faint:#53605a;
  --g:#4ade80;--g-soft:rgba(74,222,128,.10);--g-ring:transparent;--ink:#04210f;--r:#f87171;
  --ease:cubic-bezier(.25,1,.5,1);
  --logo:clamp(60px,14vw,112px);--logo-gap:clamp(32px,6vh,56px);
  color-scheme:dark;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
[hidden]{display:none!important}
html,body{min-height:100%}
/* barra de rolagem da página invisível (a página continua rolando) */
html{scrollbar-width:none;-ms-overflow-style:none}
html::-webkit-scrollbar,body::-webkit-scrollbar{display:none}
body{
  margin:0;background:var(--bg);color:var(--txt);overflow-x:hidden;
  font:400 16px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
}
body::before{
  content:"";position:fixed;inset:-25%;pointer-events:none;z-index:0;
  background:radial-gradient(640px 420px at 50% 28%,rgba(74,222,128,.075),transparent 70%);
  animation:deriva 16s ease-in-out infinite alternate;
}
main{
  position:relative;z-index:1;width:min(100% - 64px,1200px);margin:0 auto;
  padding:clamp(72px,16vh,160px) 0 96px;
  display:flex;justify-content:center;align-items:flex-start;gap:64px;
}
.esq{
  flex:1 1 0;min-width:0;max-width:540px;position:relative;
}
/* Linha divisória vertical no meio quando o layout expande */
body.dividido .esq::after{
  content:"";position:absolute;top:calc(var(--logo) + var(--logo-gap));bottom:0;right:-32px;
  width:1px;background:var(--line);
}
.dir{
  display:none;flex:1 1 0;min-width:0;max-width:540px;
  padding-top:calc(var(--logo) + var(--logo-gap));
  transition:opacity .25s var(--ease);
}
.dir.carregando{opacity:.45}
body.dividido .dir{display:block}
@media (max-width:1040px){
  main{flex-direction:column;align-items:center;gap:40px;width:min(100% - 40px,600px)}
  .esq,.dir{flex:none;width:100%;max-width:none}
  .dir{padding-top:0}
  body.dividido .esq::after{display:none}
}

/* ── título ── */
.logo{
  margin:0 0 var(--logo-gap);text-align:center;
  font-size:var(--logo);font-weight:700;letter-spacing:-.05em;line-height:1;
  background:linear-gradient(180deg,#fff 25%,#86998d 125%);
  -webkit-background-clip:text;background-clip:text;color:transparent;
  animation:sobe .9s var(--ease) backwards;
}

/* ── campo do link ── */
.campo{position:relative;animation:sobe .9s .12s var(--ease) backwards}
.campo input{
  width:100%;height:64px;padding:0 54px 0 56px;border-radius:18px;
  border:1px solid var(--line);background:var(--surface);color:var(--txt);
  font:inherit;font-size:17px;outline:none;
  transition:border-color .2s var(--ease),box-shadow .3s var(--ease);
}
.campo input::placeholder{color:var(--faint)}
.campo input:hover{border-color:var(--line-2)}
.campo input:focus{border-color:var(--g);box-shadow:0 0 0 4px var(--g-ring)}
.campo .ico{
  position:absolute;left:20px;top:50%;width:20px;height:20px;margin-top:-10px;
  color:var(--faint);transition:color .2s var(--ease);pointer-events:none;
}
.campo:focus-within .ico{color:var(--g)}
.campo .spin{
  position:absolute;right:20px;top:50%;width:20px;height:20px;margin-top:-10px;
  border:2px solid var(--line-2);border-top-color:var(--g);border-radius:50%;
  opacity:0;transition:opacity .2s;animation:giro .7s linear infinite;
}
.campo.loading .spin{opacity:1}

#status{
  min-height:24px;margin:14px 4px 0;text-align:center;font-size:14px;color:var(--dim);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:color .2s;
}
#status.ok{color:var(--txt)}
#status.err{color:var(--r)}

/* ── etapas que aparecem com animação de altura ── */
.reveal{
  display:grid;grid-template-rows:0fr;opacity:0;
  transition:grid-template-rows .45s var(--ease),opacity .35s var(--ease);
}
.reveal.open{grid-template-rows:1fr;opacity:1}
.reveal>.in{min-height:0;overflow:hidden}
.pad{padding:28px 0 4px}
.rot{
  margin:0 0 14px;text-align:center;font-size:12px;font-weight:500;
  letter-spacing:.14em;text-transform:uppercase;color:var(--faint);
}
.chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center}
.chip{
  appearance:none;font:inherit;font-size:15px;font-weight:500;cursor:pointer;
  color:var(--dim);background:transparent;border:1px solid var(--line);border-radius:999px;
  padding:10px 20px;
  transition:color .15s var(--ease),border-color .15s var(--ease),background .15s var(--ease),transform .15s var(--ease);
  animation:sobe .5s var(--ease) backwards;animation-delay:calc(var(--i,0) * 35ms);
}
.chip:hover{color:var(--txt);border-color:var(--line-2);transform:translateY(-1px)}
.chip:active{transform:scale(.96)}
.chip.on{color:var(--g);border-color:var(--g);background:var(--g-soft)}
.chip:focus-visible{outline:2px solid var(--g);outline-offset:2px}
.nota{margin-top:14px;min-height:20px;text-align:center;font-size:13px;color:var(--faint)}

/* ── botão baixar ── */
.go{
  appearance:none;display:flex;align-items:center;justify-content:center;gap:10px;
  width:100%;height:56px;border:0;border-radius:16px;cursor:pointer;
  background:var(--g);color:var(--ink);font:inherit;font-size:16px;font-weight:600;
  transition:transform .15s var(--ease),filter .2s var(--ease),box-shadow .3s var(--ease),opacity .2s;
}
.go:hover{filter:brightness(1.08);box-shadow:0 10px 32px -10px rgba(74,222,128,.6)}
.go:active{transform:scale(.985)}
.go:focus-visible{outline:2px solid var(--g);outline-offset:3px}
.go:disabled{opacity:.6;cursor:default;box-shadow:none}
.go svg{width:18px;height:18px;transition:transform .25s var(--ease)}
.go:hover:not(:disabled) svg{transform:translateY(2px)}
#msg{min-height:20px;margin-top:14px;text-align:center;font-size:13px;color:var(--g)}
#msg.err{color:var(--r)}

/* ── fila ── */
.sec{
  margin:56px 0 4px;font-size:12px;font-weight:500;letter-spacing:.14em;
  text-transform:uppercase;color:var(--faint);
}
.item{padding:16px 0;border-top:1px solid var(--line);animation:sobe .5s var(--ease) backwards}
.nome{display:flex;align-items:center;font-size:15px}
.nome span.t{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dot{flex:none;width:6px;height:6px;margin-right:12px;border-radius:50%;background:var(--faint)}
.item[data-s=baixando] .dot,.item[data-s=convertendo] .dot,.item[data-s=juntando] .dot{background:var(--g);animation:pulso 1.4s ease-in-out infinite}
.item[data-s=pronto] .dot,.item[data-s=entregue] .dot{background:var(--g)}
.item[data-s=erro] .dot{background:var(--r)}
.meta{display:flex;flex-wrap:wrap;gap:4px 16px;margin:4px 0 0 18px;font-size:13px;color:var(--dim)}
.meta a{color:var(--g);text-decoration:none}
.meta a:hover{text-decoration:underline}
.item[data-s=erro] .meta span{color:var(--r)}
.bar{height:2px;margin:12px 0 0 18px;background:var(--line);border-radius:2px;overflow:hidden}
.bar i{display:block;position:relative;height:100%;width:0;background:var(--g);transition:width .5s var(--ease)}
.bar i.ind::after{
  content:"";position:absolute;inset:0;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.55),transparent);
  transform:translateX(-100%);animation:brilho 1.5s linear infinite;
}

/* ── painel do vídeo (lado direito) ── */
.player{position:relative;aspect-ratio:16/9;border-radius:18px;overflow:hidden;background:var(--surface);border:1px solid var(--line)}
.player img{display:block;width:100%;height:100%;object-fit:cover;transition:transform .6s var(--ease),opacity .3s}
.player:hover img{transform:scale(1.03)}
.play{
  position:absolute;inset:0;margin:auto;width:64px;height:64px;border-radius:50%;border:0;cursor:pointer;
  display:grid;place-items:center;color:#fff;background:rgba(10,11,10,.55);
  -webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);
  transition:transform .2s var(--ease),background .2s var(--ease),color .2s var(--ease),opacity .3s;
}
.play:hover{transform:scale(1.08);background:var(--g);color:var(--ink)}
.play:focus-visible{outline:2px solid var(--g);outline-offset:3px}
.play svg{width:24px;height:24px;margin-left:3px}
.dur{position:absolute;right:10px;bottom:10px;padding:2px 8px;border-radius:8px;background:rgba(0,0,0,.65);font-size:12px;font-variant-numeric:tabular-nums;transition:opacity .3s}
.tela{position:absolute;inset:0;background:#000;opacity:0;pointer-events:none;transition:opacity .3s}
.tela iframe,.tela video{display:block;width:100%;height:100%;border:0}
.player.tocando .tela{opacity:1;pointer-events:auto}
.player.tocando img,.player.tocando .play,.player.tocando .dur{opacity:0;pointer-events:none}
#v-titulo{margin:20px 0 4px;font-size:18px;font-weight:600;line-height:1.4;letter-spacing:-.01em;overflow-wrap:anywhere}
#v-canal{font-size:14px;color:var(--dim)}
#v-aviso{margin-top:8px;font-size:13px;color:var(--r)}
.lnk{
  appearance:none;display:inline-flex;align-items:center;gap:6px;margin-top:10px;padding:8px 0;
  background:none;border:0;font:inherit;font-size:14px;color:var(--dim);cursor:pointer;transition:color .15s var(--ease);
}
.lnk:hover{color:var(--txt)}
.lnk:focus-visible{outline:2px solid var(--g);outline-offset:2px;border-radius:4px}
.lnk svg{width:14px;height:14px;transition:transform .3s var(--ease)}
.lnk[aria-expanded=true] svg{transform:rotate(180deg)}
.lnk.orig{margin-left:16px;text-decoration:none}
.desc-txt{
  max-height:300px;overflow-y:auto;padding:12px 0 28px;
  font-size:14px;line-height:1.65;color:var(--dim);white-space:pre-wrap;overflow-wrap:anywhere;
  scrollbar-width:none;-ms-overflow-style:none;
  -webkit-mask-image:linear-gradient(#000 calc(100% - 28px),transparent);
  mask-image:linear-gradient(#000 calc(100% - 28px),transparent);
}
.desc-txt::-webkit-scrollbar{display:none}

/* ── animações ── */
@keyframes sobe{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@keyframes giro{to{transform:rotate(360deg)}}
@keyframes pulso{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes brilho{to{transform:translateX(100%)}}
@keyframes deriva{from{transform:translate(-3%,-2%) scale(1)}to{transform:translate(3%,4%) scale(1.12)}}
@media (max-width:480px){
  .campo input{height:60px;padding-left:52px}
  .chip{padding:9px 16px}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
}
</style>
</head>
<body>
<main>
  <div class="esq" id="esq">
  <h1 class="logo">Spcher</h1>

  <div class="campo" id="campo">
    <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.5 1.5"/><path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.5-1.5"/></svg>
    <input id="link" type="text" inputmode="url" placeholder="cole o link do vídeo" spellcheck="false" autocomplete="off" autocapitalize="off" aria-label="Link do vídeo">
    <span class="spin" aria-hidden="true"></span>
  </div>
  <div id="status" aria-live="polite"></div>

  <div id="etapa-formato" class="reveal"><div class="in"><div class="pad">
    <p class="rot">baixar como</p>
    <div id="formatos" class="chips"></div>
    <div id="fdesc" class="nota"></div>
  </div></div></div>

  <div id="etapa-res" class="reveal"><div class="in"><div class="pad">
    <p class="rot">resolução</p>
    <div id="resolucoes" class="chips"></div>
  </div></div></div>

  <div id="etapa-baixar" class="reveal"><div class="in"><div class="pad">
    <button id="baixar" class="go" type="button">
      <span id="baixar-t">Baixar</span>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v12m0 0-5-5m5 5 5-5M5 20h14"/></svg>
    </button>
  </div></div></div>

  <div id="msg" aria-live="polite"></div>

  <h2 id="fila-t" class="sec" hidden>downloads</h2>
  <div id="fila"></div>
  </div>

  <aside class="dir" id="dir" aria-label="Vídeo">
    <div class="player" id="player">
      <img id="capa" alt="" referrerpolicy="no-referrer">
      <span class="dur" id="dur" hidden></span>
      <button class="play" id="play" type="button" aria-label="Reproduzir vídeo">
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.14v13.72a1 1 0 0 0 1.52.85l11.1-6.86a1 1 0 0 0 0-1.7L9.52 4.29A1 1 0 0 0 8 5.14z"/></svg>
      </button>
      <div class="tela" id="tela"></div>
    </div>
    <h2 id="v-titulo"></h2>
    <div id="v-canal"></div>
    <div id="v-aviso"></div>
    <button id="desc-btn" class="lnk" type="button" aria-expanded="false" aria-controls="desc">
      <span id="desc-rot">ver descrição</span>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
    </button>
    <div id="desc" class="reveal"><div class="in"><div id="desc-txt" class="desc-txt" tabindex="0"></div></div></div>
  </aside>
</main>
<script>
const CFG = __CONFIG__;
const $ = s => document.querySelector(s);
const el = (tag, cls, txt) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt !== undefined) e.textContent = txt;
  return e;
};
const abrir = (id, on) => $(id).classList.toggle('open', !!on);

let urlAtual = '', resolucoes = [], fmtEscolhido = null, resEscolhida = null;
let timer, infoReq = 0, enviando = false;
const jobsDestaSessao = new Set();
const downloadsDisparados = new Set();

function msg(texto, erro) {
  const m = $('#msg');
  m.textContent = texto || '';
  m.className = erro ? 'err' : '';
}
function status(texto, tipo) {
  const s = $('#status');
  s.textContent = texto || '';
  s.className = tipo || '';
}

function chip(rotulo, valor, i, aoClicar, dica) {
  const b = el('button', 'chip', rotulo);
  b.type = 'button';
  b.dataset.v = String(valor);
  b.style.setProperty('--i', i);
  if (dica) b.title = dica;
  b.onclick = () => aoClicar(valor);
  return b;
}
function marcar(box, valor) {
  box.querySelectorAll('.chip').forEach(b => b.classList.toggle('on', b.dataset.v === String(valor)));
}

function resetar() {
  abrir('#etapa-formato', false);
  abrir('#etapa-res', false);
  abrir('#etapa-baixar', false);
  $('#formatos').replaceChildren();
  $('#resolucoes').replaceChildren();
  $('#fdesc').textContent = '';
  fmtEscolhido = null;
  resEscolhida = null;
  resolucoes = [];
}

function desenharFormatos() {
  const box = $('#formatos');
  box.replaceChildren();
  CFG.formatos.forEach(([nome, desc], i) => box.append(chip(nome, nome, i, escolherFormato, desc)));
}

function desenharResolucoes() {
  const box = $('#resolucoes');
  box.replaceChildren();
  resolucoes.forEach((h, i) => box.append(chip(h + 'p', h, i, escolherResolucao)));
}

function escolherFormato(nome) {
  fmtEscolhido = nome;
  resEscolhida = null;
  marcar($('#formatos'), nome);
  const f = CFG.formatos.find(x => x[0] === nome);
  $('#fdesc').textContent = f ? f[1] : '';
  if (nome === 'mp4' && resolucoes.length) {
    desenharResolucoes();
    abrir('#etapa-res', true);
  } else {
    abrir('#etapa-res', false);
  }
  atualizarBotao();
}

function escolherResolucao(h) {
  resEscolhida = h;
  marcar($('#resolucoes'), h);
  atualizarBotao();
}

// o botão só aparece quando tudo já foi escolhido
function atualizarBotao() {
  const pronto = fmtEscolhido && (fmtEscolhido !== 'mp4' || !resolucoes.length || resEscolhida);
  if (pronto) {
    $('#baixar-t').textContent = 'Baixar ' + fmtEscolhido + (resEscolhida ? ' · ' + resEscolhida + 'p' : '');
  }
  abrir('#etapa-baixar', pronto);
}

$('#link').addEventListener('input', () => {
  clearTimeout(timer);
  const id = ++infoReq;
  $('#campo').classList.remove('loading');
  resetar();
  msg('');
  status('');
  const url = $('#link').value.trim();
  if (!url) { dividir(false); return; }
  if (!/^https?:\/\//i.test(url)) {
    status('cole um link que comece com http', 'err');
    dividir(false);
    return;
  }
  timer = setTimeout(() => carregar(url, id), 400);
});

async function carregar(url, id) {
  $('#campo').classList.add('loading');
  $('#dir').classList.add('carregando');
  status('carregando vídeo...');
  try {
    const r = await fetch('/api/info', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url})
    });
    const d = await r.json();
    if (id !== infoReq) return;
    if (!r.ok) throw new Error(d.erro || 'não foi possível carregar o vídeo');
    urlAtual = url;
    resolucoes = d.resolucoes || [];
    status('');
    mostrarVideo(d);
    dividir(true);
    desenharFormatos();
    abrir('#etapa-formato', true);
  } catch (e) {
    if (id === infoReq) { status(e.message, 'err'); dividir(false); }
  }
  if (id === infoReq) {
    $('#campo').classList.remove('loading');
    $('#dir').classList.remove('carregando');
  }
}

$('#baixar').onclick = async () => {
  if (enviando || !fmtEscolhido) return;
  enviando = true;
  const btn = $('#baixar');
  btn.disabled = true;
  msg('');
  try {
    const r = await fetch('/api/baixar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({links: [urlAtual], formato: fmtEscolhido, resolucao: fmtEscolhido === 'mp4' ? resEscolhida : null})
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.erro || 'erro ao enviar');
    (d.ids || []).forEach(id => jobsDestaSessao.add(id));
    $('#link').value = '';
    status('');
    resetar();
    dividir(false);
    msg('adicionado à fila');
    setTimeout(() => msg(''), 2500);
    ultJobs = '';
    atualizarJobs();
  } catch (e) {
    msg(e.message, true);
  }
  btn.disabled = false;
  enviando = false;
};

/* ── painel do vídeo + animação de ir para o lado ── */
let dividido = false, tokenDiv = 0, videoAtual = null;
const reduzido = matchMedia('(prefers-reduced-motion: reduce)').matches;
const EASE = 'cubic-bezier(.25,1,.5,1)';
const empilhado = () => matchMedia('(max-width: 1040px)').matches;

function fmtDuracao(s) {
  if (!s) return '';
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), seg = s % 60;
  const dois = n => String(n).padStart(2, '0');
  return h ? h + ':' + dois(m) + ':' + dois(seg) : m + ':' + dois(seg);
}

function pararPlayer() {
  $('#player').classList.remove('tocando');
  $('#tela').replaceChildren();
}

function mostrarVideo(d) {
  videoAtual = d;
  pararPlayer();
  $('#v-aviso').textContent = '';
  const capa = $('#capa');
  capa.hidden = !d.capa;
  capa.src = d.capa || '';
  const dur = fmtDuracao(d.duracao);
  $('#dur').textContent = dur;
  $('#dur').hidden = !dur;
  $('#play').hidden = !(d.embed || d.direto);
  $('#v-titulo').textContent = d.titulo || '';
  $('#v-canal').textContent = d.canal || '';
  const tem = !!(d.descricao && d.descricao.trim());
  $('#desc-btn').hidden = !tem;
  $('#desc-txt').textContent = tem ? d.descricao.trim() : '';
  $('#desc-txt').scrollTop = 0;
  abrir('#desc', false);
  $('#desc-btn').setAttribute('aria-expanded', 'false');
  $('#desc-rot').textContent = 'ver descrição';
}

function tocar() {
  const v = videoAtual;
  if (!v) return;
  let no;
  if (v.embed) {
    no = document.createElement('iframe');
    no.src = 'https://www.youtube-nocookie.com/embed/' + encodeURIComponent(v.embed) + '?autoplay=1&rel=0&modestbranding=1';
    no.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
    no.allowFullscreen = true;
    no.referrerPolicy = 'strict-origin-when-cross-origin';
    no.title = v.titulo || 'vídeo';
  } else if (v.direto) {
    no = document.createElement('video');
    no.src = v.direto;
    no.controls = true;
    no.autoplay = true;
    no.playsInline = true;
    no.onerror = () => {
      pararPlayer();
      $('#v-aviso').textContent = 'não foi possível tocar este vídeo aqui';
    };
  } else {
    return;
  }
  $('#v-aviso').textContent = '';
  $('#tela').replaceChildren(no);
  $('#player').classList.add('tocando');
}
$('#play').onclick = tocar;

$('#desc-btn').onclick = () => {
  const abrirDesc = !$('#desc').classList.contains('open');
  abrir('#desc', abrirDesc);
  $('#desc-btn').setAttribute('aria-expanded', String(abrirDesc));
  $('#desc-rot').textContent = abrirDesc ? 'ocultar descrição' : 'ver descrição';
};

// Move o bloco da esquerda (nome + barra + opções) com animação e traz o vídeo do lado direito.
async function dividir(on) {
  if (on === dividido) return;
  dividido = on;
  const tk = ++tokenDiv;
  const esq = $('#esq'), dir = $('#dir');
  const dur = reduzido ? 0 : 650;
  const desloc = empilhado() ? 'translateY(24px)' : 'translateX(56px)';
  let saida = null;
  if (!on) {
    pararPlayer();
    if (dur) {
      saida = dir.animate(
        [{opacity: 1, transform: 'none'}, {opacity: 0, transform: desloc}],
        {duration: 220, easing: 'ease-in', fill: 'forwards'}
      );
      await saida.finished.catch(() => {});
    }
  }
  if (tk !== tokenDiv) { if (saida) saida.cancel(); return; }
  const antes = esq.getBoundingClientRect();
  document.body.classList.toggle('dividido', on);
  if (saida) saida.cancel();
  const dx = antes.left - esq.getBoundingClientRect().left;
  if (!dur) return;
  if (dx) esq.animate([{transform: 'translateX(' + dx + 'px)'}, {transform: 'none'}], {duration: dur, easing: EASE});
  if (on) {
    dir.animate(
      [{opacity: 0, transform: desloc}, {opacity: 1, transform: 'none'}],
      {duration: dur, delay: 120, easing: EASE, fill: 'backwards'}
    );
  }
}

/* ── fila de downloads (atualiza os itens no lugar, sem recriar) ── */
const ROT = {
  fila: 'na fila',
  baixando: 'baixando',
  convertendo: 'convertendo...',
  juntando: 'juntando vídeo e áudio...',
  pronto: 'enviando para este dispositivo...',
  entregue: 'concluído · cópia apagada do servidor',
  expirado: 'tempo esgotado · cópia apagada do servidor, baixe de novo',
  erro: 'erro'
};
const itens = new Map();
let ultJobs = '';

function novoItem(id) {
  const root = el('div', 'item');
  const nome = el('div', 'nome');
  const meta = el('div', 'meta');
  const bar = el('div', 'bar');
  const fill = el('i');
  bar.append(fill);
  root.append(nome, meta, bar);
  $('#fila').prepend(root);
  const ref = {root, nome, meta, bar, fill};
  itens.set(id, ref);
  return ref;
}

function iniciarDownload(j) {
  if (downloadsDisparados.has(j.id)) return;
  downloadsDisparados.add(j.id);
  // o navegador baixa o arquivo; quando termina, o servidor apaga a cópia dele
  j.files.forEach((f, index) => setTimeout(() => {
    const a = document.createElement('a');
    a.href = f.url;
    a.download = f.nome;
    a.rel = 'noopener';
    document.body.append(a);
    a.click();
    a.remove();
  }, index * 700));
}

async function atualizarJobs() {
  const txt = await (await fetch('/api/jobs')).text();
  if (txt === ultJobs) return;
  ultJobs = txt;
  const jobs = JSON.parse(txt).jobs.filter(j => jobsDestaSessao.has(j.id)).reverse();
  $('#fila-t').hidden = !jobs.length;
  jobs.forEach(j => {
    const ref = itens.get(j.id) || novoItem(j.id);
    ref.root.dataset.s = j.status;

    ref.nome.replaceChildren(el('span', 'dot'), el('span', 't', j.title || j.url));

    let s = ROT[j.status] || j.status;
    if (j.status === 'baixando') {
      s += ' · ' + j.percent.toFixed(1) + '%' + (j.speed ? ' · ' + j.speed : '') + (j.eta ? ' · ' + j.eta : '');
    }
    if (j.status === 'erro') s += ' · ' + j.error;
    ref.meta.replaceChildren(el('span', null, s));

    if (j.status === 'pronto' && j.files.length) {
      iniciarDownload(j);
      j.files.forEach(f => {
        const a = el('a', null, 'baixar no dispositivo');
        a.href = f.url;
        a.download = f.nome;
        a.rel = 'noopener';
        ref.meta.append(a);
      });
    }

    const ativo = ['baixando', 'convertendo', 'juntando'].includes(j.status);
    ref.bar.hidden = !ativo;
    ref.fill.style.width = (j.status === 'baixando' ? j.percent : 100) + '%';
    ref.fill.classList.toggle('ind', j.status !== 'baixando');
  });
}

if (!matchMedia('(pointer:coarse)').matches) $('#link').focus();
atualizarJobs().catch(() => {});
setInterval(() => atualizarJobs().catch(() => {}), 1000);
</script>
</body>
</html>
"""


def log(simbolo: str, cor: str, msg: str) -> None:
    with _LOCK_PRINT:
        print(f"{DIM}{time.strftime('%H:%M:%S')}{R} {cor}{simbolo}{R} {msg}", flush=True)


def ip_local() -> str:
    """IP da máquina na rede local (não envia nenhum pacote)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class Estado:
    """Fila de downloads compartilhada entre o servidor e o trabalhador."""

    def __init__(self) -> None:
        self.jobs: list[dict] = []
        self.lock = threading.Lock()
        self.fila: queue.Queue = queue.Queue()
        self.proximo_id = 1
        self.parando = False
        self.enviando: dict[str, int] = {}  # pasta do job -> transferências em andamento

    def adicionar(self, links: list[str], fmt: str, altura: int | None) -> list[int]:
        ids = []
        with self.lock:
            for link in links:
                job = {
                    "id": self.proximo_id, "url": link, "fmt": fmt, "altura": altura,
                    "status": "fila", "title": "", "percent": 0.0,
                    "speed": "", "eta": "", "error": "", "files": [],
                    "dir": "", "pronto_em": 0.0,
                }
                self.proximo_id += 1
                ids.append(job["id"])
                self.jobs.append(job)
                self.fila.put(job)
            if len(self.jobs) > 300:
                self.jobs = self.jobs[-300:]
        return ids

    def entregue(self, caminho: Path) -> None:
        """O cliente terminou de baixar: apaga a cópia do servidor."""
        pasta = caminho.parent
        with self.lock:
            for j in self.jobs:
                if j.get("dir") == str(pasta):
                    j["files"] = [f for f in j["files"] if unquote(f["url"]).split("/files/", 1)[-1] != _rel(caminho)]
                    if not j["files"]:
                        j["status"] = "entregue"
        try:
            caminho.unlink()
        except OSError:
            pass
        apagar_pasta_se_vazia(pasta)

    def expirar(self, ttl: float) -> None:
        """Apaga downloads prontos que o navegador nunca buscou (ex.: download bloqueado)."""
        agora = time.time()
        with self.lock:
            # arquivo grande ainda indo para o navegador não pode ser apagado no meio
            velhos = [j for j in self.jobs if j["status"] == "pronto" and agora - j["pronto_em"] > ttl
                      and not self.enviando.get(j["dir"])]
            for j in velhos:
                j["status"], j["files"] = "expirado", []
        for j in velhos:
            apagar_pasta(Path(j["dir"]))

    def snapshot(self) -> list[dict]:
        with self.lock:
            return [dict(j) for j in reversed(self.jobs[-50:])]


def _rel(caminho: Path) -> str:
    return caminho.resolve().relative_to(PASTA_SAIDA.resolve()).as_posix()


def _pasta_segura(pasta: Path) -> bool:
    base = PASTA_SAIDA.resolve()
    try:
        p = pasta.resolve()
    except OSError:
        return False
    return p != base and base in p.parents


def apagar_pasta(pasta: Path) -> None:
    if _pasta_segura(pasta):
        shutil.rmtree(pasta, ignore_errors=True)


def apagar_pasta_se_vazia(pasta: Path) -> None:
    """Remove a pasta do job (e restos como .part/.ytdl) quando não sobrou arquivo para entregar."""
    apagar_pasta(pasta)


def limpar_restos() -> None:
    """Remove tudo que sobrou de execuções anteriores."""
    if PASTA_SAIDA.is_dir():
        for p in PASTA_SAIDA.glob("job*"):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)


TTL_NAO_BAIXADO = 30 * 60  # segundos


def faxineiro(estado: "Estado") -> None:
    while not estado.parando:
        time.sleep(60)
        estado.expirar(TTL_NAO_BAIXADO)


def coletar_arquivos(info) -> list[Path]:
    if not info:
        return []
    itens = list(info.get("entries") or [info])
    arquivos = []
    for item in itens:
        for rd in (item or {}).get("requested_downloads") or []:
            if rd.get("filepath"):
                arquivos.append(Path(rd["filepath"]))
    return arquivos


def processar_job(job: dict) -> None:
    fmt, altura = job["fmt"], job["altura"]
    pasta = PASTA_SAIDA / f"job{job['id']}"
    pasta.mkdir(parents=True, exist_ok=True)
    job["dir"] = str(pasta.resolve())
    anunciado = False

    def ao_baixar(d: dict) -> None:
        nonlocal anunciado
        titulo = (d.get("info_dict") or {}).get("title")
        if titulo:
            job["title"] = titulo
            if not anunciado:
                anunciado = True
                log("↓", VERDE, titulo)
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            feito = d.get("downloaded_bytes", 0)
            job["status"] = "baixando"
            if total:
                job["percent"] = round(min(feito / total, 1) * 100, 1)
            job["speed"] = f"{fmt_tam(d.get('speed'))}/s" if d.get("speed") else ""
            job["eta"] = fmt_tempo(d["eta"]) if d.get("eta") is not None else ""
        elif d["status"] == "finished":
            job["percent"] = 100.0

    def ao_processar(d: dict) -> None:
        if d["status"] != "started":
            return
        nome = d.get("postprocessor", "")
        if "Audio" in nome:
            job["status"] = "convertendo"
        elif "Merger" in nome:
            job["status"] = "juntando"
        job["speed"], job["eta"] = "", ""

    try:
        with yt_dlp.YoutubeDL(opcoes_ydl(fmt, altura, pasta, [ao_baixar], [ao_processar])) as ydl:
            info = ydl.extract_info(job["url"], download=True)
        base = PASTA_SAIDA.resolve()
        arquivos = []
        for fp in coletar_arquivos(info):
            try:
                rel = fp.resolve().relative_to(base)
            except ValueError:
                continue
            arquivos.append({"nome": fp.name, "url": "/files/" + quote(rel.as_posix())})
        job.update(status="pronto", percent=100.0, speed="", eta="", files=arquivos, pronto_em=time.time())
        log("✔", VERDE, job["title"] or job["url"])
    except Exception as e:  # noqa: BLE001
        job.update(status="erro", error=limpar_erro(e), speed="", eta="")
        apagar_pasta(pasta)
        log("✘", VERMELHO, f"{job['title'] or job['url']} — {job['error']}")


def trabalhador(estado: Estado) -> None:
    while True:
        job = estado.fila.get()
        if job is None:
            break
        if estado.parando:
            continue
        processar_job(job)


def escolher_direto(formatos: list[dict]) -> str | None:
    """Link de um arquivo único (vídeo+áudio) que o navegador toca direto, até 720p."""
    candidatos = [
        f for f in formatos
        if f.get("url") and f.get("protocol") in ("http", "https")
        and f.get("vcodec") not in (None, "none") and f.get("acodec") not in (None, "none")
        and f.get("ext") in ("mp4", "webm")
    ]
    if not candidatos:
        return None
    dentro = [f for f in candidatos if (f.get("height") or 0) <= 720] or candidatos
    return max(dentro, key=lambda f: f.get("height") or 0)["url"]


class Handler(BaseHTTPRequestHandler):
    server_version = "Baixador"

    def log_message(self, *args) -> None:  # silencia o log padrão
        pass

    def _enviar(self, corpo: bytes, tipo: str, codigo: int = 200) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, dados: dict, codigo: int = 200) -> None:
        self._enviar(json.dumps(dados, ensure_ascii=False).encode("utf-8"),
                     "application/json; charset=utf-8", codigo)

    def _aguardar_cliente(self) -> None:
        """Depois de enviar tudo, espera o navegador fechar a conexão (= recebeu o arquivo inteiro)."""
        try:
            self.connection.shutdown(socket.SHUT_WR)
            self.connection.settimeout(20)
            while self.connection.recv(4096):
                pass
        except OSError:
            pass

    def _arquivo(self, rel: str) -> None:
        base = PASTA_SAIDA.resolve()
        try:
            alvo = (base / rel).resolve()
            valido = base in alvo.parents and alvo.is_file()
        except (OSError, ValueError):
            valido = False
        if not valido:
            return self._json({"erro": "arquivo não encontrado (já foi baixado ou expirou)"}, 404)
        estado: Estado = self.server.estado  # type: ignore[attr-defined]
        tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(alvo.stat().st_size))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(alvo.name)}")
        self.send_header("Connection", "close")
        self.end_headers()
        enviado = False
        pasta = str(alvo.parent)
        with estado.lock:
            estado.enviando[pasta] = estado.enviando.get(pasta, 0) + 1
        try:
            with open(alvo, "rb") as f:
                shutil.copyfileobj(f, self.wfile, 1024 * 1024)
            self.wfile.flush()
            enviado = True
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass  # download interrompido: mantém o arquivo para tentar de novo
        finally:
            with estado.lock:
                estado.enviando[pasta] -= 1
                if not estado.enviando[pasta]:
                    del estado.enviando[pasta]
                    # reinicia o prazo: quem não terminou ainda tem tempo de tentar de novo
                    for j in estado.jobs:
                        if j.get("dir") == pasta and j["status"] == "pronto":
                            j["pronto_em"] = time.time()
        if enviado:
            self._aguardar_cliente()
            estado.entregue(alvo)
            log("🗑", DIM, f"cópia apagada do servidor: {alvo.name}")

    def do_GET(self) -> None:
        caminho = urlparse(self.path).path
        estado: Estado = self.server.estado  # type: ignore[attr-defined]
        if caminho in ("/", "/index.html"):
            config = {"formatos": [list(f) for f in FORMATOS]}
            pagina = PAGINA.replace("__CONFIG__", json.dumps(config, ensure_ascii=False))
            self._enviar(pagina.encode("utf-8"), "text/html; charset=utf-8")
        elif caminho == "/api/jobs":
            self._json({"jobs": estado.snapshot()})
        elif caminho.startswith("/files/"):
            self._arquivo(unquote(caminho[len("/files/"):]))
        else:
            self._json({"erro": "não encontrado"}, 404)

    def do_POST(self) -> None:
        caminho = urlparse(self.path).path
        if caminho not in ("/api/baixar", "/api/info"):
            return self._json({"erro": "não encontrado"}, 404)
        # exigir JSON impede que outros sites enviem pedidos às escondidas (CSRF)
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json({"erro": "content-type inválido"}, 415)
        try:
            tam = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            tam = 0
        if tam <= 0 or tam > 1_000_000:
            return self._json({"erro": "corpo inválido"}, 400)
        try:
            dados = json.loads(self.rfile.read(tam))
            assert isinstance(dados, dict)
        except (ValueError, AssertionError):
            return self._json({"erro": "JSON inválido"}, 400)

        if caminho == "/api/info":
            url = dados.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                return self._json({"erro": "link inválido"}, 400)
            try:
                with yt_dlp.YoutubeDL({**opcoes_base(), "skip_download": True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                formatos = info.get("formats") or []
                resolucoes = sorted({int(f["height"]) for f in formatos
                                     if f.get("height") and f.get("vcodec") not in (None, "none")}, reverse=True)
                embed = info.get("id") if str(info.get("extractor_key", "")).lower() == "youtube" else None
                return self._json({
                    "titulo": info.get("title", ""),
                    "resolucoes": resolucoes,
                    "capa": info.get("thumbnail") or "",
                    "descricao": (info.get("description") or "")[:8000],
                    "canal": info.get("channel") or info.get("uploader") or "",
                    "duracao": info.get("duration"),
                    "embed": embed,
                    "direto": None if embed else escolher_direto(formatos),
                    "pagina": info.get("webpage_url") or url,
                })
            except Exception as e:
                return self._json({"erro": limpar_erro(e)}, 400)

        fmt = dados.get("formato")
        if fmt not in [f[0] for f in FORMATOS]:
            return self._json({"erro": "formato inválido"}, 400)
        altura = None
        if fmt == "mp4":
            resolucao = dados.get("resolucao")
            if resolucao is not None:
                if not isinstance(resolucao, int) or resolucao < 144 or resolucao > 16384:
                    return self._json({"erro": "resolução inválida"}, 400)
                altura = resolucao
            else:
                qualidade = dados.get("qualidade", "alta")
                alturas_por_qualidade = {"baixa": 480, "media": 720, "alta": None}
                if qualidade not in alturas_por_qualidade:
                    return self._json({"erro": "qualidade inválida"}, 400)
                altura = alturas_por_qualidade[qualidade]

        brutos = dados.get("links")
        if not isinstance(brutos, list):
            return self._json({"erro": "links inválidos"}, 400)
        links, vistos, ignorados = [], set(), 0
        for item in brutos:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if not item or item.startswith("#"):
                continue
            if not item.lower().startswith("http"):
                ignorados += 1
            elif item not in vistos:
                vistos.add(item)
                links.append(item)
        if not links:
            return self._json({"erro": "nenhum link válido"}, 400)
        if len(links) > MAX_LINKS:
            return self._json({"erro": f"máximo de {MAX_LINKS} links por vez"}, 400)

        ids = self.server.estado.adicionar(links, fmt, altura)  # type: ignore[attr-defined]
        log("+", VERDE, f"{len(links)} link(s) na fila · {fmt}" + (f" até {altura}p" if altura else ""))
        self._json({"ok": True, "adicionados": len(links), "ignorados": ignorados, "ids": ids})


def servir(porta: int = PORTA_PADRAO) -> None:
    httpd = None
    for tentativa in range(porta, porta + 10):
        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", tentativa), Handler)
            porta = tentativa
            break
        except OSError:
            continue
    if httpd is None:
        erro(f"não consegui abrir nenhuma porta entre {porta} e {porta + 9}")
        return

    estado = Estado()
    httpd.estado = estado  # type: ignore[attr-defined]
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    limpar_restos()
    threading.Thread(target=trabalhador, args=(estado,), daemon=True).start()
    threading.Thread(target=faxineiro, args=(estado,), daemon=True).start()

    print(f"\n{VERDE}✔ Servidor rodando{R}")
    print(f"  {DIM}local{R}  http://localhost:{porta}")
    print(f"  {DIM}rede {R}  http://{ip_local()}:{porta}")
    print(f"{DIM}  arquivos temporários em {PASTA_SAIDA} (apagados após o download) · Ctrl+C para parar{R}\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        estado.parando = True
        estado.fila.put(None)
        httpd.server_close()
        limpar_restos()
    print(f"\n{DIM}servidor parado.{R}")


# ───────────────────────── fluxo principal ─────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Baixador de mídia com interface web e modo terminal.")
    ap.add_argument("-s", "--servidor", action="store_true", help="inicia o servidor web (padrão)")
    ap.add_argument("-t", "--terminal", action="store_true", help="abre o menu interativo no terminal")
    ap.add_argument("-p", "--porta", type=int, default=PORTA_PADRAO, help=f"porta do servidor (padrão {PORTA_PADRAO})")
    args = ap.parse_args()

    if FFMPEG_DIR is None:
        erro("ffmpeg não encontrado. Linux: sudo apt install ffmpeg · "
             "Windows: coloque ffmpeg.exe e ffprobe.exe ao lado do programa.")
        pausar()
        return

    cabecalho()
    # Por padrão, iniciar a interface web para acesso pelo navegador.
    # O modo de menu no terminal continua disponível com --terminal.
    if not args.terminal:
        servir(args.porta)
        return

    try:
        while True:
            print()
            acao = menu(
                "O que você quer fazer?",
                [
                    ("Um link", "cole um link do YouTube"),
                    ("Lista de links", "arquivo .txt, um link por linha"),
                    ("Servidor web", "baixar pelo navegador, em qualquer aparelho da rede"),
                    ("Sair", ""),
                ],
            )
            if acao == 3:
                break
            if acao == 2:
                servir(args.porta)
                continue

            links = pedir_link() if acao == 0 else pedir_arquivo()
            if not links:
                continue

            fmt = FORMATOS[menu("Em qual formato?", FORMATOS)][0]

            altura = None
            if fmt == "mp4":
                altura = ALTURAS[menu("Qual resolução?", RESOLUCOES)]

            baixar(links, fmt, altura)
    except (KeyboardInterrupt, EOFError):
        pass
    print(f"\n{DIM}até logo.{R}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        erro(f"erro inesperado: {e}")
        pausar()
        sys.exit(1)