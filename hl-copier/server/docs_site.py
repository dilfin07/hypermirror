"""Самообслуживаемая lib-style страница документации (отдаётся нашим serve.py).

Рендерит markdown из hl-copier/docs/*.md прямо в браузере (вендоренный marked, без CDN).
Источник правды — сами .md файлы: правишь markdown → дока обновляется. Открывается в
новом табе по /docs. Эндпоинты публичные (доки не содержат секретов).
"""
import os

from copier.config import PROJECT_ROOT

DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")
_STATIC = os.path.join(os.path.dirname(__file__), "static")

# порядок и человеко-понятные ярлыки в сайдбаре
ORDER = ["OPERATIONS.md", "COPIER-CORE.md", "MONITOR-AUDIT.md", "MAKER-EXECUTION.md", "PIPELINE-ANALYSIS.md"]


def list_docs():
    if not os.path.isdir(DOCS_DIR):
        return []
    files = [f for f in os.listdir(DOCS_DIR) if f.endswith(".md")]
    files.sort(key=lambda f: (ORDER.index(f) if f in ORDER else 99, f.lower()))
    out = []
    for f in files:
        title = f[:-3]
        try:
            with open(os.path.join(DOCS_DIR, f), encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
        except Exception:
            pass
        out.append({"file": f, "title": title})
    return out


def read_doc(name):
    name = os.path.basename(name or "")          # анти-traversal
    if not name.endswith(".md"):
        return None
    p = os.path.join(DOCS_DIR, name)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _marked():
    try:
        with open(os.path.join(_STATIC, "marked.min.js"), encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return "window.marked={parse:function(s){return '<pre>'+s.replace(/</g,'&lt;')+'</pre>'}};"


def page_html():
    return _VIEWER.replace("/*__MARKED__*/", _marked())


_VIEWER = r"""<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>HL-Copier · Документация</title>
<script>/*__MARKED__*/</script>
<style>
  :root{
    --bg:#0f1115; --panel:#15171c; --border:#262a31; --fg:#e6e8eb; --dim:#9aa1ab;
    --accent:#4dabf7; --code:#1b1e24; --hover:#1c2027;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);
    font:14px/1.65 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
  a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
  header{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:16px;
    height:52px;padding:0 18px;background:var(--panel);border-bottom:1px solid var(--border)}
  header .brand{font-weight:700;white-space:nowrap}
  header .brand small{color:var(--dim);font-weight:400}
  header input{flex:0 1 320px;margin-left:auto;background:var(--bg);border:1px solid var(--border);
    color:var(--fg);border-radius:8px;padding:7px 11px;font-size:13px;outline:none}
  header input:focus{border-color:var(--accent)}
  header .back{color:var(--dim);font-size:13px;white-space:nowrap}
  .wrap{display:grid;grid-template-columns:260px minmax(0,1fr) 220px;gap:0;height:calc(100% - 52px)}
  nav{border-right:1px solid var(--border);overflow:auto;padding:14px 10px;background:var(--panel)}
  nav .grp{color:var(--dim);text-transform:uppercase;font-size:11px;letter-spacing:.4px;margin:6px 8px 8px}
  nav a{display:block;color:var(--fg);padding:7px 10px;border-radius:7px;font-size:13.5px}
  nav a:hover{background:var(--hover);text-decoration:none}
  nav a.active{background:rgba(77,171,247,.14);color:var(--accent)}
  main{overflow:auto;padding:30px 44px 80px}
  article{max-width:820px;margin:0 auto}
  aside{border-left:1px solid var(--border);overflow:auto;padding:24px 14px;font-size:12.5px}
  aside .toc-h{color:var(--dim);text-transform:uppercase;font-size:11px;letter-spacing:.4px;margin-bottom:10px}
  aside a{display:block;color:var(--dim);padding:3px 0}
  aside a.h3{padding-left:12px;font-size:12px}
  aside a:hover{color:var(--fg);text-decoration:none}
  /* markdown */
  article h1{font-size:30px;margin:.2em 0 .5em;line-height:1.2}
  article h2{font-size:22px;margin:1.6em 0 .6em;padding-bottom:.3em;border-bottom:1px solid var(--border)}
  article h3{font-size:17px;margin:1.3em 0 .5em}
  article h4{font-size:14.5px;margin:1.1em 0 .4em;color:var(--dim)}
  article p,article li{color:var(--fg)}
  article code{background:var(--code);border:1px solid var(--border);border-radius:5px;
    padding:.1em .4em;font-size:12.5px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  article pre{background:var(--code);border:1px solid var(--border);border-radius:10px;
    padding:14px 16px;overflow:auto}
  article pre code{background:none;border:none;padding:0;font-size:12.5px;line-height:1.55}
  article blockquote{margin:1em 0;padding:.4em 14px;border-left:3px solid var(--accent);
    background:rgba(77,171,247,.07);color:var(--dim)}
  article table{border-collapse:collapse;width:100%;margin:1em 0;font-size:13px}
  article th,article td{border:1px solid var(--border);padding:7px 10px;text-align:left;vertical-align:top}
  article th{background:var(--panel);color:var(--dim);font-weight:600}
  article tr:nth-child(even) td{background:rgba(255,255,255,.02)}
  article hr{border:none;border-top:1px solid var(--border);margin:1.8em 0}
  article a code{color:var(--accent)}
  h2,h3{scroll-margin-top:64px}
  @media(max-width:1100px){.wrap{grid-template-columns:240px 1fr}aside{display:none}}
  @media(max-width:720px){.wrap{grid-template-columns:1fr}nav{display:none}}
</style></head>
<body>
<header>
  <div class="brand">HL-Copier <small>· Документация</small></div>
  <input id="q" placeholder="Поиск по разделам…" autocomplete="off"/>
  <a class="back" href="/" title="Вернуться в приложение">← в приложение</a>
</header>
<div class="wrap">
  <nav><div class="grp">Документы</div><div id="nav"></div></nav>
  <main><article id="content">Загрузка…</article></main>
  <aside><div class="toc-h">На этой странице</div><div id="toc"></div></aside>
</div>
<script>
  const navEl=document.getElementById('nav'), contentEl=document.getElementById('content'),
        tocEl=document.getElementById('toc'), qEl=document.getElementById('q');
  let DOCS=[], current=null;
  const slug=s=>s.toLowerCase().replace(/[^\wа-яё]+/gi,'-').replace(/(^-|-$)/g,'');

  async function init(){
    try{ DOCS=(await (await fetch('/docs/list')).json()).docs||[]; }catch(e){ DOCS=[]; }
    renderNav();
    const want=decodeURIComponent(location.hash.replace(/^#/,'')).split('::')[0];
    load(DOCS.find(d=>d.file===want)?want:(DOCS[0]&&DOCS[0].file));
  }
  function renderNav(filter){
    navEl.innerHTML='';
    DOCS.filter(d=>!filter||d.title.toLowerCase().includes(filter)).forEach(d=>{
      const a=document.createElement('a'); a.textContent=d.title; a.href='#'+d.file;
      a.className=(d.file===current?'active':''); a.onclick=e=>{e.preventDefault();load(d.file)};
      navEl.appendChild(a);
    });
  }
  async function load(file){
    if(!file){contentEl.innerHTML='<p>Нет документов.</p>';return;}
    current=file; location.hash=file; renderNav(qEl.value.trim().toLowerCase());
    let md=''; try{ md=await (await fetch('/docs/raw?file='+encodeURIComponent(file))).text(); }
    catch(e){ md='# Ошибка\nНе удалось загрузить '+file; }
    contentEl.innerHTML=window.marked?marked.parse(md):('<pre>'+md.replace(/</g,'&lt;')+'</pre>');
    addAnchors(); buildToc(); window.scrollTo(0,0); main_scroll_top();
  }
  function main_scroll_top(){ document.querySelector('main').scrollTop=0; }
  function addAnchors(){
    contentEl.querySelectorAll('h2,h3').forEach(h=>{ if(!h.id) h.id=slug(h.textContent); });
  }
  function buildToc(){
    tocEl.innerHTML='';
    contentEl.querySelectorAll('h2,h3').forEach(h=>{
      const a=document.createElement('a'); a.textContent=h.textContent; a.href='#'+current+'::'+h.id;
      a.className=(h.tagName==='H3'?'h3':''); a.onclick=e=>{e.preventDefault();
        h.scrollIntoView({behavior:'smooth',block:'start'});};
      tocEl.appendChild(a);
    });
  }
  qEl.addEventListener('input',()=>renderNav(qEl.value.trim().toLowerCase()));
  init();
</script>
</body></html>
"""
