import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// The browser queues ordinary canvas prompts. This module never calls a model,
// starts a server-side worker, or submits a hidden child API graph.
const active = new Map();
const lastTicket = new Map();
const settled = new Set();
let executingPrompt = null;
const fields = node => Object.fromEntries((node.widgets || []).map(w => [w.name, w.value]));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function show(node, text) {
    if (node?.mangaPanelStatus) node.mangaPanelStatus.textContent=text;
    if (!node?.mangaStatus) return;
    node.mangaStatus.value = text;
    node.setDirtyCanvas?.(true, true);
}

function describe(report) {
    const counts = Object.entries(report.counts || {}).map(([k,v]) => `${k}: ${v}`).join(" / ");
    return `${report.current_page || "폴더 프로젝트"}\n${report.message || report.status || ""}\n${counts}`;
}

function showReport(node, report) {
    show(node, describe(report));
    // Keep the standard PreviewAny already connected to report slot 2 current.
    for (const link of Object.values(app.graph?.links || {})) {
        if (String(link.origin_id) === String(node.id) && link.origin_slot === 2) {
            const preview = app.graph.getNodeById(link.target_id);
            if (preview?.comfyClass === "PreviewAny" || preview?.type === "PreviewAny") {
                preview.onExecuted?.({ text: [JSON.stringify(report, null, 2)] });
            }
        }
    }
}

function sameCanvas(job) {
    const node = app.graph?.getNodeById(job.source_node);
    if (!node || (node.comfyClass || node.type) !== "MangaWorkflowInput") return null;
    const value = fields(node);
    if (value.input_mode !== "폴더 프로젝트" || value.project_name !== job.project_name
        || (job.input_folder && value.input_folder !== job.input_folder)
        || !["시작·재개", "실패 재시도", "실패·검수 재시도"].includes(value.action)) return null;
    return node;
}

