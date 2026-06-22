
(function(){
  var KEY='wc26.watch';
  var DEFAULT=Array.isArray(window.WC_DEFAULT_WATCH)?window.WC_DEFAULT_WATCH:[];
  function get(){try{var v=JSON.parse(localStorage.getItem(KEY));if(Array.isArray(v))return v;}catch(e){}return DEFAULT.slice();}
  function save(a){try{localStorage.setItem(KEY,JSON.stringify(a));}catch(e){}}
  function toggle(t){var a=get();var i=a.indexOf(t);if(i>=0)a.splice(i,1);else a.push(t);save(a);apply();}
  function esc(t){return (window.CSS&&CSS.escape)?CSS.escape(t):t.replace(/"/g,'\\"');}
  function apply(){
    var w=get();
    var host=document.getElementById('your-teams');
    if(host){
      host.innerHTML='';
      if(!w.length){
        host.innerHTML='<div class="yt-empty"><span class="yt-star" aria-hidden="true">★</span>'+
          '<div class="yt-empty-body"><b>Follow your teams.</b>'+
          '<span class="muted">Tap the ★ on any team — on a group, a team page or the bracket — '+
          'and they’ll live here and glow across the whole site.</span></div></div>';
      } else {
        w.forEach(function(t){
          var src=document.querySelector('#team-src [data-team-card="'+esc(t)+'"]')
                ||document.querySelector('[data-team-card="'+esc(t)+'"]');
          if(src)host.appendChild(src.cloneNode(true));
        });
      }
    }
    document.querySelectorAll('[data-team]').forEach(function(el){
      var t=el.getAttribute('data-team');
      el.classList.toggle('watched', !!t && w.indexOf(t)>=0);
    });
    document.querySelectorAll('.match,.km,.dist-row,.pz,.road-step,.tcard').forEach(function(el){
      el.classList.toggle('has-watched',!!el.querySelector('.watched'));
    });
    document.querySelectorAll('[data-watch]').forEach(function(btn){
      var on=w.indexOf(btn.getAttribute('data-watch'))>=0;
      btn.classList.toggle('on',on);btn.setAttribute('aria-pressed',on?'true':'false');
      var lab=btn.querySelector('.wl-txt');if(lab)lab.textContent=on?'Watching':'Watch';
    });
  }
  document.addEventListener('click',function(e){
    var b=e.target.closest&&e.target.closest('[data-watch]');
    if(b){e.preventDefault();toggle(b.getAttribute('data-watch'));}
  });
  // Search the team directory.
  document.addEventListener('input',function(e){
    if(e.target.id!=='team-search')return;
    var q=e.target.value.trim().toLowerCase();
    var anyVisible=false;
    document.querySelectorAll('#directory .tcard').forEach(function(c){
      var n=(c.getAttribute('data-team-card')||'').toLowerCase();
      var show=(!q||n.indexOf(q)>=0);
      c.hidden=!show; if(show)anyVisible=true;
    });
    document.querySelectorAll('.dir-group').forEach(function(g){
      g.hidden=!g.querySelector('.tcard:not([hidden])');
    });
    var em=document.getElementById('search-empty');
    if(em)em.hidden=anyVisible;
  });

  // ---- Bracket layout: position each later-round card at the vertical midpoint
  // of its two feeding parents so the columns read as one true tournament tree
  // (card i in round R sits between cards 2i and 2i+1 of round R-1). Then draw
  // connector strokes from each card up to its parents. Both are progressive
  // enhancement; the bracket is fully legible (a clean column stack) without JS.
  function layoutBracket(){
    var tree=document.querySelector('.kbracket');
    if(!tree)return;
    var cols=[].slice.call(tree.querySelectorAll('.kr-col'));
    if(cols.length<2)return;
    var W=window.innerWidth;
    // Reset any prior positioning first (so resize recomputes from scratch).
    cols.forEach(function(col){
      [].slice.call(col.querySelectorAll('.km')).forEach(function(k){
        k.style.position='';k.style.top='';k.style.left='';k.style.right='';k.style.width='';
      });
      col.style.position='';
    });
    if(W<720){tree.classList.remove('bracket-laid');return;} // narrow: simple stacked layout
    tree.classList.add('bracket-laid');
    function cards(col){return [].slice.call(col.querySelectorAll('.km'));}
    // Establish baseline centers for round 0 in column-local coords.
    var prevCenters=null;
    cols.forEach(function(col,ci){
      col.style.position='relative';
      var ks=cards(col);
      if(ci===0){
        prevCenters=ks.map(function(k){return k.offsetTop+k.offsetHeight/2;});
        return;
      }
      var headH=0;var head=col.querySelector('.kr-head');
      if(head)headH=head.offsetTop; // cards start after the round header
      var centers=[];
      ks.forEach(function(k,i){
        var pa=prevCenters[i*2],pb=prevCenters[i*2+1];
        var mid;
        if(pa!=null&&pb!=null)mid=(pa+pb)/2;
        else if(pa!=null)mid=pa;
        else mid=k.offsetTop+k.offsetHeight/2;
        k.style.position='absolute';
        k.style.left='0';k.style.right='0';
        k.style.top=Math.round(mid-k.offsetHeight/2)+'px';
        centers.push(mid);
      });
      // Final column also carries the champion plinth, anchored under its match.
      var plinth=col.querySelector('.champion-plinth');
      if(plinth&&ks.length&&centers.length){
        var fk=ks[0];
        var topPx=parseFloat(fk.style.top)||0;
        plinth.style.position='absolute';
        plinth.style.left='0';plinth.style.right='0';
        plinth.style.top=Math.round(topPx+fk.offsetHeight+18)+'px';
      }
      prevCenters=centers;
    });
  }
  function drawBracket(){
    var tree=document.querySelector('.kbracket');
    if(!tree)return;
    layoutBracket();
    var svg=tree.querySelector('.bz-layer');
    if(!svg)return;
    // On narrow screens the tree is a simple stacked list — no connector layer.
    if(window.innerWidth<720){while(svg.firstChild)svg.removeChild(svg.firstChild);
      svg.setAttribute('width',0);svg.setAttribute('height',0);tree.setAttribute('data-links',0);return;}
    var cols=tree.querySelectorAll('.kr-col');
    if(cols.length<2)return;
    var box=tree.getBoundingClientRect();
    svg.setAttribute('width',tree.scrollWidth);
    svg.setAttribute('height',tree.scrollHeight);
    svg.setAttribute('viewBox','0 0 '+tree.scrollWidth+' '+tree.scrollHeight);
    while(svg.firstChild)svg.removeChild(svg.firstChild);
    var cards=[];
    cols.forEach(function(col,ci){cards[ci]=col.querySelectorAll('.km, .champion-plinth');});
    function center(el){var r=el.getBoundingClientRect();
      return {x:r.left-box.left+tree.scrollLeft,y:r.top-box.top+tree.scrollTop+r.height/2,
              left:r.left-box.left+tree.scrollLeft,right:r.right-box.left+tree.scrollLeft,h:r.height};}
    var made=0;
    for(var ci=1;ci<cards.length;ci++){
      var prev=cards[ci-1],cur=cards[ci];
      for(var i=0;i<cur.length;i++){
        var child=center(cur[i]);
        var p1=prev[i*2],p2=prev[i*2+1];
        [p1,p2].forEach(function(p){
          if(!p)return;
          var pc=center(p);
          var x1=pc.right,y1=pc.y,x2=child.left,y2=child.y;
          var mx=(x1+x2)/2;
          var d='M'+x1+' '+y1+' C'+mx+' '+y1+' '+mx+' '+y2+' '+x2+' '+y2;
          var path=document.createElementNS('http://www.w3.org/2000/svg','path');
          path.setAttribute('d',d);path.setAttribute('class','bz-link');
          path.setAttribute('fill','none');
          if(p.classList.contains('has-watched')||cur[i].classList.contains('has-watched'))
            path.setAttribute('data-watched','1');
          svg.appendChild(path);made++;
        });
      }
    }
    tree.setAttribute('data-links',made);
  }
  var rzTimer;
  function scheduleDraw(){clearTimeout(rzTimer);rzTimer=setTimeout(drawBracket,60);}


  // Entrance motion: progressive enhancement only. Content is visible by default
  // (CSS). We opt the page into a CSS-only fade-up — which always ENDS visible —
  // unless the user prefers reduced motion, in which case we leave it untouched.
  function wireReveal(){
    var mq=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)');
    if(mq&&mq.matches)return; // honor reduced motion: no entrance animation at all
    document.documentElement.classList.add('reveal-ready');
  }

  // Live scores: overlay ESPN's public feed onto in-progress matches. The static
  // site only knows FINAL scores (openfootball posts at full time), so a match
  // that is live right now renders as "Kicks off …" until then. This fills in the
  // live score + minute and a LIVE pulse, polling every 30s while anything is in
  // play. Pure progressive enhancement: if /api/live is unreachable (e.g. local
  // preview) it silently no-ops and the static site stands on its own.
  function liveCanon(s){
    // NFKD splits accents off (ü -> u+◌̈); the final [^a-z0-9] strip then drops the
    // combining marks and punctuation, so "Türkiye"->turkiye, "Curaçao"->curacao.
    s=(s||'').normalize('NFKD').toLowerCase().replace(/&/g,'and').replace(/[^a-z0-9]/g,'');
    var A={bosniaandherzegovina:'bosnia',bosniaherzegovina:'bosnia',czechrepublic:'czech',
      czechia:'czech',drcongo:'congodr',congodr:'congodr',turkey:'turkey',turkiye:'turkey',
      usa:'usa',unitedstates:'usa'};
    return A[s]||s;
  }
  function livePair(a,b){var x=liveCanon(a),y=liveCanon(b);return x<y?x+'~'+y:y+'~'+x;}
  function wireLive(){
    var nodes=document.querySelectorAll('[data-live]');
    if(!nodes.length)return;
    var idx={};
    nodes.forEach(function(el){
      var names=[];
      el.querySelectorAll('[data-team]').forEach(function(t){
        var n=t.getAttribute('data-team');if(n)names.push(n);});
      if(names.length<2)return;
      var k=livePair(names[0],names[1]);
      (idx[k]=idx[k]||[]).push(el);
    });
    if(!Object.keys(idx).length)return;
    function paint(el,m){
      if(el.classList.contains('is-done'))return;        // official FT already shown
      if(m.s1==null||m.s2==null)return;
      var teams=el.querySelectorAll('[data-team]');
      var firstIsHome=liveCanon(teams[0].getAttribute('data-team'))===liveCanon(m.t1);
      var g1=firstIsHome?m.s1:m.s2, g2=firstIsHome?m.s2:m.s1;
      var mid=el.querySelector('[data-live-mid]');
      if(mid){
        mid.innerHTML='<b class="sg'+(g1>g2?' win':'')+'">'+g1+'</b>'+
          '<span class="sdash">–</span><b class="sg'+(g2>g1?' win':'')+'">'+g2+'</b>';
        mid.classList.add('live-mid');
      }
      var inplay=m.state==='in';
      el.classList.toggle('is-live',inplay);
      el.classList.toggle('is-livedone',m.state==='post');
      var tag=el.querySelector('[data-live-tag]');
      if(tag){
        tag.hidden=false;
        tag.className=tag.className.replace(/\b(up|done|live)\b/g,'').replace(/\s+/g,' ').trim();
        if(inplay){tag.textContent=m.clock||'LIVE';tag.className+=' live';}
        else{tag.textContent='FT';tag.className+=' done';}
      }
    }
    var timer=null;
    function schedule(any){clearTimeout(timer);
      if(any&&document.visibilityState!=='hidden')timer=setTimeout(poll,30000);}
    function poll(){
      fetch('/api/live',{headers:{accept:'application/json'}})
       .then(function(r){return r.ok?r.json():null;})
       .then(function(d){
         if(!d||!d.ok||!d.matches){schedule(false);return;}
         var any=false;
         d.matches.forEach(function(m){
           if(m.state==='pre')return;
           var list=idx[livePair(m.t1,m.t2)];if(!list)return;
           if(m.state==='in')any=true;
           list.forEach(function(el){paint(el,m);});
         });
         schedule(any);
       }).catch(function(){schedule(false);});
    }
    document.addEventListener('visibilitychange',function(){
      if(document.visibilityState==='visible')poll();});
    window.__wcPollLive=poll;                              // diagnostic / test seam
    poll();
  }

  document.addEventListener('DOMContentLoaded',function(){
    apply();wireReveal();wireLive();drawBracket();
  });
  window.addEventListener('load',drawBracket);
  window.addEventListener('resize',scheduleDraw);
})();
