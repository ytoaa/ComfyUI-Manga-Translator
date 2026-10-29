/* Fault-injected event ordering and stalled HTTP; no browser/model claims. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '../web/workflow_execution.js'), 'utf8').replace(/^import .*;$/gm, '');
const flush = async () => { for (let i = 0; i < 16; i++) await new Promise(setImmediate); };
const never = () => new Promise(() => {});

async function fixture(handler) {
    const listeners = new Map(), requests = [], queued = [], timers = new Set();
    const app = {
        graph: { links: {}, getNodeById(id) { return String(id) === '1' ? node : null; } },
        registerExtension(extension) { this.extension = extension; },
        async queuePrompt() { queued.push(true); return true; },
    };
    const api = {
        addEventListener(name, callback) { listeners.set(name, callback); },
        async fetchApi(url, options) {
            requests.push({url, options});
            return handler(url, options);
        },
    };
    // Advance only the HTTP deadline; retain real asynchronous event ordering.
    const schedule = (callback, ms) => {
        const timer = {callback,ms};
        timers.add(timer); return timer;
    };
    const cancel = timer => { timers.delete(timer); };
    vm.runInNewContext(code, {app, api, console, AbortController, setTimeout:schedule, clearTimeout:cancel,
        document:{createElement(){ return {style:{}, value:''}; }}});
    class Node {
        constructor() {
            this.id = 1; this.type = this.comfyClass = 'MangaWorkflowInput'; this.properties = {};
            this.widgets = Object.entries({input_mode:'폴더 프로젝트', project_name:'book', input_folder:'book', action:'시작·재개'})
                .map(([name, value]) => ({name, value}));
        }
        addDOMWidget(name, type, element, options) { return {name, type, element, options}; }
        addWidget(type, name, value, callback, options) {
            const widget = {type, name, value, callback, options}; this.widgets.push(widget); return widget;
        }
        setDirtyCanvas() {}
    }
    await app.extension.beforeRegisterNodeDef(Node, {name:'MangaWorkflowInput'});
    const node = new Node(); node.onNodeCreated();
    const event = (name, detail) => listeners.get(name)?.({detail});
    const ticket = {run_id:'run-1', prompt_id:'prompt-1', project_name:'book', source_node:'1', input_folder:'book',
        relative_path:'1.png', index:1, total:2, report:{status:'running'}};
    const announce = () => event('executed', {node:'1', output:{manga_workflow:[ticket]}});
    announce();
    return {node, app, requests, queued, timers, event, announce, ticket,
        expireNetwork(){for(const timer of [...timers])if(timer.ms>=10000){timers.delete(timer);timer.callback();}},
        finish:() => event('execution_success', {prompt_id:ticket.prompt_id}),
        stop:() => node.widgets.find(w => w.type === 'button').callback()};
}
const response = body => ({ok:true, status:200, async json() { return body; }});
const resolved = () => response({pending:false, continue:true, report:{status:'awaiting_canvas'}});
const paused = () => response({status:'paused'});

const cases = [
    ['HTTP fetch stalls', async () => {
        const f = await fixture(url => url.endsWith('/resolve') ? never() : paused());
        f.finish(); await flush(); f.expireNetwork(); await flush();
        assert.match(f.node.mangaStatus.value, /시간|timed out/i);
        assert.equal(f.queued.length, 0); assert.ok(f.requests[0].options.signal.aborted);
        assert.equal(f.timers.size, 0);
    }],
    ['HTTP response body stalls', async () => {
        const f = await fixture(url => url.endsWith('/resolve') ? {ok:true, json:never} : paused());
        f.finish(); await flush(); f.expireNetwork(); await flush();
        assert.match(f.node.mangaStatus.value, /시간|timed out/i);
        assert.equal(f.queued.length, 0); assert.ok(f.requests[0].options.signal.aborted);
        assert.equal(f.timers.size, 0);
    }],
    ['pause stalls after resolve failure', async () => {
        const f = await fixture(url => {
            if (url.endsWith('/resolve')) throw new Error('resolve failed');
            return never();
        });
        f.finish(); await flush(); f.expireNetwork(); await flush();
        assert.match(f.node.mangaStatus.value, /resolve failed/);
        assert.equal(f.queued.length, 0); assert.ok(f.requests[1].options.signal.aborted);
        assert.equal(f.timers.size, 0);
    }],
    ['stop survives duplicated ticket before pause response', async () => {
        let release;
        const f = await fixture(url => url.endsWith('/pause') ? new Promise(resolve => { release = resolve; }) : resolved());
        const stopping = f.stop(); f.announce(); f.finish(); await flush();
        assert.equal(f.queued.length, 0);
        release(paused()); await stopping;
    }],
    ['settled ticket cannot reactivate a finished prompt', async () => {
        const f = await fixture(url => url.endsWith('/pause') ? paused() : response({pending:false, continue:false, report:{status:'completed'}}));
        f.finish(); await flush();
        f.announce(); f.event('reconnecting', {});
        assert.doesNotMatch(f.node.mangaStatus.value, /연결이 끊겼/);
    }],
    ['late resolve does not overwrite changed project status', async () => {
        let release;
        const f = await fixture(url => url.endsWith('/resolve') ? new Promise(resolve => { release = resolve; }) : paused());
        f.finish(); await flush();
        f.node.widgets.find(w => w.name === 'project_name').value = 'new-book';
        f.node.mangaStatus.value = 'new-book status'; release(resolved()); await flush();
        assert.equal(f.node.mangaStatus.value, 'new-book status'); assert.equal(f.queued.length, 0);
    }],
    ['new run owns status and continuation over old reply', async () => {
        let release;
        const f = await fixture(url => url.endsWith('/resolve') ? new Promise(resolve => { release = resolve; }) : paused());
        f.finish(); await flush();
        f.event('executed', {node:'1', output:{manga_workflow:[{...f.ticket, run_id:'run-2', prompt_id:'prompt-2',
            report:{status:'running', message:'new run'}}]}});
        release(resolved()); await flush();
        assert.match(f.node.mangaStatus.value, /new run/); assert.equal(f.queued.length, 0);
    }],
    ['disconnect while resolve is in flight retains recovery message', async () => {
        let release;
        const f = await fixture(() => new Promise(resolve => { release = resolve; }));
        f.finish(); await flush(); f.event('reconnecting', {});
        release(resolved()); await flush();
        assert.match(f.node.mangaStatus.value, /연결이 끊겼/); assert.equal(f.queued.length, 0);
    }],
    ['replayed ticket after disconnect cannot restart continuation', async () => {
        const f = await fixture(url => url.endsWith('/pause') ? paused() : resolved());
        f.event('reconnecting', {}); f.announce(); f.finish(); await flush();
        assert.equal(f.queued.length, 0); assert.equal(f.requests.length, 0);
        assert.match(f.node.mangaStatus.value, /연결이 끊겼/);
    }],
    ['rejected queue restores metadata and pauses exactly once', async () => {
        const f = await fixture(url => url.endsWith('/pause') ? paused() : resolved());
        f.app.queuePrompt = async () => false;
        f.finish(); await flush();
        assert.equal(f.node.properties.manga_canvas_run, undefined);
        assert.match(f.node.mangaStatus.value, /거부/);
        assert.equal(f.requests.filter(r => r.url.endsWith('/pause')).length, 1);
        f.finish(); await flush(); assert.equal(f.requests.length, 2);
    }],
    ...[null, [], {pending:false, continue:'false', report:{}}, {pending:false, continue:true, report:null}].map((body, index) =>
        [`invalid resolve schema ${index}`, async () => {
            const f = await fixture(url => url.endsWith('/resolve') ? response(body) : paused());
            f.finish(); await flush(); assert.equal(f.queued.length, 0);
            assert.match(f.node.mangaStatus.value, /연속 제출 중지/);
        }]),
    ['successful response clears deadline', async () => {
        const f = await fixture(url => url.endsWith('/pause') ? paused() : resolved());
        f.finish(); await flush(); assert.equal(f.queued.length, 1); assert.equal(f.timers.size, 0);
        f.expireNetwork(); await flush(); assert.equal(f.requests.length, 1);
    }],
];
(async () => {
    let failures = 0;
    for (const [name, run] of cases) {
        try { await run(); console.log(`PASS: ${name}`); }
        catch (error) { failures++; console.error(`FAIL: ${name}\n${error.message}`); }
    }
    console.log(`${cases.length - failures} passed, ${failures} failed`);
    if (failures) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
