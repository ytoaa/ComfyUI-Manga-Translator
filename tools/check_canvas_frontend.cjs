/* Executable event/queue contract tests, with no browser or model dependencies. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '../web/workflow_execution.js'), 'utf8').replace(/^import .*;$/gm, '');

async function fixture(options = {}) {
    const listeners = new Map(), queued = [], requested = [];
    const preview = { id: 42, type: 'PreviewAny', onExecuted(value) { this.output = value; } };
    const nodes = new Map([[42, preview], [8, { id: 8, title: 'OCR 실행' }]]);
    const app = {
        graph: { links: {1:{origin_id:1, origin_slot:2, target_id:42}}, getNodeById(id) { return nodes.get(Number(id)); } },
        registerExtension(ext) { this.extension = ext; },
        async queuePrompt(number, batch) {
            queued.push({number, batch, marker: JSON.parse(JSON.stringify(nodes.get(1).properties.manga_canvas_run))});
            return true;
        },
    };
    const api = {
        addEventListener(name, callback) {
            if (!listeners.has(name)) listeners.set(name, []);
            listeners.get(name).push(callback);
        },
        async fetchApi(url, request) {
            requested.push({url, body:JSON.parse(request.body)});
            if (url.endsWith('/resolve') && options.lostReply) throw new Error('connection lost');
            return { ok:true, async json() { return url.endsWith('/pause')
                ? {status:'paused',message:'중지',counts:{}}
                : {pending:false, continue:options.continues !== false, report:{status:'awaiting_canvas',message:'다음 페이지',counts:{completed:1}}}; } };
        },
    };
    vm.runInNewContext(code, {app, api, console, setTimeout, document:{createElement(){return {style:{},value:''};}}});
    class Node {
        constructor() {
            this.id=1; this.type=this.comfyClass='MangaWorkflowInput'; this.properties={};
            this.widgets=Object.entries({input_mode:'폴더 프로젝트',project_name:'book',input_folder:'book',action:'시작·재개'})
                .map(([name,value])=>({name,value}));
        }
        addWidget(type,name,value,callback,options) { const w={type,name,value,callback,options};this.widgets.push(w);return w; }
        addDOMWidget(name,type,element,options) { const w={name,type,element,options};this.widgets.push(w);return w; }
        setDirtyCanvas() {}
    }
    await app.extension.beforeRegisterNodeDef(Node,{name:'MangaWorkflowInput'});
    const node=new Node(); nodes.set(1,node);node.onNodeCreated();
    const event=(name,detail)=>{for(const callback of listeners.get(name)||[]) callback({detail});};
    const ticket={run_id:'run-1',prompt_id:'prompt-1',project_name:'book',source_node:'1',input_folder:'book',
                  relative_path:'1.png',index:1,total:2,report:{status:'running',current_page:'1.png',message:'페이지 처리'}};
    event('execution_start',{prompt_id:'prompt-1'});
    if (!options.delayedTicket) event('executed',{node:'1',output:{manga_workflow:[ticket]}});
    return {node,app,api,event,queued,requested,preview,ticket};
}
const flush = async () => { for(let i=0;i<8;i++) await new Promise(resolve=>setImmediate(resolve)); };
(async()=>{
    const first=await fixture();
    first.event('executing','8');
    assert.match(first.node.mangaStatus.value,/OCR 실행/); // Real frontend emits a node string.
    first.event('progress',{prompt_id:'prompt-1',node:'8',value:2,max:8});
    assert.match(first.node.mangaStatus.value,/2\/8/);
    const statusWidget=first.node.widgets.find(w=>w.type==='manga_status');
    assert.equal(statusWidget.options.getMinHeight(),106);assert.equal(statusWidget.options.getMaxHeight(),106);
    assert.equal(statusWidget.computeSize(600)[0],0);assert.match(first.node.mangaStatus.style.cssText,/max-width:100%/);
    assert.equal(first.queued.length,0);
    first.event('execution_success',{prompt_id:'prompt-1'});await flush();
    assert.equal(first.queued.length,1);
    assert.deepEqual(first.queued[0],{number:0,batch:1,marker:{run_id:'run-1',source_node:'1'}});
    assert.equal(first.node.properties.manga_canvas_run,undefined);
    first.event('execution_success',{prompt_id:'prompt-1'});await flush();
    assert.equal(first.queued.length,1);
    assert.match(first.preview.output.text[0],/completed/);
    for(const w of first.node.widgets.filter(w=>w.type==='manga_status'||w.type==='button')) {
        assert.equal(w.serialize,false);assert.equal(w.options.serialize,false);
    }
    const interrupted=await fixture();
    interrupted.event('execution_interrupted',{prompt_id:'prompt-1'});await flush();
    assert.equal(interrupted.queued.length,0);
    const done=await fixture({continues:false});done.event('execution_success',{prompt_id:'prompt-1'});await flush();
    assert.equal(done.queued.length,0);
    const changed=await fixture();changed.node.widgets.find(w=>w.name==='project_name').value='other-book';
    changed.event('execution_success',{prompt_id:'prompt-1'});await flush();
    assert.equal(changed.queued.length,0);assert.ok(changed.requested.some(r=>r.url.endsWith('/pause')));
    const disconnected=await fixture();disconnected.event('reconnecting',{});
    disconnected.event('execution_success',{prompt_id:'prompt-1'});await flush();
    assert.equal(disconnected.queued.length,0);
    const foreign=await fixture();foreign.event('execution_success',{prompt_id:'someone-else'});await flush();
    assert.equal(foreign.requested.length,0);assert.equal(foreign.queued.length,0);
    const lost=await fixture({lostReply:true});lost.event('execution_success',{prompt_id:'prompt-1'});await flush();
    assert.equal(lost.queued.length,0);assert.match(lost.node.mangaStatus.value,/connection lost/);
    const stop=await fixture();
    await stop.node.widgets.find(w=>w.type==='button').callback();
    stop.event('execution_success',{prompt_id:'prompt-1'});await flush();assert.equal(stop.queued.length,0);
    assert.ok(stop.requested.every(r=>!r.url.includes('/interrupt'))); // Never cancel foreign core jobs.
    const busy=await fixture();busy.app.processingQueue=true;
    busy.event('execution_success',{prompt_id:'prompt-1'});await flush();
    assert.equal(busy.queued.length,0);
    busy.app.processingQueue=false;await new Promise(resolve=>setTimeout(resolve,140));
    assert.equal(busy.queued.length,1);assert.equal(busy.node.properties.manga_canvas_run,undefined);
    const busyStop=await fixture();busyStop.app.processingQueue=true;
    busyStop.event('execution_success',{prompt_id:'prompt-1'});await flush();
    await busyStop.node.widgets.find(w=>w.type==='button').callback();
    busyStop.app.processingQueue=false;await new Promise(resolve=>setTimeout(resolve,140));
    assert.equal(busyStop.queued.length,0);
    const early=await fixture({delayedTicket:true});
    await early.node.widgets.find(w=>w.type==='button').callback();
    early.event('executed',{node:'1',output:{manga_workflow:[early.ticket]}});await flush();
    early.event('execution_success',{prompt_id:'prompt-1'});await flush();
    assert.equal(early.queued.length,0);assert.ok(early.requested.some(r=>r.url.endsWith('/pause')));
    console.log('PASS: native canvas progress, prefix-free control widgets, one normal queue per page, stop/disconnect/error/duplicate guards');
})().catch(error=>{console.error(error);process.exitCode=1;});
