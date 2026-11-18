// Script-level interaction tests with DOM/Canvas doubles; not a browser visual test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const data=JSON.parse(fs.readFileSync('map/b2.json','utf8'));
class Element {
  constructor(){this.value='';this.children=[];this.disabled=false;this.checked=true;this.listeners={};this.attrs={};this.textContent='';}
  add(e){this.children.push(e);if(!this.value)this.value=e.value;}
  append(...e){this.children.push(...e);}
  replaceChildren(...e){this.children=e;}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,v){this.listeners[k]=v;}
  getBoundingClientRect(){return {width:850,height:560};}
  setPointerCapture(){}
}
const elements=new Map();let polygons=0,queued=new Map(),nextFrame=0,routeCalls=0,vehicleStatus='PENDING';
const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
get('boardWidth').value='110';get('showCameras').checked=true;
get('scene').getContext=()=>new Proxy({}, {get:(o,k)=>o[k]||((...args)=>{if(['moveTo','lineTo','setTransform'].includes(k))for(const n of args)assert.ok(Number.isFinite(n),'nonfinite drawing coordinate');if(k==='fill')polygons++;}),set:(o,k,v)=>(o[k]=v,true)});
const context={console,document:{getElementById:get,createElement:()=>new Element(),createTextNode:text=>({textContent:text})},
  Option:function(text,value){this.text=text;this.value=value;},ResizeObserver:class{constructor(fn){this.fn=fn;}observe(){this.fn();}},
  window:{devicePixelRatio:1,location:{search:''}},performance:{now:()=>100},URLSearchParams,AbortController,setTimeout,clearTimeout,
  requestAnimationFrame:fn=>{const id=++nextFrame;queued.set(id,fn);return id;},cancelAnimationFrame:id=>queued.delete(id),
  fetch:async url=>{let result;if(url.startsWith('/vehicles/')){if(vehicleStatus==='NOT_FOUND')return {ok:false,json:async()=>({error:{message:'기록 없음'}})};result={status:vehicleStatus,slot_id:'B2-A-03',message:'위치 확인 중'};}else if(url.startsWith('/map?'))result=data;else if(url==='/simulator/layout')result={sample:true,layout:data.demo_layout,qr_locations:data.qr_locations};else if(url.startsWith('/qr/'))result=data.qr_locations[0];else if(url.startsWith('/route?')){routeCalls++;const query=new URLSearchParams(url.split('?')[1]),slot=data.slots.find(s=>s.slot_id===query.get('to'));result={from:query.get('from'),to_slot:slot.slot_id,floor:'B2',distance_m:16,path:[{node:'ENT1',x:0,y:3},{node:'J1',x:3,y:3},{node:'J2',x:7,y:3},{node:'J3',x:11,y:3},{node:'J4',x:15,y:3},{node:slot.node_id,x:15,y:slot.slot_id.includes('-A-')?2:4}],steps:['15m 직진 후 좌회전','1m 직진','도착']};}else throw Error(url);return {ok:true,json:async()=>result};},
};
vm.createContext(context);vm.runInContext(fs.readFileSync('simulator/app.js','utf8'),context);
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function frame(time){const fns=[...queued.values()];queued.clear();for(const fn of fns)fn(time);}
(async()=>{
  await settle();assert.ok(polygons>100);assert.equal(get('play').disabled,false);assert.match(get('metrics').textContent,/16m/);
  assert.match(get('dimensions').textContent,/110.0 × 40.0cm/);
  get('play').onclick();frame(0);frame(1000);assert.equal(get('pause').disabled,false);
  get('pause').onclick();assert.equal(queued.size,0);assert.equal(get('play').textContent,'이어서 재생');
  get('play').onclick();frame(2000);frame(20000);assert.equal(get('status').textContent,'도착했습니다.');
  get('destination').value='B2-B-03';get('destination').onchange();assert.equal(get('play').disabled,true);assert.equal(get('steps').children.length,0);
  await get('calculate').onclick();assert.equal(get('play').disabled,false);
  get('view2d').onclick();assert.equal(get('view2d').attrs['aria-pressed'],'true');
  get('view3d').onclick();assert.equal(get('view3d').attrs['aria-pressed'],'true');
  get('boardWidth').value='0';get('boardWidth').oninput();assert.equal(get('export').disabled,true);
  get('boardWidth').value='88';get('boardWidth').oninput();assert.equal(get('export').disabled,false);assert.match(get('dimensions').textContent,/88.0 × 32.0cm/);
  const before=routeCalls;get('searchPlate').value='12가3456';await get('searchVehicle').onclick();assert.equal(routeCalls,before);assert.equal(get('play').disabled,true);assert.equal(get('metrics').textContent,'위치 확인 중');
  vehicleStatus='NOT_FOUND';await get('searchVehicle').onclick();assert.equal(routeCalls,before);assert.equal(get('play').disabled,true);
  vehicleStatus='CONFIRMED';await get('searchVehicle').onclick();assert.equal(routeCalls,before+1);assert.equal(get('destination').value,'B2-A-03');assert.equal(get('play').disabled,false);
  get('searchPlate').oninput();assert.equal(get('play').disabled,true);
  const originalFetch=context.fetch;let release;
  context.fetch=async(url,options)=>url.startsWith('/vehicles/')?new Promise(resolve=>release=resolve):originalFetch(url,options);
  const oldSearch=get('searchVehicle').onclick();await settle();const oldRouteCount=routeCalls;
  get('searchPlate').value='34나5678';get('searchPlate').oninput();
  release({ok:true,json:async()=>({status:'CONFIRMED',slot_id:'B2-A-03'})});await oldSearch;
  assert.equal(routeCalls,oldRouteCount);assert.equal(get('play').disabled,true);
  context.fetch=async(url,options)=>url.startsWith('/route?')?{ok:true,json:async()=>({from:'QR-B2-ENT1',to_slot:'B2-A-03',distance_m:16,path:[],steps:[]})}:originalFetch(url,options);
  get('destination').value='B2-A-03';await get('calculate').onclick();assert.equal(get('play').disabled,true);assert.match(get('status').textContent,/경로 응답/);
  context.fetch=async()=>{const error=Error('timeout');error.name='AbortError';throw error;};
  await get('searchVehicle').onclick();assert.equal(get('searchVehicle').disabled,false);assert.equal(get('play').disabled,true);assert.match(get('status').textContent,/시간이 초과/);
  context.fetch=async()=>({ok:true,json:async()=>{throw Error('invalid json');}});
  await get('searchVehicle').onclick();assert.equal(get('play').disabled,true);assert.match(get('status').textContent,/응답 형식/);
  context.fetch=originalFetch;
  context.crypto=require('node:crypto').webcrypto;
  vm.runInContext('demoEnabled=true;vehicleApiEnabled=true;sharedBackend=true;',context);
  let submitted;
  context.fetch=async(url,options)=>{if(url==='/simulator/events'){submitted=JSON.parse(options.body);return {ok:true,json:async()=>({status:'assigned'})};}if(url.startsWith('/entries?'))return {ok:true,json:async()=>[]};return originalFetch(url,options);};
  get('observedPlate').value='12가3456';get('destination').value='B2-A-03';await get('parkVehicle').onclick();
  assert.ok(submitted.event_id);assert.equal(submitted.camera_id,'CAM-B2-01');assert.ok(!('zone_id' in submitted));
  assert.match(get('operatorStatus').textContent,/주차 위치 확정/);
  console.log('PASS: 3D/playback, PENDING/404 gates, confirmed route, stale response ignored, malformed path/JSON and timeout recovery');
})().catch(error=>{console.error(error);process.exitCode=1;});
