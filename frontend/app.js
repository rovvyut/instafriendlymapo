/* MAPO — front end.  Loaded by index.html after data/dishes.json.
   Nothing here talks to a server: the plan generator, the coach and the log
   all run in the browser. See DEPLOY.md to wire it to the FastAPI backend. */
/* ══════════════════════════════════════════════════════════════════════
   MAPO — front end. Everything below runs in the page; no server needed.
   ══════════════════════════════════════════════════════════════════════ */

/* ---------- food pool ---------- */
const POOL = (window.__MAPO_DISHES__||{}).dishes||[];
const PLAN = POOL.filter(d=>d.t==='d');          // dishes only, for generated meals
const TYPE_LABEL = {d:'Dish', c:'Condiment', k:'Drink'};
const SLOTS = ['early morning','breakfast','lunch','high tea','dinner'];
const SLOT_LABEL = {'early morning':'Early morning','breakfast':'Breakfast','lunch':'Lunch',
  'high tea':'High tea','dinner':'Dinner'};
const MEAL_SPLIT = {'early morning':.01,'breakfast':.25,'lunch':.35,'high tea':.09,'dinner':.30};
const DISH_COUNT = {'breakfast':2,'lunch':3,'high tea':1,'dinner':2};
const ACTIVITY = {1:1.2,2:1.375,3:1.55,4:1.725,5:1.9};
const PROT_M = {1:1.2,2:2.0,3:2.0,4:2.2};
const FAT_M  = {1:0.9,2:1.0,3:0.8,4:0.9};
const CARB_M = {1:2.0,2:2.5,3:3.0,4:4.0,5:5.0};
const MIN_MULT=0.5, MAX_MULT=2.0;
const TRAINING_SHIFT=0.12, CARB_FLOOR=0.55;
const WEEKDAYS=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];

const titleCase = s => s.replace(/\w\S*/g, t => t[0].toUpperCase()+t.slice(1).toLowerCase());

/* featured plates — eight real rows, shown on the pinned reel */
const FEATURED=[
 {n:'Kidney bean curry',u:'bowl',g:119.9,e:172,p:7.1,c:19.6,f:6.9,v:'veg',r:'North Indian',s:'00101'},
 {n:'Chapati / Roti',u:'chapati',g:36,e:73,p:2.1,c:12.8,f:1.3,v:'veg',r:'Pan-Indian',s:'01111'},
 {n:'Butter chicken',u:'large piece',g:275.2,e:377,p:30.1,c:10.3,f:23.9,v:'non-veg',r:'North Indian',s:'00101'},
 {n:'Idli',u:'idli',g:25.1,e:34,p:1.2,c:7.1,f:0.1,v:'veg',r:'South Indian',s:'01010'},
 {n:'Sambar',u:'bowl',g:250,e:242,p:8.4,c:26.4,f:10.9,v:'veg',r:'South Indian',s:'01101'},
 {n:'Masala dosa',u:'dosa',g:209.7,e:345,p:6.9,c:41,f:16.4,v:'veg',r:'South Indian',s:'01010'},
 {n:'Curd rice',u:'plate',g:216.2,e:423,p:12.4,c:71.2,f:9.3,v:'veg',r:'South Indian',s:'00101'},
 {n:'Hot tea · garam chai',u:'tea cup',g:200,e:32,p:0.8,c:5.2,f:1.1,v:'veg',r:'Pan-Indian',s:'01010'},
];

/* ---------- app state ---------- */
const S = {
  user:null,          // {name, how} — held in this tab only
  profile:null,       // {name, target, bmi, bmr, tdee, macros, pref, fav}
  log:[],             // [{name, kcal, p, c, f, note}]
  training:new Set([0,2,4]),
  week:null,
  deal:null,          // last dealt combo
};
const $=id=>document.getElementById(id);

/* ══════════ GRAIN ══════════ */
(function(){
  const n=document.createElement('canvas');n.width=n.height=180;
  const g=n.getContext('2d'),d=g.createImageData(180,180);
  for(let i=0;i<d.data.length;i+=4){const v=Math.random()*255;
    d.data[i]=d.data[i+1]=d.data[i+2]=v;d.data[i+3]=26;}
  g.putImageData(d,0,0);
  document.getElementById('grain').style.backgroundImage='url('+n.toDataURL()+')';
})();

/* ══════════ PRELOADER → GATE ══════════ */
function startReel(){
  document.getElementById('gate').classList.remove('on');
  document.getElementById('gate').classList.add('out');
  document.body.style.overflow=document.documentElement.style.overflow='';
  document.body.classList.add('lift');
  setTimeout(()=>{
    document.getElementById('s1').classList.add('go');
    window.scrollTo(0,0);
    document.getElementById('trayBtn').classList.add('up');
    document.getElementById('coachBtn').classList.add('up');
  },420);
}
(function(){
  let p=0;const pct=document.getElementById('pct'),bar=document.getElementById('preBar');
  document.body.style.overflow=document.documentElement.style.overflow='hidden';
  const tick=setInterval(()=>{
    p+=Math.random()*11;
    if(p>=100){p=100;clearInterval(tick);
      setTimeout(()=>{
        const pre=document.getElementById('pre');
        pre.classList.add('done');pre.style.transition='opacity .4s';pre.style.opacity=0;
        document.body.classList.add('lift');          // split the curtains onto the gate
        document.getElementById('gate').classList.add('on');
      },380);}
    pct.textContent=Math.floor(p);bar.style.width=p+'%';
  },110);
})();

/* ══════════ LOGIN GATE ══════════
   Front-end only. No credentials leave this page and nothing is stored on a
   server — the "account" is a name held in memory for this tab. If you later
   deploy MAPO, set GOOGLE_CLIENT_ID below and the real Google Identity
   Services button replaces the demo one automatically. */
const GOOGLE_CLIENT_ID = '';   // ← paste your OAuth client ID when you deploy

/* Every feature sits behind the account. Nothing here is a paywall — it keeps
   the plan generator, the coach and the log from running for a visitor who
   never signed in, which is what actually costs you on a deployed backend. */
function requireAuth(what){
  if(S.user)return true;
  const gate=$('gate');
  $('gKicker').textContent='Account required';
  $('gHead').textContent='Sign in first.';
  $('gSub').innerHTML=`You need an account to ${what}. It takes one click with Google, or an email and a password.`;
  gate.classList.remove('out'); gate.classList.add('on');
  document.body.style.overflow=document.documentElement.style.overflow='hidden';
  window.scrollTo(0,0);
  return false;
}

function signIn(name,how){
  S.user={name,how};
  const w=document.getElementById('whoami');
  document.getElementById('whoName').textContent=name+(how?' · '+how:'');
  w.style.display='flex';
  const fn=document.getElementById('fName');
  if(fn&&!fn.value)fn.value=name.split(/[ @]/)[0];
  startReel();
}
(function(){
  const gate=$('gate'), err=$('gErr');
  const bad=m=>{err.textContent=m;};

  $('gIn').addEventListener('click',()=>{
    const e=$('gEmail').value.trim(), p=$('gPass').value;
    if(!/^\S+@\S+\.\S+$/.test(e))return bad('that email doesn’t look right');
    if(p.length<6)return bad('password needs at least 6 characters');
    signIn(e.split('@')[0],'signed in');
  });
  $('gUp').addEventListener('click',()=>{
    const e=$('gEmail').value.trim(), p=$('gPass').value;
    if(!/^\S+@\S+\.\S+$/.test(e))return bad('add an email to create an account');
    if(p.length<6)return bad('pick a password of 6 characters or more');
    signIn(e.split('@')[0],'new here');
  });
  $('gPass').addEventListener('keydown',e=>{if(e.key==='Enter')$('gIn').click();});

  // Google: real GIS when configured and reachable, an obvious demo otherwise.
  $('gGoogle').addEventListener('click',()=>{
    if(window.google&&google.accounts&&GOOGLE_CLIENT_ID){
      google.accounts.id.prompt();
      return;
    }
    err.textContent='';
    signIn('Guest','google demo');
  });
  if(GOOGLE_CLIENT_ID){
    const s=document.createElement('script');
    s.src='https://accounts.google.com/gsi/client';s.async=true;s.defer=true;
    s.onload=()=>{
      try{
        google.accounts.id.initialize({client_id:GOOGLE_CLIENT_ID,callback:r=>{
          // decode only the display name from the ID token; verification is a
          // server's job — send r.credential to POST /api/auth/google for that.
          try{
            const c=JSON.parse(atob(r.credential.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));
            signIn(c.given_name||c.name||c.email,'google');
          }catch(_){signIn('Google user','google');}
        }});
        $('gGoogle').style.display='none';
        google.accounts.id.renderButton($('gsiSlot'),
          {theme:'filled_black',size:'large',width:380,text:'continue_with'});
      }catch(_){}
    };
    document.head.appendChild(s);
  }

  $('signOut').addEventListener('click',()=>{
    S.user=null;
    $('gKicker').textContent='Welcome back';
    $('gHead').textContent='Let\u2019s get you fed.';
    $('gSub').textContent='Sign in and your plate, your week and today\u2019s tally all stay with you.';
    document.getElementById('whoami').style.display='none';
    gate.classList.remove('out');gate.classList.add('on');
    document.body.style.overflow=document.documentElement.style.overflow='hidden';
    window.scrollTo(0,0);
  });

  // quiet particle field behind the brand side
  const c=$('gateCanvas'),x=c.getContext('2d');
  let W,H,t=0;
  const fit=()=>{W=c.width=c.offsetWidth;H=c.height=c.offsetHeight;};
  fit();addEventListener('resize',fit);
  const dots=Array.from({length:70},()=>({x:Math.random(),y:Math.random(),
    r:Math.random()*1.6+.4,s:Math.random()*.00035+.00008,o:Math.random()*.5+.15}));
  (function loop(){
    if(W&&H){
      x.clearRect(0,0,W,H);
      x.beginPath();
      const rr=Math.min(W,H)*.42+Math.sin(t*.01)*10;
      x.ellipse(W*.5,H*.5,rr,rr*.5,Math.sin(t*.004)*.4,0,7);
      x.strokeStyle='rgba(216,255,54,.07)';x.lineWidth=1;x.stroke();
      dots.forEach(d=>{
        d.y-=d.s; if(d.y<-.05)d.y=1.05;
        x.beginPath();x.arc(d.x*W,d.y*H,d.r,0,7);
        x.fillStyle='rgba(216,255,54,'+d.o*.6+')';x.fill();
      });
      t++;
    }
    requestAnimationFrame(loop);
  })();
})();

