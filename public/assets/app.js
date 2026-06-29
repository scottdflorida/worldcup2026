
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
        host.innerHTML='<div class="yt-empty">'+
          '<span class="yt-star" aria-hidden="true">★</span>'+
          '<div class="yt-empty-body">'+
          '<span class="yt-k">EMPTY&nbsp;WATCHLIST</span>'+
          '<b class="yt-h">PIN A TEAM.</b>'+
          '<span class="yt-p">Tap the <span class="yt-inline">★</span> beside any nation — on a group, a team page, or the bracket — '+
          'and it locks in here, marked in vermilion across the whole site.</span>'+
          '<span class="yt-cta"><a href="teams.html">Browse all 48 teams →</a></span>'+
          '</div></div>';
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
    if(document.querySelector('.kbracket'))scheduleDraw();  // recolor watched strokes
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

  // ---- Bracket layout + connectors. Boxes size to their content (a deep round
  // can hold many candidate flags), so we can't rely on CSS alone for vertical
  // centering. We lay the Round-of-32 leaves on an even grid, then place every
  // later box at the midpoint of its two feeders' centres (works for ANY box
  // height), drop the champion plinth right under the final, and draw the
  // right-angle strokes. Progressive enhancement: with JS off the columns just
  // stack top-aligned (still legible); narrow screens use the stacked fallback.
  function updateEdges(){
    var frame=document.querySelector('[data-bracket]');
    var wrap=frame&&frame.querySelector('.bracket-wrap');
    if(!frame||!wrap)return;
    var max=wrap.scrollWidth-wrap.clientWidth;
    frame.classList.toggle('at-start',wrap.scrollLeft<=1);
    frame.classList.toggle('at-end',max<=1||wrap.scrollLeft>=max-1);
  }
  function layoutBracket(){
    var tree=document.querySelector('.kbracket');
    if(!tree)return 0;
    var cols=[].slice.call(tree.querySelectorAll('.kr-col'));
    if(!cols.length)return 0;
    function body(col){return col.querySelector('.kr-body')||col;}
    function cards(col){return [].slice.call(body(col).querySelectorAll('.km'));}
    // Reset prior positioning so heights measure naturally.
    cols.forEach(function(col){
      cards(col).forEach(function(k){k.style.position='';k.style.top='';k.style.left='';k.style.right='';});
      var pl=col.querySelector('.champion-plinth');
      if(pl){pl.style.position='';pl.style.top='';pl.style.left='';pl.style.right='';}
      body(col).style.height='';
    });

    var leaves=cards(cols[0]);
    if(!leaves.length)return 0;
    var maxLeafH=0;leaves.forEach(function(k){maxLeafH=Math.max(maxLeafH,k.offsetHeight);});
    var slot=maxLeafH+28;                       // even vertical pitch for the leaves
    var bodyH=leaves.length*slot;
    var prev=null;
    cols.forEach(function(col,ci){
      var b=body(col);b.style.position='relative';b.style.height=bodyH+'px';
      var ks=cards(col),centers=[];
      ks.forEach(function(k,i){
        var c;
        if(ci===0){c=(i+0.5)*slot;}
        else{var a=prev[i*2],z=prev[i*2+1];
          c=(a!=null&&z!=null)?(a+z)/2:(a!=null?a:(z!=null?z:(i+0.5)*slot));}
        k.style.position='absolute';k.style.left='0';k.style.right='0';
        k.style.top=Math.round(c-k.offsetHeight/2)+'px';
        centers.push(c);
      });
      var plinth=col.querySelector('.champion-plinth');
      if(plinth&&ks.length){
        var fb=ks[ks.length-1];
        plinth.style.position='absolute';plinth.style.left='0';plinth.style.right='0';
        plinth.style.top=Math.round((parseFloat(fb.style.top)||0)+fb.offsetHeight+16)+'px';
      }
      prev=centers;
    });
    return bodyH;
  }
  function drawBracket(){
    var tree=document.querySelector('.kbracket');
    if(!tree)return;
    layoutBracket();
    updateEdges();
    var svg=tree.querySelector('.bz-layer');
    if(!svg)return;
    while(svg.firstChild)svg.removeChild(svg.firstChild);
    var cols=[].slice.call(tree.querySelectorAll('.kr-col'));
    if(cols.length<2)return;
    var W=tree.scrollWidth,H=tree.scrollHeight;
    svg.setAttribute('width',W);svg.setAttribute('height',H);
    svg.setAttribute('viewBox','0 0 '+W+' '+H);
    var kb=tree.getBoundingClientRect();
    // km positions are scroll-invariant relative to .kbracket (both move with the
    // scroller together), so no scrollLeft term is needed.
    function box(el){var r=el.getBoundingClientRect();
      return {left:r.left-kb.left,right:r.right-kb.left,y:r.top-kb.top+r.height/2};}
    var cards=cols.map(function(col){return [].slice.call(col.querySelectorAll('.km'));});
    var made=0;
    for(var ci=1;ci<cards.length;ci++){
      for(var i=0;i<cards[ci].length;i++){
        var child=box(cards[ci][i]);
        [cards[ci-1][i*2],cards[ci-1][i*2+1]].forEach(function(p){
          if(!p)return;
          var pc=box(p);
          var x1=pc.right,y1=pc.y,x2=child.left,y2=child.y,mx=Math.round((x1+x2)/2);
          var d='M'+x1+' '+y1+' H'+mx+' V'+y2+' H'+x2;   // right angles only
          var path=document.createElementNS('http://www.w3.org/2000/svg','path');
          path.setAttribute('d',d);path.setAttribute('class','bz-link');path.setAttribute('fill','none');
          // Highlight only the segment LEAVING a watched team's game (its path
          // forward) — never the opponent's feed into that next game.
          if(p.classList.contains('has-watched'))path.setAttribute('data-watched','1');
          svg.appendChild(path);made++;
        });
      }
    }
    tree.setAttribute('data-links',made);
  }
  var rzTimer;
  function scheduleDraw(){clearTimeout(rzTimer);rzTimer=setTimeout(drawBracket,60);}
  // Box heights depend on how many candidate flags wrap, which depends on the
  // emoji metrics — and those can land AFTER our first measure (font/emoji paint),
  // leaving stale positions (overlaps). Re-lay out once fonts are ready and again
  // whenever any box actually changes size. Layout only moves boxes (never resizes
  // them), so observing size changes can't loop.
  function wireBracketObserver(){
    var tree=document.querySelector('.kbracket');
    if(!tree)return;
    if(document.fonts&&document.fonts.ready)document.fonts.ready.then(scheduleDraw);
    if(typeof ResizeObserver==='undefined')return;
    var ro=new ResizeObserver(scheduleDraw);
    tree.querySelectorAll('.km,.champion-plinth').forEach(function(el){ro.observe(el);});
  }


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

  function wireBracketScroll(){
    var wrap=document.querySelector('[data-bracket] .bracket-wrap');
    if(!wrap)return;
    wrap.addEventListener('scroll',updateEdges,{passive:true});
  }
  // On a phone the columns scroll-snap one at a time; open on the CURRENT round
  // (left-aligned), or the far-right column right-aligned. Once only — don't yank
  // the user back on later redraws.
  function landOnActiveColumn(){
    if(window.innerWidth>=720)return;
    var wrap=document.querySelector('[data-bracket] .bracket-wrap');
    var tree=wrap&&wrap.querySelector('.kbracket');
    if(!wrap||!tree)return;
    var cols=tree.querySelectorAll('.kr-col');
    var on=document.querySelector('.brn-item.on');
    var idx=Math.min(on?parseInt(on.getAttribute('data-rd'),10)||0:0, cols.length-1);
    var col=cols[idx]; if(!col)return;
    var target=(idx===cols.length-1)
      ? col.offsetLeft+col.offsetWidth-wrap.clientWidth     // last: right-aligned
      : col.offsetLeft-14;                                  // else: left-aligned
    wrap.scrollLeft=Math.max(0,target);
    updateEdges();
  }

  document.addEventListener('DOMContentLoaded',function(){
    apply();wireReveal();wireLive();wireBracketScroll();wireBracketObserver();drawBracket();
    landOnActiveColumn();
  });
  window.addEventListener('load',drawBracket);
  window.addEventListener('resize',scheduleDraw);
})();
