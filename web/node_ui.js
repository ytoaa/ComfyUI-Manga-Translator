import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Node-local views only. No hidden requests, inference or separate project UI.
const panels = new Set(["MangaReviewDocument", "MangaOCRModel", "MangaOCRAdaptive", "MangaTextCheckpoint", "MangaDetectionCheckpoint", "MangaCleanupCheckpoint", "MangaTranslationContext", "MangaLetterPlan", "MangaLetterApply", "MangaLetteringDirection"]);
const labels = {ready:"준비됨", reused:"저장 결과 재사용", computed:"계산 완료", completed:"완료", running:"실행 중", error:"확인 필요", needs_review:"검수 필요"};
const widget = (node, name) => node.widgets?.find(w => w.name === name);
const clone = value => JSON.parse(JSON.stringify(value));
function status(node, info) {
    if (!node.mangaPanelStatus) return;
    const state = info.state || "completed";
    node.mangaPanelStatus.textContent = [labels[state] || state, info.engine, info.device, info.message].filter(Boolean).join(" · ");
    node.mangaPanelStatus.style.color = ["error","needs_review"].includes(state) ? "#ffb7b7" : state === "reused" ? "#88e5c4" : "#a7ceff";
}
function review(node, snapshot) {
    const body = node.mangaPanelBody;
    if (!body) return;
    body.replaceChildren();
    const {stage, input_revision: revision, document: data, page_identity: owner} = snapshot;
    const edits = widget(node, "edits_json");
    function current() {
        try { const result = JSON.parse(edits.value || "{}"); result.pages ||= {}; return result; }
        catch { throw new Error("edits_json JSON을 먼저 확인하세요."); }
    }
    function save(id, field, value, block) {
        if(snapshot.identity_verified === false)throw new Error('페이지 식별 입력을 연결한 뒤 교정하세요.');
        const patch = current(); patch.pages[revision] ||= {}; const row = patch.pages[revision][id] ||= {};
        if(owner){patch.identities ||= {};patch.identities[revision]=owner;}
        if (block) {
            row.blocks ||= clone(data.regions.find(r => r.id === id).blocks);
            row.blocks.find(b => b.id === block)[field] = value;
        } else row[field] = value;
        edits.value = JSON.stringify(patch); edits.callback?.(edits.value);
        status(node, {state:"ready",message:"수정 저장됨 · Run으로 반영"});node.setDirtyCanvas?.(true,true);
    }
    let pending;
    try {pending=current().pages[revision] || {};} catch(error) {status(node,{state:'error',message:error.message});return;}
    for (const raw of data.regions || []) {
        const region={...raw,...pending[raw.id]};
        const blocks = region.blocks?.length ? region.blocks : [region];
        for (const block of blocks) {
            const label = document.createElement("label");
            label.textContent = `${region.id}${block === region ? "" : ` / ${block.id}`} · ${block.role === "heading" ? "제목" : "본문"}`;
            label.style.cssText = "display:block;margin:10px 0 5px;color:#bed1e9;font-size:11px";
            const input = document.createElement("textarea");
            input.disabled=snapshot.identity_verified === false;
            input.value = block[stage] || "";input.rows = block.role === "heading" ? 2 : 4;
            input.style.cssText = "box-sizing:border-box;display:block;width:100%;max-width:100%;min-width:0;resize:vertical;border:1px solid #43556e;border-radius:8px;padding:10px;background:#111d2d;color:#f0f5fc;font:inherit;line-height:1.55";
            input.addEventListener("input", () => {try {save(region.id,stage,input.value,block === region ? null : block.id);} catch(error) {status(node,{state:"error",message:error.message});}});
            body.append(label,input);
        }
    }
    if (stage === "target" && data.regions?.length) {
        const approve = document.createElement("button");approve.textContent = "이 페이지 번역 확정";
        approve.disabled=snapshot.identity_verified === false;
        approve.style.cssText = "width:100%;margin-top:14px;padding:10px;border:1px solid #5b91b0;border-radius:8px;background:#17394c;color:#e5fbff;font:inherit;cursor:pointer";
        approve.addEventListener("click", () => {
            try {
                const patch=current();patch.pages[revision] ||= {};
                if(snapshot.identity_verified === false)throw new Error('페이지 식별 입력을 연결한 뒤 확정하세요.');
                if(owner){patch.identities ||= {};patch.identities[revision]=owner;}
                for(const r of data.regions) {
                    const row=patch.pages[revision][r.id] ||= {};
                    if(!row.blocks && !Object.hasOwn(row,"target")) {
                        if(r.blocks?.length)row.blocks=clone(r.blocks);
                        else row.target=r.target;
                    }
                }
                edits.value=JSON.stringify(patch);edits.callback?.(edits.value);
                status(node,{state:"ready",message:"확정 저장됨 · Run으로 반영"});node.setDirtyCanvas?.(true,true);
            } catch(error) {status(node,{state:"error",message:error.message});}
        });body.append(approve);
    }
    if(snapshot.identity_verified === false)status(node,{state:'error',message:'페이지 식별 정보가 없습니다. 새 통합 08의 page_context_json 연결을 확인하세요.'});
    else if(snapshot.warnings?.length)status(node,{state:'error',message:snapshot.warnings.join(' ')});
}
app.registerExtension({
    name:"manga-translator.node-ui",
    async beforeRegisterNodeDef(Node, data) {
        if (!data.name.startsWith("Manga")) return;
        const created=Node.prototype.onNodeCreated;
        Node.prototype.onNodeCreated=function() {
            const result=created?.apply(this,arguments);this.color="#263a50";this.bgcolor="#152333";
            if (panels.has(data.name) && this.addDOMWidget) {
                const panel=document.createElement("div");
                panel.style.cssText="box-sizing:border-box;width:100%;max-width:100%;min-width:0;height:100%;min-height:0;overflow:hidden;display:flex;flex-direction:column;padding:12px;border:1px solid #3c536f;border-radius:12px;background:linear-gradient(145deg,#1c2e45,#142031);color:#e1eaf7;font:12px system-ui,sans-serif";
                const title=document.createElement("div");title.textContent="MANGA / "+(data.name === "MangaReviewDocument" ? "REVIEW" : "WORKFLOW");title.style.cssText="font-size:10px;letter-spacing:1.5px;color:#8099bb;margin-bottom:8px";
                title.style.flex="0 0 auto";
                this.mangaPanelStatus=document.createElement("div");this.mangaPanelStatus.textContent="Run하면 현재 상태가 표시됩니다.";
                this.mangaPanelStatus.style.cssText="flex:0 0 auto;min-width:0;overflow-wrap:anywhere;max-height:48px;overflow:auto";
                this.mangaPanelBody=document.createElement("div");this.mangaPanelBody.style.cssText="flex:1 1 auto;min-height:0;min-width:0;overflow:auto;overflow-wrap:anywhere";panel.append(title,this.mangaPanelStatus,this.mangaPanelBody);
                const height=data.name === "MangaReviewDocument" ? 300 : 104;
                const view=this.addDOMWidget("manga_node_panel","manga_node_panel",panel,{serialize:false,getMinHeight:()=>height,getMaxHeight:()=>height,getHeight:()=>height});
                view.computeSize=()=>[0,height];view.serialize=false;view.options ||= {};view.options.serialize=false;
            }return result;
        };
        const configured=Node.prototype.onConfigure;
        Node.prototype.onConfigure=function() {
            const result=configured?.apply(this,arguments);
            const needed=this.computeSize?.();
            if(needed && this.size && this.setSize)this.setSize([Math.max(this.size[0],needed[0]),Math.max(this.size[1],needed[1])]);
            return result;
        };
        const executed=Node.prototype.onExecuted;
        Node.prototype.onExecuted=function(output) {
            const result=executed?.apply(this,arguments);
            if(output?.manga_status?.[0])status(this,output.manga_status[0]);
            else if(data.name !== "MangaWorkflowInput")status(this,{state:"completed"});
            if(output?.manga_document?.[0])review(this,output.manga_document[0]);
            return result;
        };
    },
    setup() {
        api.addEventListener("manga_model_progress",({detail:d})=>{const node=app.graph?.getNodeById(d.node);if(node)status(node,{state:"running",message:`모델 다운로드 ${d.index+1}/${d.total} · ${d.file} · ${(d.bytes/1048576).toFixed(1)} MiB`});});
        api.addEventListener("executing",({detail:d})=>{const node=app.graph?.getNodeById(typeof d === "object" ? d?.node : d);if(node)status(node,{state:"running"});});
        api.addEventListener("execution_error",({detail:d})=>{const node=app.graph?.getNodeById(d.node_id);if(node)status(node,{state:"error",message:d.exception_message});});
    }
});