/* ══════════ CURSOR ══════════ */
(function(){
  const dot=document.getElementById('cDot'),ring=document.getElementById('cRing');
  let mx=innerWidth/2,my=innerHeight/2,rx=mx,ry=my;
  addEventListener('mousemove',e=>{mx=e.clientX;my=e.clientY;
    dot.style.transform=`translate(${mx}px,${my}px)`;});
  (function loop(){rx+=(mx-rx)*.16;ry+=(my-ry)*.16;
    ring.style.transform=`translate(${rx}px,${ry}px)`;requestAnimationFrame(loop);})();
  document.addEventListener('mouseover',e=>{
    const ui=e.target.closest('.ui');
    ring.classList.toggle('off',!!ui);dot.classList.toggle('off',!!ui);
    const el=e.target.closest('[data-cursor],.plate,.layer,a');
    if(el&&!ui){ring.classList.add('big');ring.dataset.l=el.dataset.cursor||'VIEW';}
    else ring.classList.remove('big');
  });
})();

/* ══════════ HERO CANVAS ══════════ */
(function(){
  const c=document.getElementById('orb'),x=c.getContext('2d');
  let W,H,t=0,mx=0,my=0;
  function size(){W=c.width=innerWidth;H=c.height=innerHeight;}
  size();addEventListener('resize',size);
  addEventListener('mousemove',e=>{mx=(e.clientX/innerWidth-.5);my=(e.clientY/innerHeight-.5);});
  const pts=[];
  for(let i=0;i<190;i++){
    const a=Math.random()*Math.PI*2, r=180+Math.random()*260;
    pts.push({a,r,s:.0009+Math.random()*.0026,o:Math.random()*.7+.25,z:Math.random()});
  }
  function draw(){
    x.clearRect(0,0,W,H);
    const cx=W*.5+mx*70, cy=H*.5+my*50;
    for(let k=0;k<3;k++){
      x.beginPath();
      const rr=250+k*95+Math.sin(t*.012+k)*16;
      x.ellipse(cx,cy,rr,rr*.34,Math.sin(t*.004+k*.7)*.5,0,7);
      x.strokeStyle='rgba(216,255,54,'+(.09-k*.022)+')';x.lineWidth=1;x.stroke();
    }
    pts.forEach(p=>{
      p.a+=p.s;
      const px=cx+Math.cos(p.a)*p.r*(1+mx*.12);
      const py=cy+Math.sin(p.a)*p.r*.36*(1+my*.2);
      x.beginPath();x.arc(px,py,.6+p.z*1.9,0,7);
      x.fillStyle=p.z>.82?'rgba(255,91,31,'+p.o+')':'rgba(216,255,54,'+(p.o*.55)+')';
      x.fill();
    });
    t++;requestAnimationFrame(draw);
  }
  draw();
})();

/* ══════════ DRAWER ══════════ */
const drawer=document.getElementById('drawer'), scrim=document.getElementById('scrim');
const dwTitle=document.getElementById('dwTitle'), dwKicker=document.getElementById('dwKicker');
const dwBody=document.getElementById('dwBody'), dwFoot=document.getElementById('dwFoot');
function openDrawer(kicker,title,bodyHTML,footHTML){
  dwKicker.textContent=kicker; dwTitle.textContent=title;
  dwBody.innerHTML=bodyHTML; dwFoot.innerHTML=footHTML||'';
  dwBody.scrollTop=0;
  drawer.classList.add('on'); scrim.classList.add('on');
  drawer.setAttribute('aria-hidden','false');
}
function closeDrawer(){
  drawer.classList.remove('on');
  drawer.setAttribute('aria-hidden','true');
  // the coach shares this scrim — only clear it if nothing else is using it
  const coach=document.getElementById('coach');
  if(!coach||!coach.classList.contains('on'))scrim.classList.remove('on');
}
document.getElementById('dwClose').addEventListener('click',closeDrawer);
scrim.addEventListener('click',()=>{if(drawer.classList.contains('on'))closeDrawer();});
// Escape closes the topmost panel only, so dismissing a food card does not also
// shut the coach you opened it from.
addEventListener('keydown',e=>{
  if(e.key!=='Escape')return;
  if(drawer.classList.contains('on')){closeDrawer();return;}
  const coach=document.getElementById('coach');
  if(coach&&coach.classList.contains('on'))coach.dispatchEvent(new CustomEvent('coach:close'));
});

/* ══════════ TODAY LOG ══════════ */
const trayBtn=document.getElementById('trayBtn');
const trayKc=document.getElementById('trayKc'), trayNote=document.getElementById('trayNote');
const trayRing=document.getElementById('trayRing'), trayPop=document.getElementById('trayPop');
const RING_LEN=2*Math.PI*16;
trayRing.setAttribute('stroke-dasharray',RING_LEN.toFixed(1));

function logTotals(){
  return S.log.reduce((a,l)=>({kcal:a.kcal+l.kcal,p:a.p+l.p,c:a.c+l.c,f:a.f+l.f}),
                      {kcal:0,p:0,c:0,f:0});
}
function paintTray(delta){
  const t=logTotals();
  trayKc.textContent=Math.round(t.kcal).toLocaleString()+' kcal';
  if(S.profile){
    const pct=Math.min(t.kcal/S.profile.target,1);
    trayRing.style.strokeDashoffset=(RING_LEN*(1-pct)).toFixed(1);
    const left=Math.round(S.profile.target-t.kcal);
    trayNote.textContent = left>0 ? left.toLocaleString()+' kcal left today'
                                  : Math.abs(left).toLocaleString()+' kcal over — it happens';
  }else{
    trayRing.style.strokeDashoffset=(RING_LEN*(1-Math.min(t.kcal/2000,1))).toFixed(1);
    trayNote.textContent=S.log.length?S.log.length+' item'+(S.log.length>1?'s':'')+' · tap to open'
                                     :'today · tap to open';
  }
  if(delta){
    trayPop.textContent='+'+Math.round(delta);
    trayPop.classList.add('show');
    clearTimeout(paintTray._t);
    paintTray._t=setTimeout(()=>trayPop.classList.remove('show'),1400);
  }
}
function addLog(name,kcal,p,c,f,note){
  if(!requireAuth('log food'))return;
  S.log.push({name,kcal:+kcal,p:+p||0,c:+c||0,f:+f||0,note:note||''});
  paintTray(kcal);
  if(drawer.classList.contains('on')&&dwKicker.textContent==='TODAY') showLog();
}
function showLog(){
  if(!requireAuth('keep a daily log'))return;
  const t=logTotals();
  const head = `<div class="bigkc">${Math.round(t.kcal).toLocaleString()}<i>KCAL</i></div>
    <div class="mrow">
      <div class="p"><span>PROTEIN</span><b>${t.p.toFixed(1)}g</b></div>
      <div class="c"><span>CARBS</span><b>${t.c.toFixed(1)}g</b></div>
      <div class="f"><span>FAT</span><b>${t.f.toFixed(1)}g</b></div>
    </div>` + (S.profile
      ? `<div class="meta">TARGET · <b>${S.profile.target.toLocaleString()} KCAL</b><br>
           ${t.kcal<=S.profile.target
             ? 'REMAINING · <b>'+Math.round(S.profile.target-t.kcal).toLocaleString()+' KCAL</b>'
             : 'OVER BY · <b>'+Math.round(t.kcal-S.profile.target).toLocaleString()+' KCAL</b>'}</div>`
      : `<div class="meta">RUN YOUR NUMBERS TO SEE A TARGET</div>`);
  const rows = S.log.length
    ? S.log.map((l,i)=>`<div class="logrow">
        <div class="n">${l.name}<small>${l.note||''}</small></div>
        <div class="k">${Math.round(l.kcal)}</div>
        <button class="rm" data-rm="${i}">REMOVE</button></div>`).join('')
    : `<div class="empty">Nothing logged yet. Tap any plate in the index, or build the week
        and log a whole day at once. No streak is being judged here.</div>`;
  openDrawer('TODAY','What you’ve eaten',
    head+`<div style="margin-top:28px">${rows}</div>`,
    S.log.length?`<button class="btn ghost" id="clearLog">Clear the day</button>`:'');
  dwBody.querySelectorAll('[data-rm]').forEach(b=>b.addEventListener('click',()=>{
    S.log.splice(+b.dataset.rm,1);paintTray();showLog();}));
  const cl=document.getElementById('clearLog');
  if(cl)cl.addEventListener('click',()=>{S.log=[];paintTray();showLog();});
}
trayBtn.addEventListener('click',showLog);
paintTray();

