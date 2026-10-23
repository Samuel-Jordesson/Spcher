# api/index.py
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote
from flask import Flask, request, send_file, jsonify, render_template_string

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

app = Flask(__name__)
PASTA_SAIDA = Path(tempfile.gettempdir()) / "downloads"

FORMATOS = [
    ("mp4", "vídeo com áudio"),
    ("mp3", "áudio · toca em tudo"),
    ("ogg", "áudio · ideal para jogos"),
    ("wav", "áudio · sem compressão"),
    ("m4a", "áudio · AAC"),
    ("flac", "áudio · sem perdas"),
    ("opus", "áudio · leve e moderno"),
]

CODECS = {
    "mp3": ("mp3", "192"),
    "ogg": ("vorbis", "5"),
    "wav": ("wav", None),
    "m4a": ("m4a", "192"),
    "flac": ("flac", None),
    "opus": ("opus", "128"),
}

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
.logo{
  margin:0 0 var(--logo-gap);text-align:center;
  font-size:var(--logo);font-weight:700;letter-spacing:-.05em;line-height:1;
  background:linear-gradient(180deg,#fff 25%,#86998d 125%);
  -webkit-background-clip:text;background-clip:text;color:transparent;
  animation:sobe .9s var(--ease) backwards;
}
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
.sec{
  margin:56px 0 4px;font-size:12px;font-weight:500;letter-spacing:.14em;
  text-transform:uppercase;color:var(--faint);
}
.item{padding:16px 0;border-top:1px solid var(--line);animation:sobe .5s var(--ease) backwards}
.nome{display:flex;align-items:center;font-size:15px}
.nome span.t{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dot{flex:none;width:6px;height:6px;margin-right:12px;border-radius:50%;background:var(--faint)}
.item[data-s=baixando] .dot,.item[data-s=pronto] .dot{background:var(--g)}
.item[data-s=erro] .dot{background:var(--r)}
.meta{display:flex;flex-wrap:wrap;gap:4px 16px;margin:4px 0 0 18px;font-size:13px;color:var(--dim)}
.meta a{color:var(--g);text-decoration:none}
.meta a:hover{text-decoration:underline}
.bar{height:2px;margin:12px 0 0 18px;background:var(--line);border-radius:2px;overflow:hidden}
.bar i{display:block;position:relative;height:100%;width:0;background:var(--g);transition:width .5s var(--ease)}
.player{position:relative;aspect-ratio:16/9;border-radius:18px;overflow:hidden;background:var(--surface);border:1px solid var(--line)}
.player img{display:block;width:100%;height:100%;object-fit:cover}
.play{
  position:absolute;inset:0;margin:auto;width:64px;height:64px;border-radius:50%;border:0;cursor:pointer;
  display:grid;place-items:center;color:#fff;background:rgba(10,11,10,.55);
  -webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);
}
.play svg{width:24px;height:24px;margin-left:3px}
.dur{position:absolute;right:10px;bottom:10px;padding:2px 8px;border-radius:8px;background:rgba(0,0,0,.65);font-size:12px}
.tela{position:absolute;inset:0;background:#000;opacity:0;pointer-events:none;transition:opacity .3s}
.tela iframe,.tela video{display:block;width:100%;height:100%;border:0}
.player.tocando .tela{opacity:1;pointer-events:auto}
.player.tocando img,.player.tocando .play,.player.tocando .dur{opacity:0;pointer-events:none}
#v-titulo{margin:20px 0 4px;font-size:18px;font-weight:600;line-height:1.4}
#v-canal{font-size:14px;color:var(--dim)}
#v-aviso{margin-top:8px;font-size:13px;color:var(--r)}
.lnk{
  appearance:none;display:inline-flex;align-items:center;gap:6px;margin-top:10px;padding:8px 0;
  background:none;border:0;font:inherit;font-size:14px;color:var(--dim);cursor:pointer;
}
.desc-txt{
  max-height:300px;overflow-y:auto;padding:12px 0 28px;
  font-size:14px;line-height:1.65;color:var(--dim);white-space:pre-wrap;
  scrollbar-width:none;-ms-overflow-style:none;
}
.desc-txt::-webkit-scrollbar{display:none}
@keyframes sobe{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@keyframes giro{to{transform:rotate(360deg)}}
@keyframes deriva{from{transform:translate(-3%,-2%) scale(1)}to{transform:translate(3%,4%) scale(1.12)}}
</style>
</head>
<body>
<main>
  <div class="esq" id="esq">
  <h1 class="logo">Spcher</h1>
  <div class="campo" id="campo">
    <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.5 1.5"/><path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.5-1.5"/></svg>
    <input id="link" type="text" inputmode="url" placeholder="cole o link do vídeo" spellcheck="false" autocomplete="off">
    <span class="spin"></span>
  </div>
  <div id="status"></div>
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
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 4v12m0 0-5-5m5 5 5-5M5 20h14"/></svg>
    </button>
  </div></div></div>
  <div id="msg"></div>
  <h2 id="fila-t" class="sec" hidden>downloads</h2>
  <div id="fila"></div>
  </div>
  <aside class="dir" id="dir" aria-label="Vídeo">
    <div class="player" id="player">
      <img id="capa" alt="" referrerpolicy="no-referrer">
      <span class="dur" id="dur" hidden></span>
      <button class="play" id="play" type="button"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.14v13.72a1 1 0 0 0 1.52.85l11.1-6.86a1 1 0 0 0 0-1.7L9.52 4.29A1 1 0 0 0 8 5.14z"/></svg></button>
      <div class="tela" id="tela"></div>
    </div>
    <h2 id="v-titulo"></h2>
    <div id="v-canal"></div>
    <div id="v-aviso"></div>
    <button id="desc-btn" class="lnk" type="button" aria-expanded="false">
      <span id="desc-rot">ver descrição</span>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" style="width:14px;height:14px"><path d="m6 9 6 6 6-6"/></svg>
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

function msg(t, err) { const m = $('#msg'); m.textContent = t || ''; m.className = err ? 'err' : ''; }
function status(t, tp) { const s = $('#status'); s.textContent = t || ''; s.className = tp || ''; }
function chip(rot, val, i, fn, dica) {
  const b = el('button', 'chip', rot);
  b.type = 'button'; b.dataset.v = String(val); b.style.setProperty('--i', i);
  if (dica) b.title = dica;
  b.onclick = () => fn(val);
  return b;
}
function marcar(box, val) { box.querySelectorAll('.chip').forEach(b => b.classList.toggle('on', b.dataset.v === String(val))); }
function resetar() {
  abrir('#etapa-formato', false); abrir('#etapa-res', false); abrir('#etapa-baixar', false);
  $('#formatos').replaceChildren(); $('#resolucoes').replaceChildren();
  $('#fdesc').textContent = ''; fmtEscolhido = null; resEscolhida = null; resolucoes = [];
}
function desenharFormatos() {
  const box = $('#formatos'); box.replaceChildren();
  CFG.formatos.forEach(([nome, desc], i) => box.append(chip(nome, nome, i, escolherFormato, desc)));
}
function desenharResolucoes() {
  const box = $('#resolucoes'); box.replaceChildren();
  resolucoes.forEach((h, i) => box.append(chip(h + 'p', h, i, escolherResolucao)));
}
function escolherFormato(nome) {
  fmtEscolhido = nome; resEscolhida = null; marcar($('#formatos'), nome);
  const f = CFG.formatos.find(x => x[0] === nome);
  $('#fdesc').textContent = f ? f[1] : '';
  if (nome === 'mp4' && resolucoes.length) { desenharResolucoes(); abrir('#etapa-res', true); }
  else { abrir('#etapa-res', false); }
  atualizarBotao();
}
function escolherResolucao(h) { resEscolhida = h; marcar($('#resolucoes'), h); atualizarBotao(); }
function atualizarBotao() {
  const pronto = fmtEscolhido && (fmtEscolhido !== 'mp4' || !resolucoes.length || resEscolhida);
  if (pronto) { $('#baixar-t').textContent = 'Baixar ' + fmtEscolhido + (resEscolhida ? ' · ' + resEscolhida + 'p' : ''); }
  abrir('#etapa-baixar', pronto);
}

$('#link').addEventListener('input', () => {
  clearTimeout(timer); const id = ++infoReq;
  $('#campo').classList.remove('loading'); resetar(); msg(''); status('');
  const url = $('#link').value.trim();
  if (!url) { dividir(false); return; }
  if (!/^https?:\/\//i.test(url)) { status('cole um link http', 'err'); dividir(false); return; }
  timer = setTimeout(() => carregar(url, id), 400);
});

async function carregar(url, id) {
  $('#campo').classList.add('loading'); $('#dir').classList.add('carregando');
  status('carregando vídeo...');
  try {
    const r = await fetch('/api/info', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url})
    });
    const d = await r.json();
    if (id !== infoReq) return;
    if (!r.ok) throw new