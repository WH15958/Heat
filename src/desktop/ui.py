"""Small offline startup/error pages; experiment UI remains the Vue application."""
import html


def page(title, message, *, action=None, label=None):
    button = ""
    script = ""
    if action:
        # Actions are application-owned constants, never source-directory text.
        if action not in {"choose_source", "start_backend", "request_exit"}:
            raise ValueError("Unknown desktop action")
        button = f'<button id="action" disabled>{html.escape(label or "继续")}</button>'
        script = """
        <script>
        window.addEventListener('pywebviewready',()=>{
          let action='ACTION';
          const b=document.getElementById('action'); b.disabled=false;
          b.onclick=async()=>{b.disabled=true;try{
            const r=await pywebview.api[action]();
            if(r && r.url){window.location.assign(r.url);return}
            if(r && r.page){
              const p=r.page;
              document.getElementById('page-title').textContent=p.title;
              document.getElementById('page-message').textContent=p.message;
              action=p.action;b.textContent=p.label;
            }
            if(r && r.error) document.getElementById('detail').textContent=r.error;
            else document.getElementById('detail').textContent='';
          }catch(e){document.getElementById('detail').textContent=String(e)}
          finally{b.disabled=false}};
        });
        </script>""".replace("ACTION", action)
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Heat</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#f5f7fb;color:#172033;
      font:16px/1.8 'Microsoft YaHei',sans-serif;display:grid;place-items:center;min-height:100vh}}
    main{{width:min(720px,90vw);padding:48px;background:white;border-radius:16px;
      box-shadow:0 12px 40px #1f315010}}.brand{{color:#863bff;font-weight:bold;letter-spacing:2px}}
    h1{{font-size:26px;margin:12px 0}}p{{white-space:pre-wrap;color:#526077}}
    button{{background:#6c42df;color:white;border:0;border-radius:8px;padding:12px 24px;
      cursor:pointer;font:inherit}}button:disabled{{opacity:.5;cursor:wait}}
    #detail{{color:#b83232;white-space:pre-wrap}}</style><main><div class="brand">HEAT</div>
    <h1 id="page-title">{html.escape(title)}</h1><p id="page-message">{html.escape(message)}</p>{button}
    <p id="detail" role="alert"></p></main>{script}</html>"""