/* ══════════ FOOD CARD ══════════ */
function slotsOf(d){return SLOTS.filter((s,i)=>d.s[i]==='1');}
function showFood(d){
  if(!requireAuth('open a dish and log it'))return;
  let mult=1;
  const render=()=>{
    const k=d.e*mult,p=d.p*mult,c=d.c*mult,f=d.f*mult;
    return `<div class="bigkc">${Math.round(k)}<i>KCAL</i></div>
      <div class="mrow">
        <div class="p"><span>PROTEIN</span><b>${p.toFixed(1)}g</b></div>
        <div class="c"><span>CARBS</span><b>${c.toFixed(1)}g</b></div>
        <div class="f"><span>FAT</span><b>${f.toFixed(1)}g</b></div>
      </div>
      <div class="meta">
        SERVING · <b>${mult}× ${d.u} (${Math.round(d.g*mult)} g)</b><br>
        ${d.a?'ALSO CALLED · <b>'+titleCase(d.a.split('|').join(' · '))+'</b><br>':''}REGION · <b>${d.r}</b><br>
        TYPE · <b>${TYPE_LABEL[d.t]||'Dish'} · ${d.v==='veg'?'Vegetarian':d.v==='egg'?'Eggetarian':'Non-vegetarian'}</b><br>
        EATEN AT · <b>${slotsOf(d).map(s=>SLOT_LABEL[s]).join(' · ')||'Any time'}</b>
      </div>
      <div class="stepper">
        <span>HOW MUCH</span>
        <button data-step="-1">−</button><b id="multLbl">${mult}×</b><button data-step="1">+</button>
      </div>`;
  };
  const paint=()=>{
    dwBody.innerHTML=render();
    dwBody.querySelectorAll('[data-step]').forEach(b=>b.addEventListener('click',()=>{
      mult=Math.round(Math.min(3,Math.max(.5,mult+ (+b.dataset.step)*.5))*10)/10;
      paint();
    }));
  };
  openDrawer('FOOD',titleCase(d.n),'',
    `<button class="btn solid" id="logIt">Log it</button>`);
  paint();
  document.getElementById('logIt').addEventListener('click',()=>{
    addLog(titleCase(d.n),d.e*mult,d.p*mult,d.c*mult,d.f*mult,`${mult}× ${d.u}`);
    closeDrawer();
  });
}

/* ══════════ FOOD SEARCH ══════════ */
function showSearch(){
  if(!requireAuth('browse the menu'))return;
  openDrawer('BROWSE',`All ${POOL.length} dishes`,
    `<label class="field"><span>Search</span>
       <input id="sq" type="text" placeholder="dal, paneer, dosa, chai…" autocomplete="off"></label>
     <div id="sres" style="margin-top:22px"></div>`,'');
  const q=document.getElementById('sq'), res=document.getElementById('sres');
  const draw=()=>{
    const term=q.value.trim().toLowerCase();
    const hits=(term?POOL.filter(d=>hay(d).includes(term)):POOL).slice(0,60);
    res.innerHTML = hits.length ? hits.map((d,i)=>`
      <div class="logrow" data-pick="${POOL.indexOf(d)}" style="cursor:pointer">
        <div class="n">${titleCase(d.n)}<small>${d.a?titleCase(d.a.split('|')[0])+' · ':''}${d.u} · ${Math.round(d.g)} g · ${d.r}</small></div>
        <div class="k">${Math.round(d.e)}</div>
      </div>`).join('')
      : `<div class="empty">Nothing matches “${q.value}”. Try a shorter word — “paneer”, “dal”, “rice”.</div>`;
    res.querySelectorAll('[data-pick]').forEach(r=>r.addEventListener('click',
      ()=>showFood(POOL[+r.dataset.pick])));
  };
  q.addEventListener('input',draw); draw(); q.focus();
}

/* ══════════ PLATE INDEX ══════════ */
(function(){
  const tr=document.getElementById('track');
  tr.innerHTML=FEATURED.map((d,i)=>`
    <div class="plate" data-cursor="TAP" data-feat="${i}">
      <div class="idx"><span>${String(i+1).padStart(2,'0')} / 08</span><b>1 SERVING</b></div>
      <div class="art"><canvas data-seed="${i}"></canvas>
        <div class="kc">${Math.round(d.e)}<i>KCAL</i></div>
        <div class="tap">TAP TO OPEN</div></div>
      <h3>${d.n.toUpperCase()}</h3>
      <div class="macro">P ${d.p} · C ${d.c} · F ${d.f}</div>
      <div class="serv">${d.u.toUpperCase()} · ${d.g} G · ${d.r.toUpperCase()}</div>
    </div>`).join('') + `
    <div class="searchcard ui">
      <div class="idx">ALL ${POOL.length} DISHES</div>
      <div class="box">
        <h3>THE WHOLE<br>MENU.</h3>
        <p>Every dish we know, with the numbers already done. Search it, pick a portion,
           log it and get on with your day.</p>
        <button class="btn solid" id="browseBtn">Browse all dishes</button>
      </div>
    </div>`;

  tr.querySelectorAll('[data-feat]').forEach(el=>el.addEventListener('click',
    ()=>showFood(FEATURED[+el.dataset.feat])));
  document.getElementById('browseBtn').addEventListener('click',showSearch);

  document.querySelectorAll('.art canvas').forEach(cv=>{
    const g=cv.getContext('2d');const seed=+cv.dataset.seed;
    function fit(){cv.width=cv.offsetWidth;cv.height=cv.offsetHeight;}
    fit();addEventListener('resize',fit);
    let f=seed*40;
    (function loop(){
      const W=cv.width,H=cv.height;g.clearRect(0,0,W,H);
      for(let i=0;i<22;i++){
        const p=i/22, y=H*p+Math.sin(f*.011+i*.5+seed)*22;
        g.beginPath();
        for(let sx=0;sx<=W;sx+=10){
          const yy=y+Math.sin(sx*.021+f*.017+i*.35+seed)*13;
          sx?g.lineTo(sx,yy):g.moveTo(sx,yy);
        }
        g.strokeStyle=i%4===0?'rgba(255,91,31,.5)':'rgba(216,255,54,.20)';
        g.lineWidth=i%4===0?1.3:.8;g.stroke();
      }
      f++;requestAnimationFrame(loop);
    })();
  });
})();

/* ══════════ RIBBONS ══════════ */
(function(){
  document.getElementById('rib1').innerHTML='<span>'+'ROMANTICIZE YOUR MACROS ✳ '.repeat(9)+'</span>';
  document.getElementById('rib2').innerHTML='<span>'+'NO STARVATION VIBES ALLOWED ✳ '.repeat(9)+'</span>';
})();

/* ══════════ TEXT SCRAMBLE ══════════ */
const CH='ABCDEFGHIJKLMNOPQRSTUVWXYZ#%&*+/\\<>';
function scramble(el){
  const final=el.dataset.final;let frame=0;
  const q=[...final].map((ch,i)=>({ch,start:Math.floor(i*1.6),end:Math.floor(i*1.6)+14}));
  (function run(){
    let out='',done=0;
    q.forEach(o=>{
      if(frame>=o.end){done++;out+=o.ch;}
      else if(frame>=o.start){out+=o.ch===' '||o.ch==='\n'?o.ch:CH[Math.floor(Math.random()*CH.length)];}
    });
    el.textContent=out;frame++;
    if(done<q.length)requestAnimationFrame(run);
  })();
}
const io=new IntersectionObserver(es=>es.forEach(e=>{
  if(!e.isIntersecting)return;
  e.target.classList.add('in');
  if(e.target.dataset.final&&!e.target.dataset.done){e.target.dataset.done=1;scramble(e.target);}
  io.unobserve(e.target);
}),{threshold:.25});
document.querySelectorAll('.rv').forEach(el=>io.observe(el));

/* ══════════ EQUATION ══════════ */
(function(){
  const eq=document.getElementById('eq');
  const hot=['LESS','RIGHT'];
  eq.innerHTML=eq.textContent.trim().split(/\s+/).map(w=>
    `<span class="w${hot.includes(w.replace(/[^A-Z]/g,''))?' acid':''}">${w}&nbsp;</span>`).join('');
})();

/* ══════════ YOUR NUMBERS ══════════ */
function bmiInsight(b){
  if(b<18.5)return 'You’re under the healthy range — this plan leans towards eating more, not less.';
  if(b<25)  return 'You’re in the healthy range. Nothing dramatic needed, just consistency.';
  if(b<30)  return 'You’re in the overweight range. The target below is a gentle deficit, not a punishment.';
  if(b<35)  return 'Obesity class I. Slow and steady wins here — no crash anything.';
  if(b<40)  return 'Obesity class II. Worth doing this alongside a doctor who knows you.';
  return 'Obesity class III. Please loop in a doctor — this page is a tool, not a clinician.';
}
function goalLine(goal){
  return {1:'This holds you exactly where you are.',
          2:'A small surplus — gaining on purpose, slowly.',
          3:'A gentle 20% deficit. Sustainable, not miserable.',
          4:'Recomp: losing fat and holding muscle at the same time.'}[goal];
}
/* ---- favourite food: autocomplete + live match ---- */
/* Dishes carry their local names too (rajma, roti, chai, poha…), so searching
   for what you'd actually call it finds the row. */
