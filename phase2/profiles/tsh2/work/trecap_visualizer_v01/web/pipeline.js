/* Physical job stages drive this view. Animation never invents completion. */
(function(root,factory){
 const api=factory();
 if(typeof module==="object"&&module.exports)module.exports=api;
 else root.TRecapPipeline=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
 "use strict";
 const stages=["prepare","send","board","receive","verify","consumer","ready"];
 const phaseStage={requesting:"prepare",queued:"prepare",preparing:"prepare",admission:"prepare",starting:"prepare",sending:"send",processing:"board",receiving:"receive",verifying:"verify",reference:"verify",consumer:"consumer",rendering:"ready",presentation_failed:"ready",complete:"ready",cached:"prepare"};
 const titles={requesting:"Requesting a board run",queued:"Waiting for the board",preparing:"Preparing the audio",admission:"Checking the board",starting:"Opening the board service",sending:"Laptop to board",processing:"Board processing",receiving:"Board to laptop",verifying:"Checking the completed capture",reference:"Verifying the FPGA output",consumer:"Laptop analysis",rendering:"Preparing playback and charts",presentation_failed:"Capture saved; browser loading failed",complete:"Processing complete",cached:"Loading a saved capture",failed:"Processing stopped",superseded:"Queued request replaced",unknown:"Waiting for job telemetry"};
 const clean=value=>String(value??"").replace(/[\u2013\u2014]/g," - ");
 const terminal=job=>["complete","failed","superseded"].includes(job?.status);
 const labelThreshold=n=>Number(n)===0?"Off":`10^${Math.round(Math.log10(Number(n)))}`;
 function projectJob(job,options={}){
  const events=Array.isArray(job.events)?job.events:[],p=job.progress||{};
  const phase=options.presentationError?"presentation_failed":options.rendering?"rendering":p.phase||(terminal(job)?job.status:job.status==="queued"?"queued":"unknown");
  const pass=p.pass_kind||"selected";
  const relevant=events.filter(e=>(e.pass_kind||"selected")===pass);
  const states=Object.fromEntries(stages.map(k=>[k,"waiting"]));
  const observed=[];
  for(const e of relevant){const stage=phaseStage[e.phase];if(stage&&e.phase!=="queued"&&e.phase!=="requesting"&&!observed.includes(stage))observed.push(stage);}
  for(const stage of observed)states[stage]="done";
  const current=phaseStage[phase];
  const status=(phase==="failed"||phase==="presentation_failed")?"error":phase==="superseded"?"superseded":phase==="complete"?"complete":phase==="queued"?"queued":"active";
  if(events.some(e=>e.phase==="cached")&&!events.some(e=>e.phase==="sending")){for(const key of ["send","board","receive","verify"])states[key]="skipped";}
  if(phase==="presentation_failed")states.ready="error";
  else if(phase==="failed"){
   const last=[...relevant].reverse().find(e=>phaseStage[e.phase]);
   if(last)states[phaseStage[last.phase]]="error";
  }else if(phase==="queued"||phase==="requesting")states.prepare="waiting";
  else if(current)states[current]=phase==="complete"?"done":"active";
  return {phase,pass,status,states,title:titles[phase]||titles.unknown,
   message:clean(options.presentationError|| (options.rendering?"The capture is verified. Loading its audio and synchronized plots in this browser.":p.message||job.message||"Waiting for the next observed stage.")),
   threshold:p.threshold??job.threshold,events,progress:p};
 }
 function acceptObservation(previous,next){
  if(!previous)return true;
  if(previous.job_id===next.job_id){
   if(terminal(previous)&&!terminal(next))return false;
   const a=previous.events?.at(-1)?.sequence??-1,b=next.events?.at(-1)?.sequence??-1;
   return b>=a;
  }
  if(next.status==="queued"&&!terminal(previous))return false;
  if(previous.status==="queued"&&next.status==="running")return true;
  return (next.created_at||0)>=(previous.created_at||0);
 }
 class View{
  constructor(doc){this.doc=doc;this.job=null;this.rendering=false;this.pending=null;this.disconnected=false;this.clockBase=0;this.clockAnchor=performance.now();this.presentationError=null;this.timer=setInterval(()=>this.clock(),250);}
  el(id){return this.doc.getElementById(id);}
  text(id,value){const el=this.el(id);if(el)el.textContent=clean(value);}
  running(){return !!this.job&&(!terminal(this.job)||this.rendering)&&!this.disconnected;}
  idle(source,threshold){if(this.job)return;this.text("flow-source",source||"Choose a sound");this.text("flow-threshold",`Threshold ${labelThreshold(threshold)}`);}
  begin(sourceId,source,threshold){
   if(this.running()){this.text("flow-queue",`Requesting next: ${source} · ${labelThreshold(threshold)}`);return;}
   this.job=null;this.show({job_id:"requesting",source_id:sourceId,threshold,created_at:Date.now()/1000,status:"running",progress:{phase:"requesting",pass_kind:"selected",threshold,message:"Sending your request. Current audio playback remains available."},events:[]},{source});
  }
  show(job,options={}){
   if(this.job?.job_id!=="requesting"&&!acceptObservation(this.job,job))return false;
   const isNew=this.job?.job_id!==job.job_id,previousSequence=isNew?Infinity:this.job?.events?.at(-1)?.sequence||0;
   if(isNew){this.rendering=false;this.presentationError=null;}
   if(isNew||this.job?.events?.at(-1)?.sequence!==job.events?.at(-1)?.sequence){this.clockBase=Number(job.progress?.elapsed_ms||0);this.clockAnchor=performance.now();}
   this.job=job;this.disconnected=false;
   if(Object.prototype.hasOwnProperty.call(options,"rendering"))this.rendering=options.rendering;
   if(Object.prototype.hasOwnProperty.call(options,"presentationError"))this.presentationError=options.presentationError;
   const model=projectJob(job,{rendering:this.rendering,presentationError:this.presentationError}),panel=this.el("processing-flow");
   if(!panel)return false;
   panel.dataset.status=model.status;panel.dataset.phase=model.phase;
   panel.setAttribute("aria-busy",String(this.running()));
   this.text("flow-status",model.title);this.text("flow-detail",model.message);
   this.text("flow-source",options.source||job.source_id);
   this.text("flow-threshold",`Threshold ${labelThreshold(model.threshold)}`);
   this.text("flow-pass",model.pass==="baseline"?"Unthresholded reference capture":"Selected threshold capture");
   this.text("flow-observation","Live job stages. Motion inside the board illustrates the pipeline; individual FFT and IFFT times are not measured here.");
   for(const node of this.doc.querySelectorAll("[data-flow-stage], [data-flow-part]")){
    const stage=node.dataset.flowStage||node.dataset.flowPart;
    node.dataset.state=model.states[stage]||"waiting";
    if(node.dataset.flowStage){
     if(model.states[stage]==="active")node.setAttribute("aria-current","step");else node.removeAttribute("aria-current");
     const status=node.querySelector("[data-stage-state]");if(status)status.textContent={waiting:"Pending",active:"In progress",done:"Done",error:"Stopped",skipped:"Not run"}[model.states[stage]];
    }
   }
   for(const [phase,part] of [["sending","send"],["receiving","receive"]]){
    const event=[...model.events].reverse().find(e=>e.phase===phase&&e.pass_kind===model.pass);
    if(event?.sequence>previousSequence&&model.status==="active"&&model.states[part]==="done"){
     const node=this.doc.querySelector(`[data-flow-part="${part}"]`);
     if(node){node.classList.add("transfer-confirmed");clearTimeout(node.transferTimer);node.transferTimer=setTimeout(()=>node.classList.remove("transfer-confirmed"),950);}
    }
   }
   const transfer=[...model.events].reverse().find(e=>e.pass_kind===model.pass&&e.phase==="receiving"&&Number.isFinite(e.total_bytes));
   const total=Number(model.progress.total_bytes),done=Number(model.progress.completed_bytes);
   this.text("flow-transfer",Number.isFinite(total)&&total>0?`${(done/1e6).toFixed(2)} / ${(total/1e6).toFixed(2)} MB ${model.phase==="sending"?"submitted to socket":"received"}`:transfer?`Output received: ${(transfer.completed_bytes/1e6).toFixed(2)} / ${(transfer.total_bytes/1e6).toFixed(2)} MB. Includes reconstructed audio and spectral packets.`:model.phase==="processing"?"Awaiting the board's completion reply":"");
   this.history(model.events);this.clock();return true;
  }
  history(events){
   const target=this.el("flow-events");if(!target)return;
   const compact=[];
   for(const event of events){
    const last=compact.at(-1);
    if(last&&last.phase===event.phase&&last.pass_kind===event.pass_kind)compact[compact.length-1]=event;
    else compact.push(event);
   }
   const signature=JSON.stringify(compact);if(signature===this.historySignature)return;this.historySignature=signature;
   target.replaceChildren();
   for(const event of compact){
    const row=this.doc.createElement("li"),time=this.doc.createElement("time"),body=this.doc.createElement("span");
    time.textContent=`${(Number(event.elapsed_ms||0)/1000).toFixed(2)} s`;
    body.textContent=clean(`${event.pass_kind==="baseline"?"Reference":"Selected"} · ${titles[event.phase]||event.phase}: ${event.message||""}`);
    row.append(time,body);target.append(row);
   }
  }
  queue(job,source){this.pending=job;this.text("flow-queue",job?`Next in queue: ${source||job.source_id} · ${labelThreshold(job.threshold)}`:"");}
  connectionLost(detail){
   if(!this.job||terminal(this.job))return;
   this.disconnected=true;const panel=this.el("processing-flow");panel.dataset.status="unknown";
   this.text("flow-status","Live status unavailable");this.text("flow-detail",`${detail} Last observed stage is retained. The board may still be running.`);
  }
  reject(detail){
   const job=this.job||{job_id:"requesting",created_at:Date.now()/1000,events:[]};
   this.show({...job,status:"failed",finished_at:Date.now()/1000,progress:{...(job.progress||{}),phase:"failed",message:detail}});
  }
  clock(){
   if(!this.job)return;
   const elapsed=this.disconnected||terminal(this.job)&&!this.rendering?Number(this.job.progress?.elapsed_ms||0):this.clockBase+performance.now()-this.clockAnchor;
   this.text("flow-elapsed",`${Math.max(0,elapsed/1000).toFixed(1)} s elapsed`);
  }
 }
 return {View,projectJob,acceptObservation,stages};
});
