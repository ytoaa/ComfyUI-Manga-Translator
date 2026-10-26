import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Node-local views only. No hidden requests, inference or separate project UI.
const panels = new Set(["MangaPageEditPlan", "MangaReviewDocument", "MangaOCRModel", "MangaOCRAdaptive", "MangaTextCheckpoint", "MangaDetectionCheckpoint", "MangaCleanupCheckpoint", "MangaTranslationContext", "MangaLetterPlan", "MangaLetterApply", "MangaLetteringDirection"]);
const labels = {ready:"준비됨", reused:"저장 결과 재사용", computed:"계산 완료", completed:"완료", running:"실행 중", error:"확인 필요", needs_review:"검수 필요"};
const widget = (node, name) => node.widgets?.find(w => w.name === name);
const clone = value => JSON.parse(JSON.stringify(value));
function status(node, info) {
    if (!node.mangaPanelStatus) return;
    const state = info.state || "completed";
    node.mangaPanelStatus.textContent = [labels[state] || state, info.engine, info.device, info.message].filter(Boolean).join(" · ");
    node.mangaPanelStatus.style.color = ["error","needs_review"].includes(state) ? "#ffb7b7" : state === "reused" ? "#88e5c4" : "#a7ceff";
}
function letteringReview(node,report) {
    const body=node.mangaPanelBody;if(!body)return;
    body.replaceChildren();
    const reasons={unsupported_translation_glyphs:'번역문에 폰트가 지원하지 않는 문자',
        source_below_readability_minimum:'원문 크기 추정값이 최소 식자 크기보다 작음',
        unverified_bubble_ownership:'말풍선 소유권 확인 필요',
        overlaps_preserved_lettering_region:'보존한 이웃 영역과 겹침',
        unfit_lettering_preserved:'최소 크기에서도 식자 불가',
        insufficient_source_style_pixels:'원문 스타일을 측정할 획 부족',
        manual_source_preservation:'원본 보존으로 선택한 영역',
        protected_region_overlap:'보호한 원문과 겹침',
        coincident_edit_frames:'서로 다른 원문이 같은 편집 범위를 사용',
        unverified_display_text:'큰 원문 영역·컷·말풍선 경계 확인 필요',
        ambiguous_isolated_source:'독립 문자 확인 필요',
        ambiguous_cross_label_source:'글자 분류·소유권 확인 필요'};
    for(const row of [...(report.lettering_review || []),...(report.source_preservation || [])]) {
        const line=document.createElement('div');
        const detail=row.diagnostic || {};
        const note=detail.code==='bubble_candidate_limit'?'관련 말풍선 후보 64개 초과':
            detail.code==='source_below_readability_minimum' ? `${detail.source_cap}px < 최소 ${detail.minimum_font}px` :
            detail.missing_characters?.length ? `지원 불가 문자: ${detail.missing_characters.join(' ')}` : '';
        line.textContent=[row.id,reasons[row.reason] || row.reason,note].filter(Boolean).join(' · ');
        line.style.cssText='padding:5px 0;overflow-wrap:anywhere;color:#ffb7b7';body.append(line);
    }
    if(!body.children.length){const line=document.createElement('div');line.textContent=`식자 ${report.regions?.length || 0}영역`;body.append(line);}
    if(report.needs_review && !(report.lettering_review?.length || report.source_preservation?.length)) {
        const line=document.createElement('div');line.textContent='상위 단계에 검수 표시가 있습니다. 검출·원문 검수와 크롭 보고서에서 사유를 확인하세요.';
        line.style.color='#ffb7b7';body.append(line);
    }
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
function editReview(node, snapshot) {
    const body=node.mangaPanelBody, edits=widget(node,'review_edits_json');
    if(!body || !edits)return;
    body.replaceChildren();
    const revision=snapshot.input_revision, owner=snapshot.page_identity;
    const current=()=>{
        const value=JSON.parse(edits.value || '{}');
        if(!value || Array.isArray(value) || typeof value!=='object')throw Error('review_edits_json을 먼저 확인하세요.');
        value.pages ||= {};value.identities ||= {};return value;
    };
    const patch=id=>{const value=current();return clone(value.identities[revision]===owner ? value.pages[revision]?.[id] || {} : {});};
    function save(id,value) {
        if(!owner)throw Error('페이지 식별 정보가 없습니다.');
        const editsValue=current();editsValue.pages[revision] ||= {};
        editsValue.pages[revision][id]=value;editsValue.identities[revision]=owner;
        const pointCount=Object.values(editsValue.pages[revision]).reduce((total,row)=>total+(row.strokes || []).reduce((n,s)=>n+s.points.length,0),0);
        if(pointCount>4096)throw Error('이 페이지 브러시 4096점 한도입니다. 획을 줄여 저장하세요.');
        const encoded=JSON.stringify(editsValue);
        if(new TextEncoder().encode(encoded).length>1048576)throw Error('편집 저장 한도 1 MiB를 넘었습니다.');
        edits.value=encoded;edits.callback?.(encoded);node.setDirtyCanvas?.(true,true);
        status(node,{state:'ready',message:'편집 저장됨 · Run으로 제거·식자에 반영'});
    }
    const style='box-sizing:border-box;max-width:100%;min-width:0;padding:6px;border:1px solid #43556e;border-radius:6px;background:#142338;color:#e1eaf7;font:inherit';
    const info=document.createElement('div');
    info.textContent='주황: 제거 마스크 · 파랑: 원문 획(지우기 불가). 브러시는 원본 픽셀 단위입니다. 수정 후 Run하세요.';
    info.style.cssText='margin:6px 0;line-height:1.5';body.append(info);
    for(const region of snapshot.regions || []) {
        const card=document.createElement('div');card.style.cssText=style+';margin:10px 0';
        const title=document.createElement('div');title.textContent=`${region.id} · ${region.action==='replace'?'교체':'원본 보존'} · ${region.reason}`;
        title.style.cssText='overflow-wrap:anywhere;margin-bottom:6px';card.append(title);
        const select=document.createElement('select');select.style.cssText=style+';width:100%';
        for(const [value,label] of [['auto','정책에 따라 자동'],['replace','이 영역 교체'],['preserve','이 영역 원본 보존']]) {
            const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);
        }
        let pending;
        try {pending=patch(region.id);}catch(error){status(node,{state:'error',message:error.message});return;}
        select.value=pending.action || 'auto';
        select.addEventListener('change',()=>{try {save(region.id,{...patch(region.id),action:select.value});}catch(error){status(node,{state:'error',message:error.message});}});
        card.append(select);
        const text=document.createElement('div');text.textContent=`${region.source}\n→ ${region.target}`;
        text.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-height:90px;overflow:auto;margin:7px 0';card.append(text);
        const controls=document.createElement('div');controls.style.cssText='display:flex;flex-wrap:wrap;gap:4px;align-items:center;margin:6px 0';
        const mode=document.createElement('select');mode.style.cssText=style;
        for(const [value,label] of [['add','제거 범위 칠하기'],['erase','추가 여백 지우기']]){
            const option=document.createElement('option');option.value=value;option.textContent=label;mode.append(option);
        }mode.value='add';controls.append(mode);
        const radius=document.createElement('input');radius.type='number';radius.min=1;radius.max=32;radius.value=8;
        radius.title='브러시 반경 · 원본 픽셀';radius.style.cssText=style+';width:55px';controls.append(radius);
        const undo=document.createElement('button');undo.textContent='획 취소';undo.style.cssText=style;controls.append(undo);
        const reset=document.createElement('button');reset.textContent='영역 편집 초기화';reset.style.cssText=style;controls.append(reset);card.append(controls);
        const canvas=document.createElement('canvas');canvas.width=region.preview_size[0];canvas.height=region.preview_size[1];
        canvas.style.cssText='display:block;max-width:100%;height:auto;touch-action:none;cursor:crosshair;border:1px solid #43556e';
        canvas.title='제거할 글자 획만 칠하세요. 영역 밖과 보호 영역은 편집되지 않습니다.';card.append(canvas);body.append(card);
        // The DOM contract harness has no raster API. Real browser drawing is
        // independently exercised by the Chromium layout/pointer check.
        if(!canvas.getContext)continue;
        const ctx=canvas.getContext('2d'), layer=document.createElement('canvas');layer.width=canvas.width;layer.height=canvas.height;
        const mask=layer.getContext('2d');
        const base=new Image(), overlay=new Image(), ink=new Image();
        const [a,b,c,d]=region.bbox_pixels,sx=canvas.width/(c-a),sy=canvas.height/(d-b);
        let active=null,ready=false,loaded=0;
        function drawStroke(stroke) {
            mask.save();mask.scale(sx,sy);mask.translate(-a,-b);
            mask.globalCompositeOperation=stroke.mode==='erase'?'destination-out':'source-over';
            mask.fillStyle=mask.strokeStyle='rgba(255,96,32,0.45)';mask.lineWidth=stroke.radius*2+1;mask.lineCap=mask.lineJoin='round';
            mask.beginPath();stroke.points.forEach(([x,y],i)=>i?mask.lineTo(x,y):mask.moveTo(x,y));mask.stroke();
            for(const [x,y] of stroke.points){mask.beginPath();mask.arc(x,y,stroke.radius,0,Math.PI*2);mask.fill();}mask.restore();
        }
        function repaint() {
            if(!ready)return;
            ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(base,0,0);
            mask.clearRect(0,0,canvas.width,canvas.height);mask.drawImage(overlay,0,0);
            for(const stroke of patch(region.id).strokes || [])drawStroke(stroke);
            if(active)drawStroke(active);
            ctx.drawImage(layer,0,0);ctx.drawImage(ink,0,0);
        }
        for(const [image,uri] of [[base,region.image],[overlay,region.overlay],[ink,region.source_overlay]]) {
            image.onload=()=>{if(++loaded===3){ready=true;repaint();}};image.src=uri;
        }
        function point(event) {
            const rect=canvas.getBoundingClientRect();
            return [Math.min(c-1,Math.max(a,Math.floor(a+(event.clientX-rect.left)*(c-a)/rect.width))),
                    Math.min(d-1,Math.max(b,Math.floor(b+(event.clientY-rect.top)*(d-b)/rect.height)))];
        }
        canvas.addEventListener('pointerdown',event=>{
            if(!ready || (event.button!==undefined && event.button!==0))return;
            const r=Number(radius.value);
            if(!Number.isInteger(r)||r<1||r>32){status(node,{state:'error',message:'브러시 반경은 1~32 정수입니다.'});return;}
            active={mode:mode.value,radius:r,points:[point(event)]};canvas.setPointerCapture(event.pointerId);repaint();
        });
        canvas.addEventListener('pointermove',event=>{
            if(!active || active.points.length>=256)return;
            const p=point(event),last=active.points.at(-1);
            if(p[0]!==last[0]||p[1]!==last[1]){active.points.push(p);repaint();}
        });
        canvas.addEventListener('pointerup',()=>{
            if(!active)return;
            try {
                const value=patch(region.id);value.strokes ||= [];
                if(value.strokes.length>=128)throw Error('영역 브러시 128획 한도입니다.');
                value.strokes.push(active);save(region.id,value);
            }catch(error){status(node,{state:'error',message:error.message});}
            active=null;repaint();
        });
        canvas.addEventListener('pointercancel',()=>{active=null;repaint();});
        undo.addEventListener('click',()=>{try{const value=patch(region.id);value.strokes?.pop();save(region.id,value);repaint();}catch(error){status(node,{state:'error',message:error.message});}});
        reset.addEventListener('click',()=>{try{save(region.id,{});select.value='auto';repaint();}catch(error){status(node,{state:'error',message:error.message});}});
    }
    if(snapshot.warnings?.length)status(node,{state:'needs_review',message:snapshot.warnings.join(' ')});
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
                const height=data.name === "MangaReviewDocument" ? 300 : data.name === "MangaPageEditPlan" ? 420 : 104;
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
            if(output?.manga_edit_review?.[0])editReview(this,output.manga_edit_review[0]);
            if(output?.manga_lettering_report?.[0])letteringReview(this,output.manga_lettering_report[0]);
            return result;
        };
    },
    setup() {
        api.addEventListener("manga_model_progress",({detail:d})=>{const node=app.graph?.getNodeById(d.node);if(node)status(node,{state:"running",message:`모델 다운로드 ${d.index+1}/${d.total} · ${d.file} · ${(d.bytes/1048576).toFixed(1)} MiB`});});
        api.addEventListener("executing",({detail:d})=>{const node=app.graph?.getNodeById(typeof d === "object" ? d?.node : d);if(node)status(node,{state:"running"});});
        api.addEventListener("execution_error",({detail:d})=>{const node=app.graph?.getNodeById(d.node_id);if(node)status(node,{state:"error",message:d.exception_message});});
    }
});