const hay = d => ((d.n||'')+' '+(d.a||'')).toLowerCase();
function matchFav(term){
  const q=(term||'').trim().toLowerCase();
  if(q.length<2)return null;
  return POOL.find(d=>d.n.toLowerCase()===q)
      || POOL.find(d=>(d.a||'').toLowerCase().split('|').includes(q))
      || POOL.find(d=>hay(d).startsWith(q))
      || POOL.find(d=>new RegExp('\\b'+q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).test(hay(d)))
      || POOL.find(d=>hay(d).includes(q))
      || null;
}
const favLabel = d => titleCase(d.n) + (d.a ? ' · '+titleCase(d.a.split('|')[0]) : '');
(function(){
  const dl=$('favlist');
  const seen=new Set();
  dl.innerHTML=POOL.map(d=>{
    const v=favLabel(d).replace(/"/g,'');
    if(seen.has(v))return ''; seen.add(v);
    return `<option value="${v}">`;
  }).join('');
  const inp=$('fFav'), hint=$('favHint');
  inp.addEventListener('input',()=>{
    const m=matchFav(inp.value.split(' · ')[0]) || matchFav(inp.value);
    hint.innerHTML = !inp.value.trim() ? ''
      : m ? `<span style="color:var(--acid)">✓ ${favLabel(m)} · ${Math.round(m.e)} kcal per ${m.u}</span>`
          : `no exact match — we'll still keep the craving in mind`;
  });
})();

function computeProfile(){
  const w=+$('fWeight').value, h=+$('fHeight').value, age=+$('fAge').value;
  const gender=$('fGender').value, act=+$('fAct').value, goal=+$('fGoal').value;
  const tw=+$('fTarget').value || w, pref=$('fPref').value;
  const name=($('fName').value||'').trim();
  if(!(w>0&&h>0&&age>0))return null;

  const bmi=+(w/Math.pow(h/100,2)).toFixed(2);
  const bmr=+(gender==='Male' ? (10*w)+(6.25*h)-(5*age)+5 : (10*w)+(6.25*h)-(5*age)-161).toFixed(2);
  const tdee=+(bmr*ACTIVITY[act]).toFixed(2);
  let target;
  if(goal===1)target=Math.round(tdee);
  else if(goal===2)target=Math.round(tdee*1.10);
  else if(goal===3)target=Math.round(tdee*0.80);
  else{const m=bmi<25?1:bmi<30?.95:bmi<35?.90:.85;target=Math.round(tdee*m);}

  const macroW = bmi>=25 ? tw : w;
  const macros={protein:+(macroW*PROT_M[goal]).toFixed(1),
                fat:+(macroW*FAT_M[goal]).toFixed(1),
                carbs:+(macroW*CARB_M[act]).toFixed(1)};
  const favText=($('fFav').value||'').trim();
  const fav=matchFav(favText.split(' · ')[0])||matchFav(favText);
  return {name,bmi,bmr,tdee,target,macros,pref,goal,act,favText,fav};
}
function paintProfile(){
  const p=S.profile; if(!p)return;
  $('readout').classList.add('done');
  $('roTarget').textContent=p.target.toLocaleString();
  $('roGoal').textContent=goalLine(p.goal);
  $('roBmi').textContent=p.bmi;
  $('roBmr').textContent=Math.round(p.bmr).toLocaleString();
  $('roTdee').textContent=Math.round(p.tdee).toLocaleString();
  $('roP').textContent=p.macros.protein;
  $('roC').textContent=p.macros.carbs;
  $('roF').textContent=p.macros.fat;
  $('roBmiNote').innerHTML='<b>'+bmiInsight(p.bmi)+'</b>';

  const fv=$('roFav');
  if(p.fav){
    const share=Math.round(p.fav.e/p.target*100);
    fv.style.display='block';
    fv.innerHTML=`MAKING ROOM FOR · <b>${favLabel(p.fav)}</b><br>
      <b>${Math.round(p.fav.e)} KCAL</b> PER ${p.fav.u.toUpperCase()} ·
      <b>${share}%</b> OF YOUR DAY · P ${p.fav.p} · C ${p.fav.c} · F ${p.fav.f}<br>
      ${share<=35 ? 'FITS EASILY — IT’S IN THE WEEK BELOW.'
                  : share<=55 ? 'BIG BUT DOABLE — WE’LL BUILD A LIGHTER DAY AROUND IT.'
                              : 'THAT’S HALF YOUR DAY. IT’S IN THERE ANYWAY — HALF PORTIONS EXIST.'}`;
  }else if(p.favText){
    fv.style.display='block';
    fv.innerHTML=`FAVOURITE · <b>${p.favText}</b><br>
      NOT IN THE MENU YET — THE WEEK STILL LEAVES ROOM FOR IT.`;
  }else fv.style.display='none';
  $('weekNote').textContent = (p.name? p.name+', your ':'Your ')
    +'week is built on '+p.target.toLocaleString()+' kcal a day. Pick your training days, then generate.';
  paintTray();
}
$('calcBtn').addEventListener('click',()=>{
  if(!requireAuth('run your numbers'))return;
  const p=computeProfile();
  if(!p){$('weekNote').textContent='Check the numbers — weight, height and age all need a value.';return;}
  S.profile=p;paintProfile();
});
$('resetBtn').addEventListener('click',()=>{
  S.profile=null;$('readout').classList.remove('done');
  $('weekNote').textContent='Run your numbers up top first — the week is built on your target, not a template.';
  paintTray();
});
$('toWeekBtn').addEventListener('click',()=>
  document.getElementById('s7').scrollIntoView({behavior:'smooth'}));

/* ══════════ 7-DAY PLAN ══════════ */
document.querySelectorAll('.dchip').forEach(b=>b.addEventListener('click',()=>{
  const d=+b.dataset.d;
  if(S.training.has(d))S.training.delete(d);else S.training.add(d);
  b.classList.toggle('on');
}));

function poolFor(slot,pref){
  const i=SLOTS.indexOf(slot);
  return PLAN.filter(d=>d.s[i]==='1' &&
    (pref==='nonveg' ? true : pref==='egg' ? (d.v==='veg'||d.v==='egg') : d.v==='veg'));
}
function pickFoods(slot,budget,pref,used,n){
  let pool=poolFor(slot,pref);
  if(!pool.length)return [];
  const fresh=pool.filter(d=>!used.has(d.n));
  if(fresh.length>=n)pool=fresh;
  const chosen=[];
  const bag=pool.slice();
  for(let k=0;k<Math.min(n,bag.length);k++){
    chosen.push(bag.splice(Math.floor(Math.random()*bag.length),1)[0]);
  }
  const base=chosen.reduce((a,d)=>a+d.e,0)||1;
  const mult=Math.round(Math.min(MAX_MULT,Math.max(MIN_MULT,budget/base))*100)/100;
  chosen.forEach(d=>used.add(d.n));
  return chosen.map(d=>({name:titleCase(d.n),serving:`${mult}× ${d.u}`,
    e:+(d.e*mult).toFixed(1),p:+(d.p*mult).toFixed(1),
    c:+(d.c*mult).toFixed(1),f:+(d.f*mult).toFixed(1)}));
}
function dayTargets(base,training){
  const t=training.size, r=7-t;
  const shift=(t>0&&t<7)?TRAINING_SHIFT:0;
  const back=r?shift*t/r:0;
  return Array.from({length:7},(_,i)=>training.has(i)
    ? {type:'training',target:Math.round(base*(1+shift))}
    : {type:'rest',target:Math.round(base*(1-back))});
}
function buildWeek(){
  if(!requireAuth('generate a 7-day plan'))return;
  if(!S.profile){
    $('weekNote').textContent='Run your numbers first — scroll up, fill the form, hit “Run my numbers”.';
    document.getElementById('s4').scrollIntoView({behavior:'smooth'});
    return;
  }
  const p=S.profile;
  const used={}; SLOTS.forEach(s=>used[s]=new Set());

  // The favourite is not a garnish: it gets a real seat at a real meal, three
  // days a week, and the rest of that meal is built around what's left.
  const fav=p.fav;
  let favSlot=null;
  if(fav){
    const eligible=SLOTS.filter((s,i)=>s!=='early morning'&&fav.s[i]==='1');
    // a favourite with no slot of its own still gets a seat at dinner
    favSlot=eligible.length?eligible[eligible.length-1]:'dinner';
  }
  const favDays=new Set([0,3,6]);

  const days=dayTargets(p.target,S.training).map((d,i)=>{
    const meals=SLOTS.filter(s=>s!=='early morning').map(slot=>{
      const budget=Math.round(d.target*MEAL_SPLIT[slot]);
      let foods;
      if(fav&&slot===favSlot&&favDays.has(i)){
        const favItem={name:titleCase(fav.n),serving:`1× ${fav.u}`,e:+fav.e.toFixed(1),
          p:+fav.p.toFixed(1),c:+fav.c.toFixed(1),f:+fav.f.toFixed(1),star:true};
        const left=Math.max(budget-fav.e,0);
        const rest=left>60?pickFoods(slot,left,p.pref,used[slot],
                                     Math.max(DISH_COUNT[slot]-1,1)):[];
        foods=[favItem,...rest];
      }else{
        foods=pickFoods(slot,budget,p.pref,used[slot],DISH_COUNT[slot]);
      }
      return {slot,label:SLOT_LABEL[slot],budget,foods,
        totals:foods.reduce((a,f)=>({e:+(a.e+f.e).toFixed(1),p:+(a.p+f.p).toFixed(1),
          c:+(a.c+f.c).toFixed(1),f:+(a.f+f.f).toFixed(1)}),{e:0,p:0,c:0,f:0})};
    });
    const totals=meals.reduce((a,m)=>({e:+(a.e+m.totals.e).toFixed(1),p:+(a.p+m.totals.p).toFixed(1),
      c:+(a.c+m.totals.c).toFixed(1),f:+(a.f+m.totals.f).toFixed(1)}),{e:0,p:0,c:0,f:0});
    // protein and fat hold steady; carbs absorb the day's shift
    const carbShift=(d.target-p.target)/4;
    const carbs=Math.max(p.macros.carbs*CARB_FLOOR,p.macros.carbs+carbShift);
    return {i,weekday:WEEKDAYS[i],type:d.type,target:d.target,meals,totals,
      macros:{protein:p.macros.protein,fat:p.macros.fat,carbs:+carbs.toFixed(1)}};
  });
  S.week=days;
  paintWeek();
}
function paintWeek(){
  const wrap=$('week');
  wrap.innerHTML=S.week.map(d=>{
    const peek=d.meals.find(m=>m.slot==='lunch');
    return `<div class="daycard ${d.type==='training'?'train':'rest'}" data-day="${d.i}">
      <div class="d"><span>${d.weekday.slice(0,3).toUpperCase()}</span>
        <i>${d.type==='training'?'TRAINING':'REST'}</i></div>
      <div class="kc">${d.target.toLocaleString()}<i>KCAL TARGET</i></div>
      <div class="mm">ON THE PLATE ${Math.round(d.totals.e).toLocaleString()}<br>
        P ${d.totals.p} · C ${d.totals.c} · F ${d.totals.f}</div>
      <div class="peek">${peek&&peek.foods.length?peek.foods.map(f=>f.name).join(', '):'—'}</div>
      <div class="acts ui">
        <button class="btn ghost" data-open="${d.i}">See day</button>
        <button class="btn" data-log="${d.i}">Log it</button>
      </div>
    </div>`;}).join('');
  requestAnimationFrame(()=>wrap.querySelectorAll('.daycard')
    .forEach((c,i)=>setTimeout(()=>c.classList.add('in'),i*70)));

  wrap.querySelectorAll('[data-open]').forEach(b=>b.addEventListener('click',
    ()=>showDay(S.week[+b.dataset.open])));
  wrap.querySelectorAll('[data-log]').forEach(b=>b.addEventListener('click',
    ()=>logDay(S.week[+b.dataset.log])));

  const wt=S.week.reduce((a,d)=>({e:a.e+d.totals.e,p:a.p+d.totals.p,
    c:a.c+d.totals.c,f:a.f+d.totals.f}),{e:0,p:0,c:0,f:0});
  $('weekTotal').style.display='flex';
  $('wtKc').textContent=Math.round(wt.e).toLocaleString();
  $('wtAvg').textContent=Math.round(wt.e/7).toLocaleString();
  $('wtP').textContent=Math.round(wt.p).toLocaleString();
  $('wtC').textContent=Math.round(wt.c).toLocaleString();
  $('wtF').textContent=Math.round(wt.f).toLocaleString();
  $('shuffleBtn').disabled=false;
  $('weekNote').textContent='Seven days, no repeats. Training days run '+
    Math.round(TRAINING_SHIFT*100)+'% higher; rest days give back exactly the same amount, so the week still lands on target.';
}
function showDay(d){
  const body=`<div class="bigkc">${Math.round(d.totals.e).toLocaleString()}<i>KCAL</i></div>
    <div class="mrow">
      <div class="p"><span>PROTEIN</span><b>${d.totals.p}g</b></div>
      <div class="c"><span>CARBS</span><b>${d.totals.c}g</b></div>
      <div class="f"><span>FAT</span><b>${d.totals.f}g</b></div>
    </div>
    <div class="meta">DAY TYPE · <b>${d.type==='training'?'Training day':'Rest day'}</b><br>
      TARGET · <b>${d.target.toLocaleString()} kcal</b><br>
      CARB TARGET · <b>${d.macros.carbs} g</b> ${d.type==='training'?'(loaded up)':'(dialled back)'}</div>
    <div style="margin-top:26px">${d.meals.map(m=>`
      <div class="mealblk">
        <div class="h"><span>${m.label}</span><b>${Math.round(m.totals.e)} KCAL</b></div>
        <ul>${m.foods.length?m.foods.map(f=>
          `<li><span>${f.star?'<span style="color:var(--acid)">★ </span>':''}${f.name}</span><i>${f.serving} · ${Math.round(f.e)}</i></li>`).join('')
          :'<li><span>Nothing matched your filters here</span></li>'}</ul>
      </div>`).join('')}</div>`;
  openDrawer('DAY '+(d.i+1),d.weekday,body,
    `<button class="btn solid" id="logDayBtn">Log this whole day</button>`);
  document.getElementById('logDayBtn').addEventListener('click',()=>{logDay(d);closeDrawer();});
}
function logDay(d){
  if(!requireAuth('log a day'))return;
  d.meals.forEach(m=>m.foods.forEach(f=>{
    S.log.push({name:f.name,kcal:f.e,p:f.p,c:f.c,f:f.f,note:m.label+' · '+f.serving});
  }));
  paintTray(d.totals.e);
}
$('weekBtn').addEventListener('click',buildWeek);
$('shuffleBtn').addEventListener('click',buildWeek);

/* ══════════ BURGER ANATOMY ══════════ */
const BURGER=[
  {part:'BUN · 55 G', macro:'CARBS', col:'#e8a33d', g:55, kcal:153.5, p:5.0,c:27.5,f:2.5, dens:2.79,
   role:'Two halves, one number. It’s the quiet 154 that nobody counts — not a villain, just worth knowing about.'},
  {part:'PATTY · 80 G', macro:'PROTEIN', col:'#ff5b1f', g:80, kcal:156.0, p:19.8,c:1.1,f:8.1, dens:1.95,
   role:'Protein-loading, secured. Twenty grams of protein for 156 kcal is the best deal on the whole plate.'},
  {part:'CHEESE · 20 G', macro:'FAT', col:'#ffd93d', g:20, kcal:80.6, p:5.0,c:0.3,f:6.6, dens:4.03,
   role:'Twenty grams doing the work of eighty. Keep it — fat runs your hormones. Just know it’s there.'},
  {part:'LETTUCE · 20 G', macro:'FIBRE', col:'#8fe36a', g:20, kcal:3.0, p:0.3,c:0.4,f:0.0, dens:0.15,
   role:'Three calories. Fibermaxxing starts here: bulk, crunch, and basically nothing on the tally.'},
  {part:'ONION · 12 G', macro:'FIBRE', col:'#c58ad6', g:12, kcal:4.8, p:0.1,c:1.1,f:0.0, dens:0.40,
   role:'Under five calories. Add more of it. Genuinely, add more of it.'},
  {part:'TOMATO · 25 G', macro:'FIBRE', col:'#e5453a', g:25, kcal:4.5, p:0.2,c:1.0,f:0.1, dens:0.18,
   role:'All three veg layers together cost less than 3% of the burger. This is the free real estate.'},
  {part:'SAUCE · 22 G', macro:'FAT', col:'#f4e3b8', g:22, kcal:170.5, p:0.4,c:0.4,f:18.6, dens:7.75,
   role:'The plot twist. Nearly eight calories a gram — the densest thing in the stack, and the one nobody sees coming.'},
];
(function(){
  const layers=[...document.querySelectorAll('#burger .layer')];
  const hots=[...document.querySelectorAll('.hot2')];
  const hotsG=$('hots'), card=$('dCard'), prompt=$('dPrompt');
  let cur=-1, sf=0;

  function pick(i){
    if(i===cur){reset();return;}
    cur=i;const d=BURGER[i];
    hotsG.classList.add('hide');
    layers.forEach(l=>{const k=+l.dataset.i;
      l.classList.toggle('sel',k===i);l.classList.toggle('dim',k!==i);});
    prompt.style.opacity=0;
    card.classList.remove('on');card.style.color=d.col;
    setTimeout(()=>{
      $('dPart').textContent=d.part;
      $('dRole').textContent=d.role;
      $('dG').textContent=d.g+' g';
      $('dK').textContent=d.kcal;
      $('dPcf').textContent=`${d.p} · ${d.c} · ${d.f}`;
      $('dDlab').textContent=d.macro+' · '+d.dens.toFixed(2)+' KCAL/G';
      $('dMacro').style.color=d.col;
      $('dFill').style.width=Math.min(d.dens/9*100,100)+'%';
      card.classList.add('on');
      decode($('dMacro'),d.macro);
    },220);
  }
  function reset(){
    cur=-1;layers.forEach(l=>l.classList.remove('sel','dim'));
    hotsG.classList.remove('hide');card.classList.remove('on');
    $('dFill').style.width=0;setTimeout(()=>prompt.style.opacity=1,180);
  }
  function decode(el,word){
    const my=++sf;let f=0;
    const q=[...word].map((ch,i)=>({ch,s:i*2,e:i*2+11}));
    (function run(){
      if(my!==sf)return;
      let out='',done=0;
      q.forEach(o=>{if(f>=o.e){done++;out+=o.ch;}else if(f>=o.s)out+=CH[Math.floor(Math.random()*CH.length)];});
      el.textContent=out;f++;
      if(done<q.length)requestAnimationFrame(run);
    })();
  }
  layers.forEach(l=>{l.setAttribute('data-cursor','TAP');
    l.addEventListener('click',e=>{e.stopPropagation();pick(+l.dataset.i);});});
  hots.forEach(h=>{h.setAttribute('data-cursor','TAP');
    h.addEventListener('click',e=>{e.stopPropagation();pick(+h.dataset.i);});});
  $('dLog').addEventListener('click',e=>{
    e.stopPropagation();
    if(cur<0||!requireAuth('log a layer'))return;
    const d=BURGER[cur];
    addLog(titleCase(d.part.split('·')[0].trim()),d.kcal,d.p,d.c,d.f,'burger layer');
  });
  document.getElementById('sB').addEventListener('click',()=>{if(cur>-1)reset();});
})();

/* ══════════ THE DEALER — what can I eat right now ══════════ */
let dealSlot='any';
document.querySelectorAll('.spick').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.spick').forEach(o=>o.classList.remove('on'));
  b.classList.add('on'); dealSlot=b.dataset.slot;
}));
/* "Use what's left today" needs a target to subtract from. Without one it used
   to silently write 600 over 600, which looked like a dead button — so now it
   always reports what it did, or why it couldn't. */
