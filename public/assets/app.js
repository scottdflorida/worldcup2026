
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
    document.querySelectorAll('.match,.km,.dist-row,.pz,.road-step,.tcard,.cal-m').forEach(function(el){
      el.classList.toggle('has-watched',!!el.querySelector('.watched'));
    });
    document.querySelectorAll('[data-watch]').forEach(function(btn){
      var on=w.indexOf(btn.getAttribute('data-watch'))>=0;
      btn.classList.toggle('on',on);btn.setAttribute('aria-pressed',on?'true':'false');
      var lab=btn.querySelector('.wl-txt');if(lab)lab.textContent=on?'Watching':'Watch';
    });
    if(document.querySelector('.kbracket'))scheduleDraw();  // recolor watched strokes
    applyTZ();  // re-render times (incl. the freshly cloned Your-teams cards)
  }
  // ---- time zone: re-render every [data-utc] time in the viewer's chosen zone ----
  var TZS={'America/New_York':'ET','America/Chicago':'CT','America/Denver':'MT',
           'America/Los_Angeles':'PT','America/Sao_Paulo':'BRT'};
  var TZ_KEY='wc26.tz', TZ_DEFAULT='America/Los_Angeles';
  function getTZ(){try{var v=localStorage.getItem(TZ_KEY);if(v&&TZS[v])return v;}catch(e){}return TZ_DEFAULT;}
  function setTZ(v){try{localStorage.setItem(TZ_KEY,v);}catch(e){}}
  function tzParts(utc,tz){
    var d=new Date(utc);
    if(isNaN(d))return null;
    var day=new Intl.DateTimeFormat('en-US',{timeZone:tz,weekday:'short',month:'short',day:'numeric'}).format(d).replace(/,/g,'');
    var time=new Intl.DateTimeFormat('en-US',{timeZone:tz,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(d);
    return {day:day,time:time};
  }
  function applyTZ(){
    var tz=getTZ(), label=TZS[tz]||'';
    document.querySelectorAll('[data-utc]').forEach(function(el){
      if(el.classList.contains('live-mid'))return;          // currently showing a live score
      var p=tzParts(el.getAttribute('data-utc'),tz); if(!p)return;
      var fmt=el.getAttribute('data-tfmt');
      if(fmt==='day'){el.textContent=p.day;return;}
      if(fmt==='daytime'){
        var dy=el.querySelector('.ko-day'); if(dy)dy.textContent=p.day;
        var tm=el.querySelector('.ko-time');
        if(tm){var c=(tm.querySelector('.tz')||{}).className||'ko-tz tz';
          tm.innerHTML=p.time+'<span class="'+c+'">'+label+'</span>';}
        return;
      }
      var cc=(el.querySelector('.tz')||{}).className||'tz';   // 'time'
      el.innerHTML=p.time+'<span class="'+cc+'">'+label+'</span>';
    });
  }
  function wireTZ(){
    var sel=document.getElementById('tz-select'); if(!sel)return;
    sel.value=getTZ();
    sel.addEventListener('change',function(){setTZ(sel.value);applyTZ();});
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

  // ---- Fantasy bracket: a flags-only pick-the-winner knockout tree ----
  function initFantasy(){
    var root=document.querySelector('.fb'); if(!root||!window.FB_DATA)return;
    var M=window.FB_DATA.matches, FLAGS=window.FB_DATA.flags, FKEY='wc26.fantasy';
    var picks={}; try{var v=JSON.parse(localStorage.getItem(FKEY));if(v&&typeof v==='object')picks=v;}catch(e){}
    function savePicks(){try{localStorage.setItem(FKEY,JSON.stringify(picks));}catch(e){}}
    function occupant(num){var m=M[num];if(!m)return null;return m.winner||picks[num]||null;}
    function feasible(num,depth){
      depth=depth||0;var m=M[num];if(!m||depth>10)return [];
      if(m.winner)return [m.winner];
      if(m.round==='R32'){
        var o=[];(m.entrants||[]).forEach(function(e){if(e.team)o.push(e.team);else (e.pool||[]).forEach(function(t){o.push(t);});});return o;
      }
      var seen={},res=[];
      (m.feeders||[]).forEach(function(f){
        var p=occupant(f),arr=p?[p]:feasible(f,depth+1);
        arr.forEach(function(t){if(!seen[t]){seen[t]=1;res.push(t);}});
      });
      return res;
    }
    function prune(){  // drop any pick that's no longer reachable, parents first
      ['R32','R16','QF','SF','F'].forEach(function(rd){
        Object.keys(picks).forEach(function(num){
          if(M[num]&&M[num].round===rd&&feasible(num).indexOf(picks[num])<0)delete picks[num];
        });
      });
    }
    function render(){
      prune();
      root.querySelectorAll('.fb-node').forEach(function(node){
        var occ=occupant(node.getAttribute('data-m')),fl=node.querySelector('.fb-fl');
        if(fl)fl.textContent=occ?(FLAGS[occ]||''):'';
        node.classList.toggle('fb-filled',!!occ);
        node.classList.toggle('fb-empty',!occ);
      });
      // outer flag layer: once an R32 is decided, dim the team that didn't advance
      root.querySelectorAll('.fb-ent[data-r32]').forEach(function(el){
        var occ=occupant(el.getAttribute('data-r32')),t=el.getAttribute('data-team');
        el.classList.toggle('fb-ent-out',!!occ&&t!==occ);
      });
      savePicks();
    }
    // every match is one box: tap it to pick the winner (settled ties are locked)
    root.addEventListener('click',function(e){
      var pk=e.target.closest('.fb-pick');
      if(pk&&!pk.classList.contains('fb-locked'))openModal(pk.getAttribute('data-m'));
    });
    // modal picker for later rounds
    var modal=document.getElementById('fb-modal'),
        grid=document.getElementById('fb-modal-grid'),cur=null;
    function openModal(num){
      cur=num;var opts=feasible(num);
      if(!opts.length)return;
      grid.innerHTML=opts.map(function(t){
        return '<button class="fb-opt" type="button" data-team="'+t.replace(/"/g,'&quot;')+'">'+(FLAGS[t]||'')+'</button>';
      }).join('');
      modal.hidden=false;
    }
    function closeModal(){modal.hidden=true;cur=null;}
    modal.addEventListener('click',function(e){
      if(e.target.closest('[data-fb-close]')){closeModal();return;}
      if(e.target.closest('[data-fb-clear]')){if(cur)delete picks[cur];closeModal();render();return;}
      var o=e.target.closest('.fb-opt');
      if(o&&cur){picks[cur]=o.getAttribute('data-team');closeModal();render();}
    });
    document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!modal.hidden)closeModal();});
    var reset=document.getElementById('fb-reset');
    if(reset)reset.addEventListener('click',function(){picks={};render();});
    render();
  }

  document.addEventListener('DOMContentLoaded',function(){
    wireTZ();apply();wireReveal();wireLive();wireBracketScroll();wireBracketObserver();drawBracket();
    landOnActiveColumn();initFantasy();
  });
  window.addEventListener('load',drawBracket);
  window.addEventListener('resize',scheduleDraw);
})();
