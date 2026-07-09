
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
      if(fmt==='stamp'){   // footer "updated" stamp: month day, year · time + zone
        var sd=new Date(el.getAttribute('data-utc'));
        var ds=new Intl.DateTimeFormat('en-US',{timeZone:tz,month:'short',day:'numeric',year:'numeric'}).format(sd);
        el.textContent=ds+' · '+p.time+' '+label;return;
      }
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
      usa:'usa',unitedstates:'usa',
      // ESPN spellings → the site's canonical token for the same nation
      korearepublic:'southkorea',southkorea:'southkorea',
      caboverde:'capeverde',capeverde:'capeverde',
      cotedivoire:'ivorycoast',ivorycoast:'ivorycoast',
      iriran:'iran',iran:'iran'};
    return A[s]||s;
  }
  function livePair(a,b){var x=liveCanon(a),y=liveCanon(b);return x<y?x+'~'+y:y+'~'+x;}
  function wireLive(){
    var nodes=document.querySelectorAll('[data-live]');
    if(!nodes.length)return;
    var idx={}, stamps=[];
    nodes.forEach(function(el){
      var names=[];
      el.querySelectorAll('[data-team]').forEach(function(t){
        var n=t.getAttribute('data-team');if(n)names.push(n);});
      if(names.length<2)return;
      var k=livePair(names[0],names[1]);
      (idx[k]=idx[k]||[]).push(el);
      var ts=parseInt(el.getAttribute('data-ts'),10);   // kickoff instant, epoch seconds
      if(!isNaN(ts))stamps.push(ts);
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
    // Scheduler: while anything is in play, poll every 30s. Otherwise, if the
    // earliest upcoming kickoff is within WINDOW, wake ~LEAD before it and start
    // polling; if the next kickoff is further out (or there is none), stop — a tab
    // that becomes visible re-arms us. A busy flag prevents overlapping fetches
    // (e.g. a visibility poll landing on top of a scheduled one).
    var WINDOW=2*3600, LEAD=60, LIVE_EVERY=30000;
    var timer=null, busy=false, lastAny=false;   // lastAny: last successful poll saw a live match
    function nextWait(){                     // ms until the next poll, or null to stop
      var now=Date.now()/1000, best=null;
      for(var i=0;i<stamps.length;i++){if(stamps[i]>now&&(best===null||stamps[i]<best))best=stamps[i];}
      if(best===null)return null;            // nothing upcoming at all
      if(best-now>WINDOW)return (best-now-WINDOW)*1000; // far out: sleep until the window opens
      var w=(best-LEAD-now)*1000;            // (so a tab left open all day still wakes for kickoff)
      return w>LIVE_EVERY?w:LIVE_EVERY;      // near/inside the lead window, keep the 30s cadence
    }
    function schedule(anyLive){
      clearTimeout(timer);timer=null;
      if(document.visibilityState==='hidden')return;   // paused; re-armed on visibility
      if(anyLive){timer=setTimeout(poll,LIVE_EVERY);return;}
      var w=nextWait();
      if(w!==null)timer=setTimeout(poll,w);
    }
    function poll(){
      if(busy)return;                        // an in-flight fetch is already running
      busy=true;
      fetch('/api/live',{headers:{accept:'application/json'}})
       .then(function(r){return r.ok?r.json():null;})
       .then(function(d){
         busy=false;
         if(!d||!d.ok||!d.matches){schedule(false);return;}
         var any=false;
         d.matches.forEach(function(m){
           if(m.state==='pre')return;
           var list=idx[livePair(m.t1,m.t2)];if(!list)return;
           if(m.state==='in')any=true;
           list.forEach(function(el){paint(el,m);});
         });
         lastAny=any;
         schedule(any);
       }).catch(function(){busy=false;schedule(lastAny);});
       // error → retry on the last known cadence: keep 30s while a match was live
       // (kickoff stamps are past by then, so schedule(false) would go dormant
       // mid-match); otherwise nextWait bounds it and stops when nothing upcoming.
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
    // lift the modal out of <main> (its own stacking context) so it paints above
    // the footer instead of behind it
    if(modal&&modal.parentNode!==document.body)document.body.appendChild(modal);
    function he(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
    function openModal(num){
      cur=num;var opts=feasible(num);
      if(!opts.length)return;
      grid.innerHTML=opts.map(function(t){
        return '<button class="fb-opt" type="button" data-team="'+he(t)+'">'+
          '<span class="fb-opt-fl">'+(FLAGS[t]||'')+'</span>'+
          '<span class="fb-opt-nm">'+he(t)+'</span></button>';
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
    // right-angle connectors from each pair of feeders into the game they feed
    function drawLines(){
      var svg=root.querySelector('.fb-lines'),p=svg&&svg.querySelector('path');
      if(!p)return;
      var rb=root.getBoundingClientRect(); if(!rb.width)return;
      svg.setAttribute('viewBox','0 0 '+rb.width+' '+rb.height);
      function geom(el){var r=el.getBoundingClientRect();
        return {y:(r.top+r.bottom)/2-rb.top,l:r.left-rb.left,r:r.right-rb.left,cx:(r.left+r.right)/2-rb.left};}
      var d=[];
      root.querySelectorAll('.fb-pick').forEach(function(bx){
        var num=bx.getAttribute('data-m'),m=M[num],fe=[];
        if(m.round==='R32')fe=[].slice.call(root.querySelectorAll('.fb-ent[data-r32="'+num+'"]'));
        else (m.feeders||[]).forEach(function(f){var el=root.querySelector('.fb-pick[data-m="'+f+'"]');if(el)fe.push(el);});
        var b=geom(bx);
        fe.forEach(function(el){
          var f=geom(el),right=b.cx>f.cx,x1=right?f.r:f.l,x2=right?b.l:b.r,mx=(x1+x2)/2;
          d.push('M'+x1.toFixed(1)+' '+f.y.toFixed(1)+'H'+mx.toFixed(1)+'V'+b.y.toFixed(1)+'H'+x2.toFixed(1));
        });
      });
      p.setAttribute('d',d.join(' '));
    }
    var lt=null;
    window.addEventListener('resize',function(){clearTimeout(lt);lt=setTimeout(drawLines,100);});
    if(document.fonts&&document.fonts.ready)document.fonts.ready.then(drawLines);
    render();drawLines();
    requestAnimationFrame(drawLines);
  }

  // ---- Betting pool: play-money wagers on knockout matches (backed by a Function) ----
  function initBetting(){
    var app=document.getElementById('bet-app'); if(!app)return;
    var state=null, joining=false, leaveArmed=false;
    var showBets=true; try{showBets=localStorage.getItem('wc26.betshow')!=='0';}catch(e){}
    function setShowBets(v){showBets=v;try{localStorage.setItem('wc26.betshow',v?'1':'0');}catch(e){}render();}
    // memberships of multiple pools live on this device; the active pool's token
    // identifies you to the server (the legacy cookie is a one-time import fallback)
    var mem={active:null,pools:[]}; try{var mv=JSON.parse(localStorage.getItem('wc26.bets'));if(mv&&mv.pools)mem=mv;}catch(e){}
    function saveMem(){try{localStorage.setItem('wc26.bets',JSON.stringify(mem));}catch(e){}}
    function activeTok(){for(var i=0;i<mem.pools.length;i++)if(mem.pools[i].code===mem.active)return mem.pools[i].token;return null;}
    function upsertPool(p){for(var i=0;i<mem.pools.length;i++)if(mem.pools[i].code===p.code){mem.pools[i]=p;mem.active=p.code;saveMem();return;}mem.pools.push(p);mem.active=p.code;saveMem();}
    function dropPool(code){mem.pools=mem.pools.filter(function(p){return p.code!==code;});if(mem.active===code)mem.active=mem.pools.length?mem.pools[0].code:null;saveMem();}
    function api(path,opts){
      opts=opts||{};var h=Object.assign({'content-type':'application/json'},opts.headers||{});
      var t=activeTok();if(t)h['X-Bet-Token']=t;
      return fetch('/api/bets/'+path,Object.assign({},opts,{headers:h})).then(function(r){return r.json();});
    }
    function he(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
    function money(n){return '$'+(Math.round(n*100)/100).toFixed(2);}
    function matchById(num){var a=(state.matches||[]);for(var i=0;i<a.length;i++)if(a[i].num===num)return a[i];return null;}
    function showErr(id,msg){var e=document.getElementById(id);if(e){e.textContent=msg;e.hidden=false;}}
    var NETERR='Network error — nothing was changed. Try again.';
    function load(){
      leaveArmed=false;
      api('state').then(function(s){
        state=s;
        if(s.joined&&s.token&&s.pool){upsertPool({code:s.pool.code,name:s.me.name,token:s.token});}
        else if(!s.joined&&mem.active){dropPool(mem.active);if(mem.active){load();return;}}  // stale token
        render();
      }).catch(function(){app.innerHTML='<div class="bet-card"><p class="muted">Could not reach the betting service.</p></div>';});
    }
    function render(){
      if(!state||state.configured===false){app.innerHTML='<div class="bet-card"><p class="muted">The betting pool is not set up on the server yet.</p></div>';return;}
      if(joining||!state.joined){renderJoin();return;}
      renderPool();
    }
    function renderJoin(){
      var canCancel=mem.pools.length>0;
      app.innerHTML='<div class="bet-card bet-join"><h2>'+(canCancel?'Join another pool':'Join a pool')+'</h2>'+
        '<p class="muted">Pick a display name and a pool code. Share the code so everyone is in the same pool. A new code starts a new pool. Already joined? Enter the same name and code to pick up where you left off — even on a new device.</p>'+
        '<label class="bet-l">Display name<input id="bet-name" maxlength="24" autocomplete="off"></label>'+
        '<label class="bet-l">Pool code<input id="bet-code" maxlength="24" autocomplete="off" placeholder="friends26"></label>'+
        '<div class="bet-join-actions"><button id="bet-join-go" class="bet-btn" type="button">Join with $100</button>'+
        (canCancel?'<button id="bet-join-cancel" class="bet-btn ghost" type="button">Cancel</button>':'')+'</div>'+
        '<p class="bet-err" id="bet-join-err" hidden></p></div>';
      document.getElementById('bet-join-go').onclick=function(){
        var name=(document.getElementById('bet-name').value||'').trim();
        var code=(document.getElementById('bet-code').value||'').trim();
        if(!name||!code){showErr('bet-join-err','Enter a name and a code.');return;}
        api('join',{method:'POST',body:JSON.stringify({name:name,code:code})}).then(function(r){
          if(r.ok){joining=false;upsertPool({code:r.code,name:r.name,token:r.token});load();}
          else showErr('bet-join-err','Could not join.');
        }).catch(function(){showErr('bet-join-err',NETERR);});
      };
      var cc=document.getElementById('bet-join-cancel');
      if(cc)cc.onclick=function(){joining=false;render();};
    }
    function betsList(bh){
      var F=state.flags||{};
      return '<div class="bet-dbets">'+bh.map(function(b){
        var amt=b.status==='won'?'<span class="bet-db-amt won">'+money(b.stake)+' → won '+money(b.payout)+'</span>'
          :b.status==='lost'?'<span class="bet-db-amt lost">'+money(b.stake)+' → lost</span>'
          :'<span class="bet-db-amt">'+money(b.stake)+'</span>';
        return '<div class="bet-dbet'+(b.you?' you':'')+'"><span class="bet-db-l"><span class="bet-db-who">'+he(b.player)+(b.you?' (you)':'')+'</span> <span class="bet-db-pick">'+(F[b.pick]||'')+' '+he(b.pick)+'</span></span>'+amt+'</div>';
      }).join('')+'</div>';
    }
    // group by who they backed (winner's group first once decided), biggest stake first
    function sortBets(rows,m){
      var order=m.decided?[m.winner,(m.winner===m.team1?m.team2:m.team1)]:[m.team1,m.team2];
      var rank={}; order.forEach(function(t,i){rank[t]=i;});
      return rows.slice().sort(function(a,b){
        var ga=rank[a.pick]==null?9:rank[a.pick], gb=rank[b.pick]==null?9:rank[b.pick];
        return ga!==gb?ga-gb:b.stake-a.stake;
      });
    }
    function renderPool(){
      var me=state.me,F=state.flags||{};
      var openM=(state.matches||[]).filter(function(m){return m.open;});
      var games=openM.length?openM.map(function(m){
        var when=m.kickoff?' · <span class="ko" data-utc="'+m.kickoff+'" data-tfmt="daytime"><span class="ko-day"></span> <span class="ko-time"><span class="ko-tz tz"></span></span></span>':'';
        // your own bets always show; everyone else's show when the toggle is on
        var bh=(state.poolBets||[]).filter(function(b){return b.match_num===m.num;});
        var mine=bh.filter(function(b){return b.you;});
        var rows=showBets?mine.concat(bh.filter(function(b){return !b.you;})):mine;
        var block=rows.length?betsList(sortBets(rows,m)):'';
        var myPick=mine.length?mine[0].pick:null;   // can't bet both sides — lock the other one
        function pickBtn(team,odds){
          var dis=myPick&&myPick!==team;
          return '<button class="bet-pick'+(dis?' disabled':'')+'" type="button"'+(dis?' disabled':'')+' data-bet="'+m.num+'" data-team="'+he(team)+'"><span class="bet-fl">'+(F[team]||'')+'</span><span class="bet-nm">'+he(team)+'</span><span class="bet-od">'+odds.toFixed(2)+'</span></button>';
        }
        function detail(team){var u=(state.urls||{})[team];return u?'<a class="bet-detail" href="'+u+'">See team details</a>':'<span></span>';}
        return '<div class="bet-game"><div class="bet-g-rd">'+he(m.round)+when+'</div><div class="bet-g-row">'+
          pickBtn(m.team1,m.odds1)+pickBtn(m.team2,m.odds2)+'</div>'+
          '<div class="bet-g-links">'+detail(m.team1)+detail(m.team2)+'</div>'+block+'</div>';
      }).join(''):'<p class="muted">No matches are open for betting right now — check back when the next ties are set.</p>';
      // closed + in-play matches this round — dimmed, not selectable, everyone's bets
      var RORD={R32:0,R16:1,QF:2,SF:3,F:4};
      var curRound=openM.length?openM[0].round:(function(){
        var ko=(state.matches||[]).filter(function(m){return !m.open;});
        return ko.length?ko.reduce(function(a,b){return RORD[b.round]>=RORD[a.round]?b:a;}).round:null;})();
      function dside(team,odds,winner){
        var cls='bet-dteam'+(winner?(team===winner?' win':' lose'):'');
        var inner='<span class="bet-fl">'+(F[team]||'')+'</span><span class="bet-nm">'+he(team)+'</span><span class="bet-od">'+odds.toFixed(2)+'</span>';
        var u=(state.urls||{})[team];
        return u?'<a class="'+cls+'" href="'+u+'">'+inner+'</a>':'<div class="'+cls+'">'+inner+'</div>';
      }
      function matchBlock(m){
        var bh=(state.poolBets||[]).filter(function(b){return b.match_num===m.num;});
        var mine=bh.filter(function(b){return b.you;});
        var rows=showBets?mine.concat(bh.filter(function(b){return !b.you;})):mine;
        var bl=rows.length?betsList(sortBets(rows,m)):(showBets?'<div class="bet-dbets-none muted">No bets on this match.</div>':'');
        return '<div class="bet-game bet-decided"><div class="bet-g-rd">'+he(m.round)+(m.decided?' · '+he(m.winner)+' won':'')+'</div>'+
          '<div class="bet-g-row">'+dside(m.team1,m.odds1,m.winner)+dside(m.team2,m.odds2,m.winner)+'</div>'+bl+'</div>';
      }
      var closedM=(state.matches||[]).filter(function(m){return m.decided&&m.round===curRound;});
      var inPlayM=(state.matches||[]).filter(function(m){return !m.open&&!m.decided&&m.round===curRound;});
      var closedCard=closedM.length?'<div class="bet-card"><h2>Closed matches</h2>'+closedM.map(matchBlock).join('')+'</div>':'';
      var inPlayCard=inPlayM.length?'<div class="bet-card"><h2>In-play matches</h2>'+inPlayM.map(matchBlock).join('')+'</div>':'';
      var lb='<div class="bet-card"><h2>Leaderboard</h2><ol class="bet-lb">'+(state.leaderboard||[]).map(function(p,i){
        var rk=i+1, medal=rk<=3?(' medal r'+rk):'';
        return '<li class="'+(p.you?'you':'')+(p.out?' out':'')+'"><span class="bet-lb-r'+medal+'">'+rk+'</span><span class="bet-lb-n">'+he(p.name)+(p.you?' (you)':'')+'</span><span class="bet-lb-b">'+money(p.total)+'<i class="bet-lb-sub">cash '+money(p.cash)+' · in play '+money(p.portfolio)+'</i></span></li>';
      }).join('')+'</ol></div>';
      var toggle='<label class="bet-toggle"><input type="checkbox" id="bet-show"'+(showBets?' checked':'')+'><span>Show everyone’s bets</span></label>';
      var poolsBar='<div class="bet-pools">'+mem.pools.map(function(p){
        return '<button class="bet-pool'+(p.code===mem.active?' on':'')+'" type="button" data-pool="'+he(p.code)+'">'+he(p.code)+'</button>';
      }).join('')+'<button class="bet-pool add" type="button" id="bet-pool-add">+ Join</button></div>';
      var leaveCtl=leaveArmed
        ? '<span class="bet-leave-c">Leave “'+he(mem.active)+'”? <button id="bet-leave-yes" class="bet-mini danger" type="button">Leave</button><button id="bet-leave-no" class="bet-mini" type="button">Cancel</button></span>'
        : '<button id="bet-leave" class="bet-mini" type="button">Leave</button>';
      var balRow='<div class="bet-bal'+(me.out?' out':'')+'">'+
        '<div class="bet-bal-top"><b class="bet-bal-big">'+money(me.total)+'</b><i class="bet-bal-lbl">Portfolio</i></div>'+
        '<div class="bet-bal-break">Cash '+money(me.cash)+' · In play '+money(me.portfolio)+'</div>'+
        '<div class="bet-bal-k">'+he(me.name)+' · '+he(state.pool.name)+(me.out?' · out':'')+' · '+leaveCtl+'</div></div>';
      app.innerHTML=poolsBar+balRow+toggle+lb+closedCard+inPlayCard+'<div class="bet-card"><h2>Open matches</h2>'+games+'</div>';
      [].forEach.call(app.querySelectorAll('.bet-pick'),function(btn){btn.onclick=function(){
        var num=+btn.getAttribute('data-bet');
        var existing=(state.myBets||[]).filter(function(b){return b.match_num===num&&b.status==='open';})[0];
        if(existing)openEdit(existing.id); else openBet(num,btn.getAttribute('data-team'));
      };});
      [].forEach.call(app.querySelectorAll('.bet-pool[data-pool]'),function(b){b.onclick=function(){var c=b.getAttribute('data-pool');if(c!==mem.active){mem.active=c;saveMem();leaveArmed=false;load();}};});
      var addB=document.getElementById('bet-pool-add'); if(addB)addB.onclick=function(){joining=true;render();};
      var lv=document.getElementById('bet-leave'); if(lv)lv.onclick=function(){leaveArmed=true;render();};
      var ly=document.getElementById('bet-leave-yes'); if(ly)ly.onclick=function(){api('leave',{method:'POST'}).then(function(){dropPool(mem.active);leaveArmed=false;if(mem.active)load();else{state={configured:true,joined:false};render();}});};
      var ln=document.getElementById('bet-leave-no'); if(ln)ln.onclick=function(){leaveArmed=false;render();};
      var cb=document.getElementById('bet-show'); if(cb)cb.onchange=function(){setShowBets(cb.checked);};
      applyTZ();   // format the kickoff times in the viewer's chosen zone
    }
    var modal=document.getElementById('bet-modal'),form=document.getElementById('bet-form');
    if(modal&&modal.parentNode!==document.body)document.body.appendChild(modal);
    function closeBet(){if(modal)modal.hidden=true;}
    if(modal)modal.addEventListener('click',function(e){if(e.target.closest('[data-bet-close]'))closeBet();});
    document.addEventListener('keydown',function(e){if(e.key==='Escape'&&modal&&!modal.hidden)closeBet();});
    function openBet(num,team){
      var m=matchById(num); if(!m)return;
      var F=state.flags||{},odds=team===m.team1?m.odds1:m.odds2,bal=state.me.cash;
      document.getElementById('bet-modal-k').textContent='Bet on '+team;
      form.innerHTML='<div class="bet-form-team">'+(F[team]||'')+' <b>'+he(team)+'</b> @ '+odds.toFixed(2)+'</div>'+
        '<label class="bet-l">Stake (you have '+money(bal)+')<input id="bet-stake" type="number" min="0.01" step="0.01"></label>'+
        '<div class="bet-payout muted" id="bet-payout"></div>'+
        '<button class="bet-btn" id="bet-place" type="button">Place bet</button><p class="bet-err" id="bet-place-err" hidden></p>';
      var inp=document.getElementById('bet-stake'),po=document.getElementById('bet-payout');
      inp.oninput=function(){var s=parseFloat(inp.value)||0;po.textContent=s>0?('Returns '+money(s*odds)+' if '+team+' wins'):'';};
      document.getElementById('bet-place').onclick=function(){
        var s=parseFloat(inp.value)||0;
        if(s<=0){showErr('bet-place-err','Enter a stake.');return;}
        if(s>bal){showErr('bet-place-err','That is more than your balance.');return;}
        api('place',{method:'POST',body:JSON.stringify({match:num,pick:team,stake:s})}).then(function(r){
          if(r.ok){closeBet();load();}else showErr('bet-place-err',r.error==='closed'?'Betting on this match is closed.':r.error==='insufficient'?'Not enough balance.':r.error==='both_sides'?'You already backed the other side of this match.':'Could not place bet.');
        }).catch(function(){showErr('bet-place-err',NETERR);});
      };
      if(modal)modal.hidden=false;
    }
    function openEdit(id){
      var b=null; (state.myBets||[]).forEach(function(x){if(x.id===id)b=x;}); if(!b)return;
      var m=matchById(b.match_num); if(!m||!m.open)return;
      var F=state.flags||{},sel=b.pick,avail=state.me.cash+b.stake;
      function curOdds(team){return team===m.team1?m.odds1:m.odds2;}
      function teamBtn(team){return '<button class="bet-pick" type="button" data-eteam="'+he(team)+'"><span class="bet-fl">'+(F[team]||'')+'</span><span class="bet-nm">'+he(team)+'</span><span class="bet-od">'+curOdds(team).toFixed(2)+'</span></button>';}
      document.getElementById('bet-modal-k').textContent='Edit bet';
      form.innerHTML='<div class="bet-g-row" id="bet-edit-teams">'+teamBtn(m.team1)+teamBtn(m.team2)+'</div>'+
        '<label class="bet-l">Stake (you have '+money(avail)+')<input id="bet-stake" type="number" min="0.01" step="0.01" value="'+b.stake+'"></label>'+
        '<div class="bet-payout muted" id="bet-payout"></div>'+
        '<div class="bet-edit-actions"><button class="bet-btn" id="bet-save" type="button">Save changes</button>'+
        '<button class="bet-btn ghost" id="bet-remove" type="button">Remove bet</button></div>'+
        '<p class="bet-err" id="bet-place-err" hidden></p>';
      var inp=document.getElementById('bet-stake'),po=document.getElementById('bet-payout');
      function refresh(){
        [].forEach.call(form.querySelectorAll('#bet-edit-teams .bet-pick'),function(btn){btn.classList.toggle('on',btn.getAttribute('data-eteam')===sel);});
        var s=parseFloat(inp.value)||0; po.textContent=s>0?('Returns '+money(s*curOdds(sel))+' if '+sel+' wins'):'';
      }
      inp.oninput=refresh;
      [].forEach.call(form.querySelectorAll('#bet-edit-teams .bet-pick'),function(btn){btn.onclick=function(){sel=btn.getAttribute('data-eteam');refresh();};});
      refresh();
      document.getElementById('bet-save').onclick=function(){
        var s=parseFloat(inp.value)||0;
        if(s<=0){showErr('bet-place-err','Enter a stake.');return;}
        if(s>avail){showErr('bet-place-err','That is more than you have.');return;}
        api('update',{method:'POST',body:JSON.stringify({id:id,pick:sel,stake:s})}).then(function(r){
          if(r.ok){closeBet();load();}else showErr('bet-place-err',r.error==='both_sides'?'You already backed the other side here.':r.error==='closed'?'This match has kicked off.':r.error==='insufficient'?'More than you have.':'Could not update.');
        }).catch(function(){showErr('bet-place-err',NETERR);});
      };
      document.getElementById('bet-remove').onclick=function(){
        api('cancel',{method:'POST',body:JSON.stringify({id:id})}).then(function(r){
          if(r.ok){closeBet();load();}else showErr('bet-place-err',r.error==='closed'?'This match has kicked off.':'Could not remove.');
        }).catch(function(){showErr('bet-place-err',NETERR);});
      };
      if(modal)modal.hidden=false;
    }
    window.__betRender=function(s){state=s;render();};   // test seam
    window.__betReload=function(){mem={active:null,pools:[]};try{var v=JSON.parse(localStorage.getItem('wc26.bets'));if(v&&v.pools)mem=v;}catch(e){}joining=false;leaveArmed=false;load();};
    load();
  }

  // Calendar: jump to today on load (offset for the sticky header).
  function landOnToday(){
    var t=document.querySelector('.cal-day.today'); if(!t)return;
    var head=document.querySelector('.site-head');
    var off=(head?head.getBoundingClientRect().height:0)+12;
    var y=t.getBoundingClientRect().top+window.pageYOffset-off;
    window.scrollTo(0,Math.max(0,y));
  }

  document.addEventListener('DOMContentLoaded',function(){
    wireTZ();apply();wireReveal();wireLive();wireBracketScroll();wireBracketObserver();drawBracket();
    landOnActiveColumn();initFantasy();initBetting();landOnToday();
  });
  window.addEventListener('load',landOnToday);
  window.addEventListener('load',drawBracket);
  window.addEventListener('resize',scheduleDraw);
})();