function dealMsg(html,warn){
  const el=$('dealMsg');
  el.innerHTML=html; el.classList.toggle('warn',!!warn);
}
$('dealFill').addEventListener('click',()=>{
  if(!requireAuth('use your remaining calories'))return;
  const t=logTotals();
  if(!S.profile){
    dealMsg('No target yet — run your numbers up in <b>“tell us your goals”</b> and this button will fill in exactly what you have left.',true);
    $('s4').scrollIntoView({behavior:'smooth'});
    setTimeout(()=>{
      $('goalForm').classList.add('flashfield');
      setTimeout(()=>$('goalForm').classList.remove('flashfield'),950);
    },700);
    return;
  }
  const raw=Math.round(S.profile.target-t.kcal);
  const left=Math.max(raw,120);
  $('dealKc').value=left;
  $('dealKc').classList.add('flashfield');
  setTimeout(()=>$('dealKc').classList.remove('flashfield'),950);
  if(raw<=0){
    dealMsg(`You're already at your target (<b>${Math.round(t.kcal).toLocaleString()}</b> of <b>${S.profile.target.toLocaleString()}</b>). Set to <b>120</b> — something small, if you want it.`,true);
  }else{
    dealMsg(`Target <b>${S.profile.target.toLocaleString()}</b> − logged <b>${Math.round(t.kcal).toLocaleString()}</b> = <b>${left.toLocaleString()} kcal</b> left. Pull the lever.`);
  }
});

