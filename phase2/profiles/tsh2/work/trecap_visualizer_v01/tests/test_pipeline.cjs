const test=require('node:test');
const assert=require('node:assert/strict');
const {View,projectJob,acceptObservation}=require('../web/pipeline.js');
function job(phases,{id='a',created=100,status='running',pass='selected'}={}){
 const events=phases.map((phase,index)=>({phase,pass_kind:pass,threshold:1e8,message:phase,sequence:index+1,elapsed_ms:index*100,at:created+index/10}));
 return {job_id:id,created_at:created,status,threshold:1e8,events,progress:events.at(-1)};
}
test('only observed work can be marked complete, never future stages',()=>{
 const model=projectJob(job(['queued','preparing','admission','starting','sending','processing']));
 assert.deepEqual(model.states,{prepare:'done',send:'done',board:'active',receive:'waiting',verify:'waiting',consumer:'waiting',ready:'waiting'});
});
test('no telemetry does not manufacture a board-processing animation',()=>{
 const model=projectJob({status:'running',events:[]});
 assert.equal(model.phase,'unknown');
 assert.ok(Object.values(model.states).every(v=>v==='waiting'));
});
test('a selected capture does not inherit completed stages from the baseline',()=>{
 const baseline=job(['preparing','sending','processing','receiving','reference'],{pass:'baseline'});
 const event={phase:'admission',pass_kind:'selected',threshold:1e8,sequence:6};
 const model=projectJob({...baseline,events:[...baseline.events,event],progress:event});
 assert.equal(model.pass,'selected');
 assert.equal(model.states.prepare,'active');
 for(const key of ['send','board','receive','verify','consumer','ready'])assert.equal(model.states[key],'waiting');
});
test('failure stops at the last observed operation and leaves later work pending',()=>{
 const model=projectJob(job(['preparing','sending','processing','failed'],{status:'failed'}));
 assert.equal(model.status,'error');assert.equal(model.states.board,'error');assert.equal(model.states.send,'done');
 assert.equal(model.states.receive,'waiting');assert.equal(model.states.ready,'waiting');
});
test('a ready server result still shows browser presentation loading separately',()=>{
 const done=job(['preparing','sending','processing','receiving','verifying','reference','consumer','complete'],{status:'complete'});
 assert.equal(projectJob(done,{rendering:true}).states.ready,'active');
 assert.equal(projectJob(done,{rendering:true}).status,'active');
 assert.ok(Object.values(projectJob(done).states).every(v=>v==='done'));
});
test('saved captures never mark hardware stages as executed',()=>{
 const model=projectJob(job(['preparing','cached','consumer']));
 for(const key of ['send','board','receive','verify'])assert.equal(model.states[key],'skipped');
 assert.equal(model.states.ready,'waiting');
 assert.equal(model.states.consumer,'active');
});
test('out-of-order polling cannot rewind a job or replace current active work with a queue',()=>{
 const processing=job(['preparing','sending','processing']);
 assert.equal(acceptObservation(processing,job(['preparing'])),false);
 assert.equal(acceptObservation(processing,job(['queued'],{id:'b',created:101,status:'queued'})),false);
 assert.equal(acceptObservation(job(['complete'],{status:'complete'}),job(['preparing','sending'])),false);
 assert.equal(acceptObservation(job(['queued'],{id:'b',created:101,status:'queued'}),processing),true);
});
test('late completion of an older request cannot overwrite the next running request',()=>{
 assert.equal(acceptObservation(job(['preparing'],{id:'b',created:101}),job(['preparing','complete'],{created:100,status:'complete'})),false);
});

test('browser loading failure does not report audio ready or falsify board success',()=>{
 const complete=job(['preparing','sending','processing','receiving','verifying','consumer','complete'],{status:'complete'});
 const model=projectJob(complete,{presentationError:'Audio decoding failed'});
 assert.equal(model.status,'error');assert.equal(model.states.ready,'error');assert.equal(model.states.board,'done');
 assert.equal(model.message,'Audio decoding failed');
});
test('terminal elapsed time freezes on measured duration even without finished_at',()=>{
 const text={textContent:''},view=new View({getElementById:()=>text});
 try{
  view.job={...job(['complete'],{status:'complete'}),progress:{phase:'complete',elapsed_ms:1234}};
  view.clockBase=90000;view.clockAnchor=-999999;
  view.clock();assert.equal(text.textContent,'1.2 s elapsed');
  view.clock();assert.equal(text.textContent,'1.2 s elapsed');
 }finally{clearInterval(view.timer);}
});