async function request(route, job) {
    const response = await api.fetchApi(`/manga_translator/workflow/${route}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_name: job.project_name, run_id: job.run_id, prompt_id: job.prompt_id }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `프로젝트 기록 확인 실패 (${response.status})`);
    return result;
}

async function pause(job) {
    job.stopped = true;
    try {
        const report = await request("pause", job);
        const node = sameCanvas(job);
        if (node) showReport(node, report);
    } catch (error) {
        const node = sameCanvas(job);
        show(node, `연속 제출 중지 · ${error.message}`);
    }
}

async function finish(promptId, interrupted = false) {
    const job = active.get(promptId);
    if (!job || settled.has(promptId)) return;
    settled.add(promptId);
    if (interrupted) job.stopped = true;
    const node = sameCanvas(job);
    show(node, `${job.relative_path} · 완료 기록 확인 중`);
    try {
        let result;
        // execution_success may precede PromptQueue.task_done by a few ms.
        for (let count = 0; count < 150; count++) {
            result = await request("resolve", job);
            if (!result.pending) break;
            await delay(200);
        }
        if (!result || result.pending) throw new Error("완료 이력을 확인하지 못했습니다. 상태 확인 후 재개하세요.");
        if (node) showReport(node, result.report);
        if (!result.continue || job.stopped) return;
        // ComfyUI can emit execution_error/success while its original
        // app.queuePrompt is still updating the job UI. A reentrant call queues
        // work but returns false, before serializing our continuation marker.
        // Wait for that ordinary submission to finish, then enqueue exactly once.
        for (let count = 0; app.processingQueue; count++) {
            if (job.stopped) return;
            if (count >= 300) throw new Error("기본 Run 제출 처리가 끝나지 않았습니다. 상태 확인 후 재개하세요.");
            await delay(100);
        }
        if (job.stopped) return;
        const current = sameCanvas(job);
        if (!current) { await pause(job); return; }
        // Only this queue call gets the continuation property. ComfyUI serializes
        // it in its normal workflow metadata, alongside the visible API graph.
        const previous = current.properties.manga_canvas_run;
        current.properties.manga_canvas_run = { run_id: job.run_id, source_node: String(job.source_node) };
        try {
            show(current, `${describe(result.report)}\n다음 페이지를 기본 실행 큐에 추가합니다.`);
            const accepted = await app.queuePrompt(0, 1);
            if (accepted === false) throw new Error("다음 페이지 큐 제출이 거부됐습니다.");
        } finally {
            if (previous === undefined) delete current.properties.manga_canvas_run;
            else current.properties.manga_canvas_run = previous;
        }
    } catch (error) {
        await pause(job);
        show(node, `연속 제출 중지 · ${error.message}`);
    } finally {
        active.delete(promptId);
        if (settled.size > 1000) settled.delete(settled.values().next().value);
    }
}

api.addEventListener("executed", event => {
    const data = event.detail || {};
    const ticket = data.output?.manga_workflow?.[0];
    if (!ticket?.run_id || !ticket?.prompt_id) {
        const source = app.graph?.getNodeById(data.node);
        if ((source?.comfyClass || source?.type) === "MangaWorkflowInput" && data.output?.text?.[0]) {
            try { showReport(source, JSON.parse(data.output.text[0])); } catch (_) {}
        }
        return;
    }
    const node = sameCanvas(ticket);
    const job = { ...ticket, stopped: false };
    active.set(ticket.prompt_id, job);
    lastTicket.set(String(ticket.source_node), job);
    if (node) {
        showReport(node, ticket.report || {});
        const stop = node.mangaStopRequested;
        if (stop?.project_name === ticket.project_name && stop?.input_folder === ticket.input_folder) {
            delete node.mangaStopRequested;
            void pause(job);
        }
    }
});
api.addEventListener("execution_start", event => { executingPrompt = event.detail?.prompt_id || null; });
api.addEventListener("executing", event => {
    const raw = event.detail;
    const data = typeof raw === "object" && raw !== null ? raw : { node: raw, prompt_id: executingPrompt };
    const job = active.get(data.prompt_id);
    if (!job || !data.node) return;
    const source = sameCanvas(job);
    const current = app.graph?.getNodeById(data.display_node || data.node);
    show(source, `${job.index}/${job.total} · ${job.relative_path}\n실행 중: ${current?.title || current?.comfyClass || data.node}`);
});
api.addEventListener("progress", event => {
    const data = event.detail || {};
    const job = active.get(data.prompt_id);
    if (!job) return;
    const node = sameCanvas(job);
    const current = app.graph?.getNodeById(data.node);
    show(node, `${job.index}/${job.total} · ${job.relative_path}\n${current?.title || "처리 중"} · ${data.value}/${data.max}`);
});
for (const name of ["execution_success", "execution_error", "execution_interrupted"]) {
    api.addEventListener(name, event => void finish(event.detail?.prompt_id, name === "execution_interrupted"));
}
api.addEventListener("reconnecting", () => {
    // Do not guess that an accepted prompt failed or automatically re-submit.
    for (const job of active.values()) {
        job.stopped = true;
        show(app.graph?.getNodeById(job.source_node), "연결이 끊겼습니다. 현재 작업 이력 확인 후 같은 노드에서 재개하세요.");
    }
    active.clear();
});

app.registerExtension({
    name: "MangaTranslator.CanvasExecution",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "MangaWorkflowInput") return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            delete this.properties.manga_canvas_run;
            const status = document.createElement("textarea");
            status.readOnly = true;
            status.value = "이미지 한 장 / 폴더 프로젝트를 선택하고 Run";
            status.style.cssText = "width:100%;height:100%;min-height:90px;resize:none;box-sizing:border-box;background:#20232a;color:#e9edf2;border:1px solid #4b5363;border-radius:5px;padding:8px;font:13px/1.5 sans-serif;";
            const display = this.addDOMWidget("현재 페이지 · 실시간 진행", "manga_status", status, {
                serialize: false, getValue: () => status.value, setValue: value => { status.value = value; },
            });
            display.serialize = false;
            display.options = { ...(display.options || {}), serialize: false };
            display.computeSize = width => [width, 100];
            this.mangaStatus = status;
            const button = this.addWidget("button", "연속 처리 중지 · 현재 페이지 이후", null, async () => {
                const job = lastTicket.get(String(this.id));
                const value = fields(this);
                if (job && active.has(job.prompt_id) && value.project_name === job.project_name && value.input_folder === job.input_folder) await pause(job);
                else {
                    this.mangaStopRequested = { project_name:value.project_name, input_folder:value.input_folder };
                    show(this, '연속 실행 중지 요청. 현재 페이지 이후 추가 제출하지 않습니다.');
                }
            }, { serialize: false });
            button.serialize = false;
            button.options = { ...(button.options || {}), serialize: false };
            return result;
        };
        const configured = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = configured?.apply(this, arguments);
            delete this.properties.manga_canvas_run;
            return result;
        };
    },
});