function dealPool(){
  const pref=S.profile?S.profile.pref:'nonveg';
  const base=PLAN.filter(d=>pref==='nonveg'?true:pref==='egg'
    ?(d.v==='veg'||d.v==='egg'):d.v==='veg');
  if(dealSlot==='any')return base.filter(d=>d.s.slice(1).includes('1'));
  const i=SLOTS.indexOf(dealSlot);
  return base.filter(d=>d.s[i]==='1');
}
/* Find 1–3 dishes that land inside the budget, closest fit wins. Portions are
   half-steps, the way anyone actually serves food. */
function findCombo(budget,pool){
  if(!pool.length)return null;
  const STEPS=[0.5,1,1.5,2];
  let best=null;
  for(let tries=0;tries<900;tries++){
    const n=1+Math.floor(Math.random()*3);
    const picks=[],bag=pool.slice();
    for(let k=0;k<n&&bag.length;k++)
      picks.push(bag.splice(Math.floor(Math.random()*bag.length),1)[0]);
    const items=picks.map(d=>{
      const want=budget/picks.length/d.e;
      const m=STEPS.reduce((a,b)=>Math.abs(b-want)<Math.abs(a-want)?b:a,STEPS[0]);
      return {d,m};
    });
    const total=items.reduce((a,i)=>a+i.d.e*i.m,0);
    if(total>budget)continue;
    if(!best||total>best.total)best={items,total};
    if(budget-total<budget*0.06)break;
  }
  if(!best){                       // budget too small for a whole portion
    const d=pool.reduce((a,b)=>b.e<a.e?b:a);
    best={items:[{d,m:0.5}],total:d.e*0.5};
  }
  return best;
}
function verdictFor(total,budget){
  const gap=budget-total;
  if(gap<budget*0.08)return 'That lands almost exactly on your number. Go eat it.';
  if(gap<budget*0.25)return `Leaves ${Math.round(gap)} kcal spare — room for chai, or fruit, or nothing at all.`;
  return `Comes in ${Math.round(gap)} kcal under. You could go bigger, or bank it. Both are fine.`;
}
function dealPlate(){
  if(!requireAuth('be dealt a plate'))return;
  const budget=Math.max(50,+$('dealKc').value||600);
  const pool=dealPool();
  const reel=$('reel');
  if(!pool.length){
    reel.innerHTML='<div class="waiting">Nothing in the menu matches that moment and your food preference. Try “any time”.</div>';
    return;
  }
  // slot-machine tease before the answer
  reel.innerHTML='<div class="spinner"><div id="r1">—</div><div id="r2">—</div><div id="r3">—</div></div>';
  const r=[$('r1'),$('r2'),$('r3')];
  let ticks=0;
  const spin=setInterval(()=>{
    r.forEach(el=>{el.textContent=titleCase(pool[Math.floor(Math.random()*pool.length)].n);});
    if(++ticks>13){
      clearInterval(spin);
      const combo=findCombo(budget,pool);
      S.deal={combo,budget};
      const tot=combo.items.reduce((a,i)=>({
        e:a.e+i.d.e*i.m,p:a.p+i.d.p*i.m,c:a.c+i.d.c*i.m,f:a.f+i.d.f*i.m}),
        {e:0,p:0,c:0,f:0});
      reel.innerHTML=`<div class="combo">
        <ol>${combo.items.map((it,k)=>`<li>
          <span class="num">${String(k+1).padStart(2,'0')}</span>
          <span class="nm">${titleCase(it.d.n)}
            <small>${it.m}× ${it.d.u} · ${Math.round(it.d.g*it.m)} g · ${it.d.r}</small></span>
          <span class="kk">${Math.round(it.d.e*it.m)}</span></li>`).join('')}</ol>
        <div class="sum"><b>${Math.round(tot.e)}</b>
          <span>KCAL OF ${budget}<br>P ${tot.p.toFixed(1)} · C ${tot.c.toFixed(1)} · F ${tot.f.toFixed(1)}</span></div>
        <div class="verdict">${verdictFor(tot.e,budget)}</div>
      </div>`;
      $('dealLog').disabled=false;
    }
  },70);
}
$('dealBtn').addEventListener('click',()=>{dealMsg('');dealPlate();});
$('dealLog').addEventListener('click',()=>{
  if(!S.deal||!requireAuth('log this plate'))return;
  S.deal.combo.items.forEach(it=>{
    S.log.push({name:titleCase(it.d.n),kcal:it.d.e*it.m,p:it.d.p*it.m,
      c:it.d.c*it.m,f:it.d.f*it.m,note:`dealt · ${it.m}× ${it.d.u}`});
  });
  paintTray(S.deal.combo.total);
  $('dealLog').disabled=true;
});

