/* Execute the actual folder button with controlled picker and HTTP boundaries. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '../web/folder_upload.js'), 'utf8').replace(/^import .*;$/gm, '');
const flush = async () => { for(let i=0;i<10;i++) await new Promise(setImmediate); };
const files = [{name:'1.png', webkitRelativePath:'book/1.png'}, {name:'2.png', webkitRelativePath:'book/chapter/2.png'}];
const never = () => new Promise(() => {});
const ok = request => ({ok:true, status:200, async json(){ return {
    type:'input', name:request.body.get('image').name, subfolder:request.body.get('subfolder')}; }});

async function fixture(handler = (_, request) => ok(request), chosen = files) {
    const pickers = [], requests = [], alerts = [], timers = new Set();
    class Form { constructor(){this.data = new Map();} append(k,v){this.data.set(k,v);} get(k){return this.data.get(k);} }
    const app = {registerExtension(extension){this.extension=extension;}};
    const api = {async fetchApi(url, request){requests.push(request);return handler(url, request);}};
    const document = {createElement(){const input={files:chosen,setAttribute(){},click(){pickers.push(this);}};return input;}};
    const schedule = (callback, ms) => {
        // The button-label reset is irrelevant; advance the network deadline.
        const timer={callback,ms};
        timers.add(timer);return timer;
    };
    vm.runInNewContext(code, {app,api,document,FormData:Form,AbortController,
        console:{error(){}},window:{alert(message){alerts.push(message);}},
        setTimeout:schedule,clearTimeout(timer){timers.delete(timer);}});
    class Node {
        constructor(){this.widgets=Object.entries({input_mode:'이미지 한 장',input_folder:'old',project_name:'book_01'}).map(([name,value])=>({name,value}));}
        addWidget(type,name,value,callback,options){const widget={type,name,value,callback,options};this.widgets.push(widget);return widget;}
        setDirtyCanvas(){}
    }
    await app.extension.beforeRegisterNodeDef(Node,{name:'MangaWorkflowInput'});
    const node=new Node();node.onNodeCreated();
    const button=node.widgets.find(w=>w.type==='button');
    return {node,button,pickers,requests,alerts,timers,
        expireNetwork(){for(const timer of [...timers])if(timer.ms>=10000){timers.delete(timer);timer.callback();}},
        value:name=>node.widgets.find(w=>w.name===name).value,
        select:()=>pickers.at(-1).onchange(), start:()=>button.callback()};
}

const cases = [
    ['nested folder success activates input only after all uploads', async()=>{
        const f=await fixture();const task=f.start();f.select();await task;
        assert.equal(f.requests.length,2);assert.equal(f.value('input_mode'),'폴더 프로젝트');
        assert.ok(f.requests[1].body.get('subfolder').endsWith('/book/chapter'));
        assert.equal(f.value('input_folder'),f.requests[0].body.get('subfolder'));
        assert.equal(f.alerts.length,0);assert.equal(f.button.disabled,false);
    }],
    ['double click opens only one picker and uploads once', async()=>{
        const f=await fixture();const one=f.start(),two=f.start();
        assert.equal(f.pickers.length,1);f.select();await Promise.all([one,two]);assert.equal(f.requests.length,2);
    }],
    ['cancel permits later selection', async()=>{
        const f=await fixture();const task=f.start();f.pickers[0].oncancel();await task;
        const second=f.start();f.select();await second;assert.equal(f.requests.length,2);
    }],
    ['failed second upload does not activate partial folder', async()=>{
        let calls=0;
        const f=await fixture((_,request)=>++calls===1?ok(request):{ok:false,status:507,async json(){return {error:'disk full'};}});
        const task=f.start();f.select();await task;
        assert.equal(f.value('input_folder'),'old');assert.equal(f.value('input_mode'),'이미지 한 장');
        assert.match(f.alerts[0],/disk full/);assert.equal(f.button.disabled,false);
    }],
    ...['fetch','body'].map(stage=>[`${stage} stall releases button without activating folder`,async()=>{
        const f=await fixture(()=>stage==='fetch'?never():{ok:true,json:never});
        const task=f.start();f.select();await flush();f.expireNetwork();await flush();
        assert.equal(f.button.disabled,false);assert.equal(f.value('input_folder'),'old');
        assert.match(f.alerts[0],/시간/);assert.ok(f.requests[0].signal.aborted);await task;
    }]),
    ['changed widget values are not overwritten by late upload',async()=>{
        let release;
        const f=await fixture((_,request)=>new Promise(resolve=>{release=()=>resolve(ok(request));}),[files[0]]);
        const task=f.start();f.select();await flush();
        f.node.widgets.find(w=>w.name==='input_folder').value='different-book';release();await task;
        assert.equal(f.value('input_folder'),'different-book');assert.equal(f.value('input_mode'),'이미지 한 장');
        assert.match(f.alerts[0],/설정/);
    }],
    ['unexpected server destination does not activate nonexistent folder',async()=>{
        const f=await fixture(()=>({ok:true,async json(){return {type:'input',name:'other.png',subfolder:'elsewhere'};}}));
        const task=f.start();f.select();await task;
        assert.equal(f.value('input_folder'),'old');assert.equal(f.requests.length,1);assert.equal(f.alerts.length,1);
    }],
    ['unsupported-only folder does not upload',async()=>{
        const f=await fixture(undefined,[{name:'readme.txt',webkitRelativePath:'book/readme.txt'}]);
        const task=f.start();f.select();await task;assert.equal(f.requests.length,0);assert.equal(f.alerts.length,1);
    }],
];
(async()=>{
    let failures=0;
    for(const [name,run] of cases){try{await run();console.log(`PASS: ${name}`);}catch(error){failures++;console.error(`FAIL: ${name}\n${error.message}`);}}
    console.log(`${cases.length-failures} passed, ${failures} failed`);if(failures)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
