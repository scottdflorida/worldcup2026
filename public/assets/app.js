
(function(){
  var KEY='wc26.watch';
  var DEFAULT=Array.isArray(window.WC_DEFAULT_WATCH)?window.WC_DEFAULT_WATCH:[];
  function get(){try{var v=JSON.parse(localStorage.getItem(KEY));if(Array.isArray(v))return v;}catch(e){}return DEFAULT.slice();}
  function save(a){try{localStorage.setItem(KEY,JSON.stringify(a));}catch(e){}}
  function toggle(t){var a=get();var i=a.indexOf(t);if(i>=0)a.splice(i,1);else a.push(t);save(a);apply();}
  function apply(){
    var w=get();
    var host=document.getElementById('your-teams');
    if(host){
      host.innerHTML='';
      if(!w.length){host.innerHTML='<p class="muted empty">No teams pinned yet — tap ★ on any team to follow it here.</p>';}
      else{w.forEach(function(t){
        var src=document.querySelector('#team-src [data-team-card="'+t.replace(/"/g,'\\"')+'"]')
              ||document.querySelector('[data-team-card="'+t.replace(/"/g,'\\"')+'"]');
        if(src)host.appendChild(src.cloneNode(true));
      });}
    }
    document.querySelectorAll('[data-team]').forEach(function(el){
      el.classList.toggle('watched',w.indexOf(el.getAttribute('data-team'))>=0);
    });
    document.querySelectorAll('.bm,.match,.km,.dist-row').forEach(function(el){
      el.classList.toggle('has-watched',!!el.querySelector('.watched'));
    });
    document.querySelectorAll('[data-watch]').forEach(function(btn){
      var on=w.indexOf(btn.getAttribute('data-watch'))>=0;
      btn.classList.toggle('on',on);btn.setAttribute('aria-pressed',on);
      var lab=btn.querySelector('.wl-txt');if(lab)lab.textContent=on?'Watching':'Watch';
    });
  }
  document.addEventListener('click',function(e){
    var b=e.target.closest&&e.target.closest('[data-watch]');
    if(b){e.preventDefault();toggle(b.getAttribute('data-watch'));}
  });
  document.addEventListener('input',function(e){
    if(e.target.id!=='team-search')return;
    var q=e.target.value.trim().toLowerCase();
    document.querySelectorAll('#directory .tcard').forEach(function(c){
      var n=(c.getAttribute('data-team-card')||'').toLowerCase();
      c.style.display=(!q||n.indexOf(q)>=0)?'':'none';
    });
    document.querySelectorAll('.dir-group').forEach(function(g){
      g.style.display=g.querySelector('.tcard:not([style*="display: none"])')?'':'none';
    });
  });
  function wireRefresh(){
    var btn=document.getElementById('refresh-btn');
    var msg=document.getElementById('refresh-msg');
    if(!btn)return;
    function say(t){if(msg)msg.textContent=t||'';}
    function reset(label){btn.disabled=false;btn.classList.remove('busy');
      var t=btn.querySelector('.rf-txt');if(t)t.textContent=label||'Update now';}
    btn.addEventListener('click',function(){
      if(btn.disabled)return;
      btn.disabled=true;btn.classList.add('busy');
      var t=btn.querySelector('.rf-txt');if(t)t.textContent='Checking…';say('Looking for new results…');
      fetch('/api/refresh',{method:'POST'}).then(function(r){
        return r.json().catch(function(){return{};}).then(function(d){return{s:r.status,d:d};});
      }).then(function(res){
        var d=res.d||{};
        if(res.s>=200&&res.s<300&&d.ok){
          if(t)t.textContent='Queued ✓';
          say('Fetching the latest results — this page refreshes in ~90 seconds.');
          setTimeout(function(){location.reload();},90000);
        }else if(res.s===503||d.error==='not_configured'){
          say('Auto-updates run every ~15 min. Manual refresh isn’t configured yet.');reset();
        }else if(res.s===429||d.error==='cooldown'){
          say('Just refreshed — give it a moment before trying again.');setTimeout(function(){reset();},5000);
        }else{
          say('Couldn’t reach the updater. Auto-updates still run on their own.');reset('Try again');
        }
      }).catch(function(){
        say('Couldn’t reach the updater (only works on the live site). Auto-updates still run.');
        reset('Try again');
      });
    });
  }
  document.addEventListener('DOMContentLoaded',function(){apply();wireRefresh();});
})();