/* ══════════ CTA — build your plate (with the M5) ══════════ */
(function(){
  const m=$('mag'), wrap=$('magWrap'), rev=$('rev'), ndl=$('tachNdl');
  const LEN=2*Math.PI*140;
  ndl.setAttribute('stroke-dasharray',LEN.toFixed(1));
  ndl.style.strokeDashoffset=LEN.toFixed(1);

  m.addEventListener('mousemove',e=>{
    const r=m.getBoundingClientRect();
    m.style.transform='translate('+((e.clientX-r.left-r.width/2)*.32)+'px,'
      +((e.clientY-r.top-r.height/2)*.32)+'px)';
  });
  m.addEventListener('mouseleave',()=>m.style.transform='translate(0,0)');

  // Every click blips the throttle again: the sound restarts from zero and the
  // needle sweep starts over. `gen` makes the previous sweep stand down, so a
  // rapid second click never leaves two animations fighting over the needle.
  let gen=0;
  m.addEventListener('click',()=>{
    if(!requireAuth('build your plate'))return;
    const mine=++gen;
    wrap.classList.add('revving');
    try{
      rev.pause();
      rev.currentTime=0;
      const pr=rev.play();
      if(pr&&pr.catch)pr.catch(()=>{});   // AbortError when a click interrupts the last play
    }catch(_){}
    const dur=(rev.duration&&isFinite(rev.duration)&&rev.duration>0?rev.duration:3.2)*1000;
    const t0=performance.now();
    (function sweep(now){
      if(mine!==gen)return;               // a newer click owns the needle now
      const t=Math.min((now-t0)/dur,1);
      // needle climbs, hangs at the limiter, then drops back
      const rpm=t<.55 ? Math.pow(t/.55,.65) : t<.8 ? 1-(t-.55)*.12 : (1-(t-.8)/.2)*.85;
      ndl.style.strokeDashoffset=(LEN*(1-Math.max(rpm,0)*.92)).toFixed(1);
      $('redline').textContent='▲ '+Math.round(1000+Math.max(rpm,0)*6200)+' RPM';
      if(t<1){requestAnimationFrame(sweep);return;}
      wrap.classList.remove('revving');
      ndl.style.strokeDashoffset=LEN.toFixed(1);
      $('redline').textContent='▲ REDLINE · 7200 RPM';
      $('deal').scrollIntoView({behavior:'smooth'});
      setTimeout(()=>{
        if(mine!==gen)return;
        const tot=logTotals();
        if(S.profile)$('dealKc').value=Math.max(Math.round(S.profile.target-tot.kcal),120);
        dealPlate();
      },900);
    })(performance.now());
  });
})();


/* ══════════════════════════════════════════════════════════════════════
   MAPO COACH — a faithful port of mapo_chatbot.py.
   Same rule order (drink → junk → meal → general), same brand table, same
   volume/quantity parsing, same Hinglish/English copy. Runs in the page, so
   there is no LLM and no request: exactly the behaviour of the Python module.
   ══════════════════════════════════════════════════════════════════════ */
const BRANDS={
 "mimosa":{base:"Mimosa",ml:120,cal30:25}, "mojito":{base:"Mojito",ml:200,cal30:22},
 "bloody mary":{base:"Bloody Mary",ml:180,cal30:20}, "cosmopolitan":{base:"Cosmopolitan",ml:100,cal30:45},
 "mai tai":{base:"Mai Tai",ml:150,cal30:40}, "rum and coke":{base:"Rum and Coke",ml:200,cal30:25},
 "white russian":{base:"White Russian",ml:150,cal30:50}, "old fashioned":{base:"Old Fashioned",ml:90,cal30:55},
 "martini":{base:"Martini",ml:90,cal30:50}, "long island iced tea":{base:"LIIT",ml:220,cal30:35},
 "liit":{base:"LIIT",ml:220,cal30:35}, "pina colada":{base:"Piña Colada",ml:200,cal30:45},
 "beluga":{base:"Vodka",ml:30,cal30:65}, "absolut":{base:"Vodka",ml:30,cal30:65},
 "smirnoff":{base:"Vodka",ml:30,cal30:65}, "grey goose":{base:"Vodka",ml:30,cal30:65},
 "royal stag":{base:"Whiskey",ml:30,cal30:70}, "blenders pride":{base:"Whiskey",ml:30,cal30:70},
 "johnnie walker":{base:"Whiskey",ml:30,cal30:70}, "chivas regal":{base:"Whiskey",ml:30,cal30:70},
 "old monk":{base:"Dark Rum",ml:30,cal30:65}, "bacardi":{base:"Rum",ml:30,cal30:65},
 "bombay sapphire":{base:"Gin",ml:30,cal30:65}, "tanqueray":{base:"Gin",ml:30,cal30:65},
 "sula":{base:"Wine",ml:150,cal30:24}, "chardonnay":{base:"Wine",ml:150,cal30:24},
 "kingfisher":{base:"Beer",ml:330,cal30:13}, "bira":{base:"Beer",ml:330,cal30:13},
 "budweiser":{base:"Beer",ml:330,cal30:13}, "heineken":{base:"Beer",ml:330,cal30:13},
 "corona":{base:"Beer",ml:330,cal30:13}
};
const DRINKS=["Absinthe","Amaretto","Baileys","Blue Curacao","Bourbon Whiskey","Brandy","Chambord","Coffee Liqueur","Cointreau","Daiquiri","Vodka","Whiskey Sour","Dark Rum","Drambuie","Eggnog","Frangelico","Gin","Gin Tonic","Grand Marnier","Jack Daniel's","Jim Beam","Jägermeister","Kahlua","Liquor, Cordial","Piña Colada","Rum","Sambuca","Scotch Whisky","Southern Comfort","Tequila","Triple Sec","Beer (light)","Beer (regular)","Beer (higher alcohol/craft beers)","Gin (80 proof)","Gin (94 proof)","Rum (80 proof)","Rum (94 proof)","Vodka (80 proof)","Vodka (94 proof)","Whiskey (80 proof)","Whiskey (94 proof)","Coffee liqueur","Coffee liqueur with cream","Crème de menthe","Bloody Mary","Chocolate martini","Cosmopolitan","Highball","Hot buttered rum","Mai Tai","Margarita","Mimosa","Mint Julep","Mojito","Piña colada","Rum and Coke","Rum and Diet Coke","Tequila Sunrise","Vodka and tonic","White Russian","White table wine","Gewurztraminer","Muscat","Riesling","Chenin Blanc","Chardonnay","Sauvignon Blanc","Fumé Blanc","Pinot Grigio","Dry dessert wine","Red table wine","Petite Sirah","Merlot","Cabernet Sauvignon","Red Zinfandel","Burgundy","Pinot Noir","Claret","Syrah","Red dessert wine","Champagne","Rosé wine","Prosecco","Port wine","Sherry","Cider","Hard seltzer","Whiskey Highball","Moscow Mule","Old Fashioned","Negroni","Martini","Aperol Spritz","Long Island Iced Tea (LIIT)","Gin & Tonic","Tom Collins","Gin Fizz","Gimlet","Dry Martini","French 75","Singapore Sling","Aviation","Bramble","Southside","Gin Basil Smash","Bee's Knees","Clover Club"];
const GENERIC=["whiskey","whisky","beer","vodka","rum","gin","wine","cocktail",
               "brandy","tequila","cider","champagne"];

function extractDrink(message){
  const m=message.toLowerCase().trim();
  let label=null, map=null;
  for(const b of Object.keys(BRANDS).sort((a,b)=>b.length-a.length)){
    if(m.includes(b)){label=titleCase(b);map=BRANDS[b];break;}
  }
  if(!map){
    for(const d of DRINKS.slice().sort((a,b)=>b.length-a.length)){
      if(m.includes(d.toLowerCase())){label=d;map={base:d,ml:30,cal30:65};break;}
    }
  }
  if(!map){
    for(const t of GENERIC){
      if(m.includes(t)){
        label=t[0].toUpperCase()+t.slice(1);
        map={base:label,ml:t==='beer'?330:30,cal30:t==='beer'?13:65};
        break;
      }
    }
  }
  if(!map)return null;
  const vol=m.match(/(\d+(?:\.\d+)?)\s*ml\b/);
  const qty=m.match(/(\d+)\s*(pegs?|glass(?:es)?|pints?|shots?|drinks?|bottles?|cans?|cups?)/);
  const userMl=vol?parseFloat(vol[1]):null;
  const userQty=qty?parseFloat(qty[1]):null;
  const totalMl=userMl!==null?userMl:(userQty!==null?userQty*map.ml:map.ml);
  return {drink:label,ml:totalMl,qty:userQty||1,cal:Math.round(totalMl/30*map.cal30*10)/10};
}

/* the coach carries its own targets, same formulas as the Python module —
   note the floor on a fat-loss goal that the plan generator does not apply */
