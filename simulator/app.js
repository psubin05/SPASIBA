'use strict';
const $ = id => document.getElementById(id);
const canvas = $('scene'), ctx = canvas.getContext('2d');
let map, layout, nodes, qrs, result, walker, animation, lastTime, progress=0;
let running=false, requestVersion=0, angle=-0.28, elevation=0.92, zoom=1, flat=false;
let width=800, height=560, faces=[], labels=[];
const occupied=new Set(['B2-A-01','B2-A-03','B2-B-02']);
const occupancyInputs=new Map();
const colors=['#d09064','#e4d6a5','#4d7c81','#9aada1','#c1b3c9','#7e96b1','#d2ae79','#b47d76'];
async function api(url,options){const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);try{const response=await fetch(url,{...options,signal:controller.signal,cache:'no-store'});let data;try{data=await response.json();}catch{throw Error('서버 응답 형식을 확인할 수 없습니다. 다시 시도해주세요.');}if(!response.ok)throw Error(data.error?.message||'요청에 실패했습니다.');return data;}catch(error){if(error.name==='AbortError')throw Error('서버 응답 시간이 초과됐습니다. 연결을 확인하고 다시 시도해주세요.');throw error;}finally{clearTimeout(timeout);}}
const post=(url,data)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
let demoEnabled=false,operatorBusy=false;
function status(text,error=false){$('status').textContent=text;$('status').className=error?'error':'';}
function project(x,y,z){
  const b=layout.board, dx=x-(b.x+b.width/2),dy=y-(b.y+b.depth/2);
  const rx=dx*Math.cos(angle)-dy*Math.sin(angle), ry=dx*Math.sin(angle)+dy*Math.cos(angle);
  const depth=ry*Math.cos(elevation)-z*Math.sin(elevation);
  const perspective=flat?1:35/(35+depth);
  const scale=Math.min(width/(b.width*1.3),height/(b.depth+9))*zoom;
  return {x:width/2+rx*scale*perspective,y:height/2+(ry*Math.sin(elevation)-z*Math.cos(elevation))*scale*perspective,depth};
}
function polygon(points,color,stroke=null){const projected=points.map(p=>project(...p));faces.push({points:projected,color,stroke,depth:projected.reduce((v,p)=>v+p.depth,0)/projected.length});}
function plane(x,y,w,d,z,color,stroke){polygon([[x,y,z],[x+w,y,z],[x+w,y+d,z],[x,y+d,z]],color,stroke);}
function box(x,y,w,d,z,h,color){
  polygon([[x,y,z],[x+w,y,z],[x+w,y,z+h],[x,y,z+h]],'#9da394');
  polygon([[x+w,y,z],[x+w,y+d,z],[x+w,y+d,z+h],[x+w,y,z+h]],'#8d9589');
  polygon([[x+w,y+d,z],[x,y+d,z],[x,y+d,z+h],[x+w,y+d,z+h]],color);
  polygon([[x,y+d,z],[x,y,z],[x,y,z+h],[x,y+d,z+h]],color);
  plane(x,y,w,d,z+h,color);
}
function text(value,x,y,z,color='#2e4739',size=11){labels.push({value,p:project(x,y,z),color,size});}
function segment(a,b,color,r=.09){const dx=b.x-a.x,dy=b.y-a.y,l=Math.hypot(dx,dy);if(!l)return;const nx=-dy/l*r,ny=dx/l*r;polygon([[a.x+nx,a.y+ny,.09],[b.x+nx,b.y+ny,.09],[b.x-nx,b.y-ny,.09],[a.x-nx,a.y-ny,.09]],color);}
function draw(){
  if(!layout)return;
  faces=[];labels=[];ctx.clearRect(0,0,width,height);
  const b=layout.board;
  box(b.x,b.y,b.width,b.depth,-.35,.35,'#dedac9');
  const aisle=layout.aisle;plane(aisle.x,aisle.y,aisle.width,aisle.depth,.015,'#c9cebf');
  for(let x=aisle.x+.4;x<aisle.x+aisle.width;x+=1.2)plane(x,aisle.y+aisle.depth/2-.025,.55,.05,.025,'#edf0e5');
  for(const wall of layout.walls)box(wall.x,wall.y,wall.width,wall.depth,0,wall.height,'#e4e0d2');
  map.slots.forEach((slot,i)=>{
    const p=slot.polygon, xs=p.map(v=>v[0]),ys=p.map(v=>v[1]);
    const x=Math.min(...xs),y=Math.min(...ys),w=Math.max(...xs)-x,d=Math.max(...ys)-y;
    const selected=slot.slot_id===$('destination').value;
    plane(x,y,w,d,.03,selected?'#f3dbb9':'#e2e6da','#fdfbf1');
    const n=nodes[slot.node_id];text(slot.name,n.x,n.y,.15,selected?'#a65c21':'#4f6453',12);
    if(occupied.has(slot.slot_id)){
      const cx=x+w/2,cy=y+d/2;
      box(cx-w*.31,cy-d*.34,w*.62,d*.68,.06,.38,colors[i]);
      box(cx-w*.25,cy-d*.19,w*.5,d*.34,.44,.25,'#d3e2df');
      plane(cx-w*.2,cy-d*.10,w*.4,d*.20,.70,colors[i]);
      for(const wx of [cx-w*.33,cx+w*.23])for(const wy of [cy-d*.23,cy+d*.15])box(wx,wy,w*.10,d*.12,.04,.18,'#434c44');
    }
  });
  for(const qr of qrs){const n=nodes[qr.node_id];box(n.x-.18,n.y-.18,.36,.36,0,.7,'#38755d');text('QR',n.x,n.y,.9,'#205640',13);}
  if($('showCameras').checked)for(const camera of layout.camera_mounts){
    box(camera.x-.05,camera.y-.05,.1,.1,0,camera.height,'#748b96');
    box(camera.x-.25,camera.y-.16,.5,.32,camera.height,.23,'#4e82ab');
    text(camera.label,camera.x,camera.y,camera.height+.5,'#35648a',10);
  }
  if(result)for(let i=1;i<result.path.length;i++)segment(result.path[i-1],result.path[i],'#df843e');
  if(walker){box(walker.x-.12,walker.y-.12,.24,.24,.12,.5,'#2b8a61');text('●',walker.x,walker.y,.85,'#2b8a61',17);}
  faces.sort((a,b)=>b.depth-a.depth);
  for(const face of faces){ctx.beginPath();face.points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.closePath();ctx.fillStyle=face.color;ctx.fill();if(face.stroke){ctx.strokeStyle=face.stroke;ctx.lineWidth=1.5;ctx.stroke();}}
  for(const label of labels){ctx.font=`600 ${label.size}px system-ui`;ctx.textAlign='center';ctx.fillStyle=label.color;ctx.fillText(label.value,label.p.x,label.p.y);}
}
function resize(){const rect=canvas.getBoundingClientRect();width=rect.width;height=rect.height;const ratio=window.devicePixelRatio||1;canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);draw();}
function stop(){running=false;cancelAnimationFrame(animation);lastTime=null;$('pause').disabled=true;}
function clearRoute(){requestVersion++;stop();result=null;progress=0;walker=null;$('play').disabled=true;$('response').textContent='';$('steps').replaceChildren();$('metrics').textContent='경로를 다시 계산해주세요.';draw();}
async function calculate(){
  if(operatorBusy)return;
  const origin=$('origin').value,destination=$('destination').value;clearRoute();const version=requestVersion;
  $('calculate').disabled=true;status('경로를 계산하고 있습니다.');const start=performance.now();
  try{await api('/qr/'+encodeURIComponent(origin));const data=await api('/route?'+new URLSearchParams({from:origin,to:destination}));if(version!==requestVersion)return;
    if(!data||data.from!==origin||data.to_slot!==destination||!Number.isFinite(data.distance_m)||data.distance_m<0||!Array.isArray(data.path)||!data.path.length||data.path.some(p=>!p||!Number.isFinite(p.x)||!Number.isFinite(p.y)||!nodes[p.node])||!Array.isArray(data.steps)||data.steps.some(s=>typeof s!=='string'))throw Error('경로 응답이 올바르지 않습니다. 다시 검색해주세요.');
    result=data;walker=data.path[0];$('metrics').textContent=`${data.distance_m}m · API 요청 ${(performance.now()-start).toFixed(1)}ms`;
    $('steps').replaceChildren(...data.steps.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));
    $('response').textContent=JSON.stringify(data,null,2);$('play').disabled=false;$('play').textContent='이동 재생';status('경로가 준비되었습니다.');draw();
  }catch(error){if(version===requestVersion)status(error.message,true);}finally{$('calculate').disabled=operatorBusy;}
}
function tick(time){if(!running||!result)return;if(lastTime!==null)progress+=(time-lastTime)/1000*2;lastTime=time;
  let remaining=progress,done=true;walker=result.path.at(-1);
  for(let i=1;i<result.path.length;i++){const a=result.path[i-1],b=result.path[i],length=Math.hypot(b.x-a.x,b.y-a.y);if(remaining<length){const t=length?remaining/length:0;walker={x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t};done=false;break;}remaining-=length;}
  draw();if(done){stop();progress=0;$('play').textContent='다시 재생';status('도착했습니다.');}else animation=requestAnimationFrame(tick);
}
function dimensions(){const cm=Number($('boardWidth').value);if(!Number.isFinite(cm)||cm<22||cm>500){$('dimensions').textContent='가로 크기를 22~500cm 사이로 입력해주세요.';$('export').disabled=true;return null;}
  $('export').disabled=false;const ratio=cm/layout.board.width;const p=map.slots[0].polygon,slotW=Math.abs(p[1][0]-p[0][0]),slotD=Math.abs(p[2][1]-p[1][1]);
  $('dimensions').textContent=`보드 ${cm.toFixed(1)} × ${(layout.board.depth*ratio).toFixed(1)}cm / 주차칸 ${ (slotW*ratio).toFixed(1)} × ${(slotD*ratio).toFixed(1)}cm / 가운데 통로 ${(layout.aisle.depth*ratio).toFixed(1)}cm`;
  return ratio;
}
function escapeXml(value){return String(value).replace(/[<>&"']/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&apos;'}[c]));}
function exportPlan(){const ratio=dimensions();if(ratio===null)return;const b=layout.board;
  const pieces=[`<svg xmlns="http://www.w3.org/2000/svg" width="${b.width*ratio}cm" height="${b.depth*ratio}cm" viewBox="${b.x} ${b.y} ${b.width} ${b.depth}">`,`<rect x="${b.x}" y="${b.y}" width="${b.width}" height="${b.depth}" fill="#f3f1e5"/>`];
  for(const edge of map.edges){const a=nodes[edge.from_node],c=nodes[edge.to_node];pieces.push(`<line x1="${a.x}" y1="${a.y}" x2="${c.x}" y2="${c.y}" stroke="#8eab98" stroke-width=".06"/>`);}
  for(const slot of map.slots){const p=slot.polygon;pieces.push(`<polygon points="${p.map(v=>v.join(',')).join(' ')}" fill="white" stroke="#4c6652" stroke-width=".04"/><text x="${(p[0][0]+p[1][0])/2}" y="${(p[0][1]+p[2][1])/2}" text-anchor="middle" font-size=".3">${escapeXml(slot.name)}</text>`);}
  for(const qr of qrs){const n=nodes[qr.node_id];pieces.push(`<circle cx="${n.x}" cy="${n.y}" r=".2" fill="#2b8a61"/><text x="${n.x}" y="${n.y-.4}" text-anchor="middle" font-size=".25">${escapeXml(qr.location_id)}</text>`);}
  for(const camera of layout.camera_mounts)pieces.push(`<circle cx="${camera.x}" cy="${camera.y}" r=".12" fill="#4e82ab"/><text x="${camera.x}" y="${camera.y+.4}" text-anchor="middle" font-size=".2">${escapeXml(camera.camera_id)}</text>`);
  pieces.push(`<text x="${b.x+.2}" y="${b.y+.4}" font-size=".22">PROTOTYPE / ${(b.width*ratio).toFixed(1)} x ${(b.depth*ratio).toFixed(1)} cm / CAMERA POSITIONS UNVERIFIED</text></svg>`);
  const url=URL.createObjectURL(new Blob(pieces,{type:'image/svg+xml;charset=utf-8'}));const anchor=document.createElement('a');anchor.href=url;anchor.download='SPASIBA-model-layout.svg';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);status('제작 검토용 평면도를 저장했습니다. 출력 시 실제 크기 설정을 확인하세요.');
}
function setView(top){flat=top;angle=top?0:-.28;elevation=top?Math.PI/2:.92;zoom=1;$('view3d').setAttribute('aria-pressed',String(!top));$('view2d').setAttribute('aria-pressed',String(top));draw();}
let drag;
canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointermove',e=>{if(!drag||flat)return;angle+=(e.clientX-drag.x)*.008;elevation=Math.max(.25,Math.min(1.48,elevation+(e.clientY-drag.y)*.006));drag={x:e.clientX,y:e.clientY};draw();});
for(const event of ['pointerup','pointercancel'])canvas.addEventListener(event,()=>drag=null);
canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.5,Math.min(2.3,zoom*Math.exp(-e.deltaY*.001)));draw();},{passive:false});
canvas.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-'].includes(e.key))return;e.preventDefault();if(e.key==='+')zoom=Math.min(2.3,zoom+.1);else if(e.key==='-')zoom=Math.max(.5,zoom-.1);else if(!flat){if(e.key==='ArrowLeft')angle-=.1;if(e.key==='ArrowRight')angle+=.1;if(e.key==='ArrowUp')elevation=Math.min(1.48,elevation+.1);if(e.key==='ArrowDown')elevation=Math.max(.25,elevation-.1);}draw();});
$('view3d').onclick=()=>setView(false);$('view2d').onclick=()=>setView(true);$('reset').onclick=()=>setView(flat);
$('calculate').onclick=calculate;$('play').onclick=()=>{if(!result||running)return;running=true;lastTime=null;$('pause').disabled=false;$('play').textContent='재생 중';animation=requestAnimationFrame(tick);};
$('pause').onclick=()=>{stop();$('play').textContent='이어서 재생';status('이동을 일시정지했습니다.');};
for(const id of ['origin','destination'])$(id).onchange=()=>{clearRoute();updateQrLink();status('선택한 위치로 경로를 계산해주세요.');};
$('searchPlate').oninput=()=>{clearRoute();status('차량번호가 변경되었습니다. 다시 검색해주세요.');};
function updateQrLink(){$('qrLink').href='/simulator?'+new URLSearchParams({location_id:$('origin').value});}
async function refreshEntries(){if(!demoEnabled)return;const entries=await api('/entries?state=ACTIVE');occupied.clear();for(const entry of entries)if(entry.slot_id)occupied.add(entry.slot_id);for(const [slotId,input] of occupancyInputs)input.checked=occupied.has(slotId);$('entries').replaceChildren(...entries.map(entry=>{const li=document.createElement('li');li.textContent=entry.plate_number+' · '+(entry.slot_id||'입차 완료 / 위치 확인 중');return li;}));draw();}
async function operatorAction(button,action){if(operatorBusy)return;operatorBusy=true;for(const id of ['enterVehicle','parkVehicle','exitVehicle','searchVehicle','calculate'])$(id).disabled=true;try{clearRoute();const message=await action();await refreshEntries();$('operatorStatus').textContent=message;}catch(error){$('operatorStatus').textContent=error.message;}finally{clearRoute();operatorBusy=false;for(const id of ['enterVehicle','parkVehicle','exitVehicle','searchVehicle'])$(id).disabled=!demoEnabled;$('calculate').disabled=false;status('차량 상태를 다시 검색해주세요. 요청 결과가 불확실하면 입차 목록을 확인하세요.');}}
$('enterVehicle').onclick=()=>operatorAction($('enterVehicle'),async()=>{const entry=await post('/entries',{plate_number:$('entryPlate').value});$('observedPlate').value=entry.plate_number;$('searchPlate').value=entry.plate_number;return entry.plate_number+' 입차 기록을 저장했습니다.';});
$('parkVehicle').onclick=()=>operatorAction($('parkVehicle'),async()=>{const slot=map.slots.find(s=>s.slot_id===$('destination').value);const event=await post('/simulator/events',{event_id:crypto.randomUUID(),plate_number:$('observedPlate').value,camera_id:slot.camera_id,zone_id:slot.zone_id,slot_id:slot.slot_id,recognized_at:new Date().toISOString(),votes:5,frames:7,kind:'confirm'});return event.status==='CONFIRMED'?'주차 위치 확정 · '+slot.name+(event.review_recommended?' / 한 글자 보정, 검토 권장':''):'관측 처리: '+event.status;});
$('exitVehicle').onclick=()=>operatorAction($('exitVehicle'),async()=>{await post('/exits',{plate_number:$('entryPlate').value});return '출차 처리했습니다. 이후 검색은 기록 없음으로 표시됩니다.';});
$('searchVehicle').onclick=async()=>{if(operatorBusy)return;clearRoute();const version=requestVersion;$('searchVehicle').disabled=true;status('차량 위치를 검색하고 있습니다.');try{const vehicle=await api('/vehicles/'+encodeURIComponent($('searchPlate').value)+'/last-location');if(version!==requestVersion)return;if(vehicle.status==='PENDING'){status(vehicle.message||'주차 위치를 확인하고 있습니다.');$('metrics').textContent='위치 확인 중';return;}if(vehicle.status!=='CONFIRMED'||!map.slots.some(s=>s.slot_id===vehicle.slot_id))throw Error('안내 가능한 주차면이 없습니다.');$('destination').value=vehicle.slot_id;await calculate();}catch(error){if(version===requestVersion){status(error.message,true);$('metrics').textContent='경로 안내 대기';}}finally{$('searchVehicle').disabled=operatorBusy;}};
$('boardWidth').oninput=()=>{if(layout)dimensions();};$('showCameras').onchange=draw;$('export').onclick=exportPlan;
new ResizeObserver(resize).observe(canvas);
(async()=>{try{const [data,meta]=await Promise.all([api('/map?floor=B2'),api('/simulator/layout')]);map=data;layout=meta.layout;qrs=meta.qr_locations;demoEnabled=!!meta.demo_enabled;nodes=Object.fromEntries(map.nodes.map(n=>[n.node_id,n]));
  for(const qr of qrs){const option=new Option(qr.name,qr.location_id);$('origin').add(option);}
  for(const slot of map.slots){$('destination').add(new Option(slot.name,slot.slot_id));const label=document.createElement('label');label.className='check';const input=document.createElement('input');input.type='checkbox';input.checked=occupied.has(slot.slot_id);input.disabled=demoEnabled;occupancyInputs.set(slot.slot_id,input);input.onchange=()=>{input.checked?occupied.add(slot.slot_id):occupied.delete(slot.slot_id);draw();};label.append(input,document.createTextNode(slot.name));$('occupancy').append(label);}
  $('destination').value='B2-A-03';const locationId=new URLSearchParams(window.location.search).get('location_id');if(locationId&&!qrs.some(q=>q.location_id===locationId))throw Error('QR 위치가 없습니다. QR을 다시 스캔해주세요.');if(locationId)$('origin').value=locationId;updateQrLink();dimensions();resize();$('calculate').disabled=false;
  $('searchVehicle').disabled=!demoEnabled;for(const id of ['enterVehicle','parkVehicle','exitVehicle'])$(id).disabled=!demoEnabled;
  if(demoEnabled){$('demoNotice').textContent='로컬 전체 시연 · 카메라 인식 결과를 수동 입력';await refreshEntries();status('입차 기록을 저장한 뒤 주차 관측을 전송하고, 차량번호로 검색하세요.');}else{status('지도 실험 모드입니다. 전체 흐름은 demo_app으로 실행하세요.');await calculate();}
}catch(error){status('지도를 불러오지 못했습니다: '+error.message,true);}})();