function coachProfile(){
  const p=S.profile;
  const w=p?+($('fWeight').value||70):70, ht=p?+($('fHeight').value||170):170;
  const age=p?+($('fAge').value||25):25;
  const gender=($('fGender').value||'male').toLowerCase();
  const act=p?p.act:2, goal=p?p.goal:3;
  const bmi=+(w/Math.pow(ht/100,2)).toFixed(2);
  const bmr=+(gender==='male'?(10*w)+(6.25*ht)-(5*age)+5:(10*w)+(6.25*ht)-(5*age)-161).toFixed(2);
  const tdee=+(bmr*ACTIVITY[act]).toFixed(2);
  let target;
  if(goal===1)target=tdee;
  else if(goal===2)target=tdee*1.10;
  else if(goal===3)target=Math.max(tdee*0.80,gender==='male'?1500:1200);
  else target=tdee*(bmi<25?1:bmi<30?.95:bmi<35?.90:.85);
  return {name:(p&&p.name)||(S.user&&S.user.name)||'Friend',
          bmi,bmr,tdee,target:Math.round(target),
          pref:p?p.pref:'veg'};
}
function recommendMeals(slot,budget,pref){
  let res=PLAN.filter(d=>pref==='nonveg'?true:pref==='egg'?(d.v==='veg'||d.v==='egg'):d.v==='veg');
  const i=SLOTS.indexOf(slot);
  const inSlot=res.filter(d=>d.s[i]==='1');
  if(inSlot.length)res=inSlot;
  const fit=res.filter(d=>d.e<=budget+120);
  if(fit.length)res=fit;
  if(!res.length)res=PLAN.slice(0,3);
  const out=[],bag=res.slice();
  for(let k=0;k<Math.min(3,bag.length);k++)
    out.push(bag.splice(Math.floor(Math.random()*bag.length),1)[0]);
  return out;
}
function coachReply(message){
  const prof=coachProfile(), mode=S.coachMode, msg=message.toLowerCase();
  const drink=extractDrink(message);
  if(drink){
    return {text: mode==='hinglish'
      ? `Haanji, koi baat nahi! Outings aur fun moments toh life ka part hain — ek outing se aapki poori progress kharab nahi hoti.<br><br>Aapne lagbhag <strong>${Math.round(drink.ml)}ml ${drink.drink}</strong> se <strong>${Math.round(drink.cal)} kcal</strong> consume kiye. Bas ab dinner thoda light rakhenge aur protein par focus karenge. Guilt bilkul mat feel kariye ji!`
      : `No worries at all! Enjoying a drink with friends is part of life, and one social event won't undo your progress.<br><br>You consumed roughly <strong>${Math.round(drink.cal)} kcal</strong> from <strong>${Math.round(drink.ml)}ml of ${drink.drink}</strong>. Let's keep the rest of your meals lighter and protein-forward. Consistency over perfection!`,
      drink};
  }
  if(['junk','pizza','burger','fries'].some(k=>msg.includes(k))){
    return {text: mode==='hinglish'
      ? "Koi baat nahi ji! Aapko wahi khilana hai jo aapko pasand hai. Better portions aur cleaner swaps ke saath hum aapke calorie aur protein targets ke andar reh kar consistency maintain karenge!"
      : "Not a problem! No need to force foods you dislike. We'll fit your comfort foods in by managing portions and prioritising protein."};
  }
  if(['eat','dinner','lunch','breakfast','suggest','recommend','snack','khaun','khana','bhookh']
       .some(k=>msg.includes(k))){
    let slot='dinner';
    if(msg.includes('lunch'))slot='lunch';
    else if(msg.includes('breakfast')||msg.includes('nashta'))slot='breakfast';
    else if(msg.includes('snack')||msg.includes('high tea'))slot='high tea';
    const meals=recommendMeals(slot,prof.target*0.35,prof.pref);
    const list=meals.map(o=>`• <strong>${titleCase(o.n)}</strong> — ~${Math.round(o.e)} kcal | ${Math.round(o.p)}g protein`).join('<br>');
    return {text: mode==='hinglish'
      ? `Bilkul ji! Aapke targets ke hisaab se yeh badiya balanced options hain:<br><br>${list}<br><br>Inme se apni pasand ka choose kar lijiye — satiety bhi milegi aur protein goals bhi poore honge!`
      : `Here are a few tailored options that fit your remaining budget:<br><br>${list}<br><br>Pick whichever sounds best — they'll keep you full and hit your protein goals!`,
      meals};
  }
  return {text: mode==='hinglish'
    ? `Haanji ${prof.name}! Main aapki nutrition journey me help ke liye taiyar hoon. Bataiye aaj kya khaya ya kya khana plan kar rahe hain — hum milkar adjust kar lenge! (Aapka daily target ~${prof.target} kcal hai.)`
    : `Hello ${prof.name}! I'm here to support your nutrition journey. Tell me what you ate or plan to eat and we'll keep it balanced. (Your daily target is ~${prof.target} kcal.)`};
}

/* ---- coach UI ---- */
S.coachMode='hinglish';
const QUICKS={
  hinglish:["Aaj dinner mein kya khaun?","2 peg whiskey pi li","Breakfast suggest karo","Mujhe pizza chahiye"],
  english:["What should I eat for dinner?","I had 2 pegs of whiskey","Suggest a breakfast","I want pizza"]
};
(function(){
  const panel=$('coach'), logEl=$('coachLog'), inp=$('coachIn'), quick=$('coachQuick');
  const open=()=>{if(!requireAuth('talk to the coach'))return;
    panel.classList.add('on');panel.setAttribute('aria-hidden','false');
    scrim.classList.add('on');setTimeout(()=>inp.focus(),450);};
  const close=()=>{panel.classList.remove('on');panel.setAttribute('aria-hidden','true');
    if(!drawer.classList.contains('on'))scrim.classList.remove('on');};
  $('coachBtn').addEventListener('click',open);
  $('coachClose').addEventListener('click',close);
  panel.addEventListener('coach:close',close);
  scrim.addEventListener('click',()=>{if(!drawer.classList.contains('on'))close();});

  function bubble(who,html,cls){
    const d=document.createElement('div');
    d.className='msg '+cls;
    d.innerHTML=`<span class="who">${who}</span>${html}`;
    logEl.appendChild(d); logEl.scrollTop=logEl.scrollHeight;
    return d;
  }
  function paintQuick(){
    quick.innerHTML=QUICKS[S.coachMode].map(q=>`<button>${q}</button>`).join('');
    quick.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>send(b.textContent)));
  }
  document.querySelectorAll('.modesw button').forEach(b=>b.addEventListener('click',()=>{
    document.querySelectorAll('.modesw button').forEach(o=>o.classList.remove('on'));
    b.classList.add('on'); S.coachMode=b.dataset.mode;
    inp.placeholder = S.coachMode==='hinglish' ? 'kya khaun aaj dinner mein?'
                                               : 'what should I eat tonight?';
    paintQuick();
    bubble('Coach', S.coachMode==='hinglish'
      ? 'Theek hai ji, ab Hinglish mein baat karte hain.'
      : 'Switched to English — carry on.','bot');
  }));

  function send(text){
    const t=(text!==undefined?text:inp.value).trim();
    if(!t)return;
    bubble(S.user?S.user.name:'You', t.replace(/</g,'&lt;'), 'you');
    inp.value='';
    const typing=bubble('Coach','<span class="typing"><span></span><span></span><span></span></span>','bot');
    setTimeout(()=>{
      const r=coachReply(t);
      typing.innerHTML=`<span class="who">Coach</span>${r.text}`;
      if(r.meals){
        const picks=document.createElement('div');
        picks.className='picks';
        r.meals.forEach(m=>{
          const b=document.createElement('button');
          b.textContent='open '+titleCase(m.n).slice(0,22);
          b.addEventListener('click',()=>showFood(m));
          picks.appendChild(b);
        });
        typing.appendChild(picks);
      }
      if(r.drink){
        const picks=document.createElement('div');
        picks.className='picks';
        const b=document.createElement('button');
        b.textContent=`log ${Math.round(r.drink.cal)} kcal`;
        b.addEventListener('click',()=>{
          addLog(r.drink.drink,r.drink.cal,0,0,0,`${Math.round(r.drink.ml)} ml`);
          b.textContent='logged ✓'; b.disabled=true;
        });
        picks.appendChild(b);
        typing.appendChild(picks);
      }
      logEl.scrollTop=logEl.scrollHeight;
    },520);
  }
  $('coachSend').addEventListener('click',()=>send());
  inp.addEventListener('keydown',e=>{if(e.key==='Enter')send();});

  paintQuick();
  bubble('Coach','Haanji! Main MAPO coach hoon. Bataiye aaj kya khaya, ya kya khana plan kar rahe hain — drinks bhi count kar leta hoon, bina judgement ke.','bot');
})();

/* ══════════ SCROLL ENGINE ══════════ */
const s3=$('s3'), track=$('track');
const eqWords=[...document.querySelectorAll('#eq .w')];
const scrubFill=$('scrubFill'), tc=$('tc'), lbl=$('sceneLbl'), flash=$('flash');
const scenes=[...document.querySelectorAll('[data-scene]')];
let lastScene='';
scenes.forEach(s=>{
  const m=document.createElement('div');m.className='mark';
  $('scrub').appendChild(m);s._mark=m;
});
function frame(){
  const y=scrollY, vh=innerHeight;
  const max=Math.max(document.body.scrollHeight-vh,1);
  const prog=Math.min(y/max,1);
  scrubFill.style.width=(prog*100)+'%';
  scenes.forEach(s=>{s._mark.style.left=(s.offsetTop/max*100)+'%';});

  const total=prog*196;
  tc.textContent='00:'+String(Math.floor(total/60)).padStart(2,'0')+':'
    +String(Math.floor(total%60)).padStart(2,'0')+':'
    +String(Math.floor((total%1)*24)).padStart(2,'0');

  let active=scenes[0];
  scenes.forEach(s=>{if(y+vh*.45>=s.offsetTop)active=s;});
  if(active.dataset.scene!==lastScene){
    lastScene=active.dataset.scene;lbl.textContent=lastScene;
    flash.classList.remove('hit');void flash.offsetWidth;flash.classList.add('hit');
  }

  const r3=s3.getBoundingClientRect();
  if(r3.top<=0&&r3.bottom>=vh){
    const p=(-r3.top)/(s3.offsetHeight-vh);
    const dist=track.scrollWidth-innerWidth+innerWidth*.1;
    track.style.transform='translateX('+(-p*dist)+'px)';
  }

  const r5=$('s5').getBoundingClientRect();
  const p5=1-(r5.top/vh);
  eqWords.forEach((w,i)=>w.classList.toggle('lit',p5*1.35>i/eqWords.length));

  requestAnimationFrame(frame);
}
frame();
