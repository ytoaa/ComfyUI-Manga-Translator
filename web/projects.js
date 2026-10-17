import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const BASE = "/manga/projects";
const statuses = {ready:"준비",pending:"대기",preparing:"입력 준비",submitting:"접수 확인",queued:"큐 대기",running:"진행 중",collecting:"결과 수집",completed:"완료",failed:"실패",needs_review:"검토 필요",unchanged_blank:"빈 페이지",paused:"일시정지",stopping:"일시정지 대기",review:"검토할 페이지 있음"};
const label = value => statuses[value] || value;
function element(tag, text, parent) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.append(node);
    return node;
}
async function call(path = "", value) {
    const response = await api.fetchApi(BASE + path, value === undefined ? {} : {
        method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(value)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
}

function renderPanel(host) {
    if (host.__mangaPanel) { host.__mangaPanel.refresh(); return; }
    const root = element("div", undefined, host);
    root.className = "manga-project-panel";
    element("h3", "만화 번역 프로젝트", root);
    element("p", "08 워크플로우를 열고 모델·번역·식자 설정을 맞춘 뒤 폴더를 실행하세요.", root);
    const notice = element("div", "", root); notice.setAttribute("role","status"); notice.className = "mp-notice";
    const controls = [];
    let busy = false, selected = "", folder = "", current = null, timer = null, pageOffset = 0;
    const act = async fn => {
        if (busy) return;
        busy = true; controls.forEach(node => node.disabled = true);
        try { await fn(); } catch (error) { notice.textContent = error.message; }
        finally { busy = false; controls.forEach(node => node.disabled = false); }
    };
    const button = (text, parent, fn) => {
        const node = element("button", text, parent); node.type = "button";
        node.onclick = () => act(fn); controls.push(node); return node;
    };
    element("label", "프로젝트 이름", root);
    const name = element("input", undefined, root); name.placeholder = "예: 1권"; name.maxLength = 80;
    element("label", "원본 폴더", root);
    const selectedFolder = element("div", "선택하지 않음", root); selectedFolder.className = "mp-path";
    const folderActions = element("div", undefined, root); folderActions.className = "mp-actions";
    const picker = element("input", undefined, root);
    picker.type = "file"; picker.multiple = true; picker.setAttribute("webkitdirectory", ""); picker.hidden = true;
    button("내 PC 폴더 업로드", folderActions, async () => picker.click());
    const browser = element("div", undefined, root); browser.hidden = true;
    const location = element("div", "", browser); location.className = "mp-path";
    const dirs = element("div", undefined, browser); dirs.className = "mp-folders";
    let browsed = "";
    async function browse(path = "") {
        const data = await call("/folders?path=" + encodeURIComponent(path));
        browsed = data.path; location.textContent = "ComfyUI/input/" + data.path + ` (${data.images}개 이미지, 하위 폴더 포함 처리)`;
        dirs.replaceChildren();
        if (data.path) {
            const up = element("button", "↑ 상위 폴더", dirs);
            up.onclick = () => act(() => browse(data.path.split("/").slice(0,-1).join("/")));
        }
        for (const item of data.folders) {
            const node = element("button", "📁 " + item.name, dirs);
            node.onclick = () => act(() => browse(item.path));
        }
    }
    button("서버 input 폴더 선택", folderActions, async () => { browser.hidden = false; await browse(); });
    button("이 폴더 선택", browser, async () => {
        if (!browsed) throw new Error("프로젝트 원본을 모은 input 하위 폴더를 선택하세요.");
        folder = browsed; selectedFolder.textContent = "ComfyUI/input/" + folder; browser.hidden = true;
    });
    picker.onchange = () => act(async () => {
        const supported = /\.(png|jpe?g|webp|bmp|tiff?|gif)$/i;
        const files = Array.from(picker.files || []).filter(file => supported.test(file.name));
        if (!files.length) throw new Error("선택한 폴더에 지원되는 이미지가 없습니다.");
        if (files.some(file => file.size > 256*1024*1024)) throw new Error("256MiB를 넘는 이미지가 있습니다.");
        folder = ""; selectedFolder.textContent = "업로드 중 · 모든 파일 전송 후 선택됩니다.";
        const imported = await call("/import", {});
        const ident = imported.input.split("/").pop();
        // Select only after every upload succeeds: a partial import is never started automatically.
        for (let index = 0; index < files.length; index++) {
            const file = files[index], relative = file.webkitRelativePath || file.name;
            notice.textContent = `업로드 ${index+1}/${files.length}: ${relative}`;
            const form = new FormData(); form.append("image", file, file.name);
            const response = await api.fetchApi(BASE + `/import/${ident}?path=${encodeURIComponent(relative)}`, {method:"POST",body:form});
            const data = await response.json(); if (!response.ok) throw new Error(data.error || "업로드 실패");
        }
        folder = imported.input; selectedFolder.textContent = "ComfyUI/input/" + folder;
        if (!name.value.trim()) name.value = (files[0].webkitRelativePath || "새 프로젝트").split("/")[0];
        notice.textContent = `${files.length}개 업로드 완료. 현재 08 설정으로 새 프로젝트를 시작하세요.`;
        picker.value = "";
    });
    const create = button("현재 08 설정으로 새 프로젝트 시작", root, async () => {
        if (!selectedFolder.textContent.startsWith("ComfyUI/input/")) throw new Error("원본 폴더를 먼저 선택하세요.");
        const prompt = await app.graphToPrompt();
        const data = await call("", {name:name.value, input:folder, graph:prompt.output});
        selected = data.id; pageOffset = 0;
        await loadProjects();
        await call(`/${selected}/start`, {});
        await refresh();
    });
    create.className = "mp-primary";
    element("hr", undefined, root);
    element("label", "저장된 프로젝트", root);
    const projects = element("select", undefined, root);
    const projectActions = element("div", undefined, root); projectActions.className = "mp-actions";
    button("목록 새로고침", projectActions, async () => { await loadProjects(); await refresh(); });
    button("저장된 설정으로 재개", projectActions, async () => {
        if (!selected) throw new Error("프로젝트를 선택하세요.");
        await call(`/${selected}/start`, {retry_failed:retry.checked}); await refresh();
    });
    button("일시정지", projectActions, async () => {
        if (!selected) return; await call(`/${selected}/stop`, {}); await refresh();
    });
    const retryLabel = element("label", undefined, root); retryLabel.className = "mp-check";
    const retry = element("input", undefined, retryLabel); retry.type = "checkbox";
    retryLabel.append(document.createTextNode("실패 페이지도 한 번씩 다시 시도"));
    element("p", "재개는 프로젝트를 만들 때 저장한 설정을 사용합니다. 설정을 바꾸려면 새 프로젝트를 만드세요. 일시정지는 현재 페이지를 마친 뒤 적용됩니다.", root);
    const heading = element("strong", "", root);
    const counts = element("div", "", root);
    const output = element("div", "", root); output.className = "mp-path";
    const list = element("div", undefined, root);
    const pager = element("div", undefined, root); pager.className = "mp-actions";
    button("이전 50개", pager, async () => { pageOffset = Math.max(0,pageOffset-50); draw(); });
    button("다음 50개", pager, async () => { if (current && pageOffset+50<current.pages.length) pageOffset += 50; draw(); });
    function draw() {
        if (!current) return;
        heading.textContent = current.name + " · " + label(current.status);
        counts.textContent = Object.entries(current.counts).map(([key,value]) => `${label(key)} ${value}`).join(" / ") || "페이지 목록 확인 전";
        output.textContent = "저장 위치: " + current.output_folder + (current.export ? "\n정렬된 결과: " + current.export : "");
        list.replaceChildren();
        for (const [index,row] of current.pages.slice(pageOffset,pageOffset+50).entries()) {
            const item = element("div", undefined, list); item.className = "mp-page";
            element("strong", `${pageOffset+index+1}. ${row.relative_path} · ${label(row.status)}`, item);
            if (row.reason || row.failure_message) element("p", [row.failure_node,row.reason,row.failure_message].filter(Boolean).join("\n"), item);
            if (row.artifacts?.includes("result.png")) {
                const image = element("img", undefined, item); image.loading = "lazy";
                image.alt = row.relative_path + " 번역 결과"; image.style.cssText = "display:block;max-width:100%;max-height:220px;margin:8px 0;object-fit:contain";
                image.src = api.apiURL(BASE + `/${current.id}/file/${row.id}/${row.attempt}/result.png`);
            }
            const links = element("div", undefined, item); links.className = "mp-actions";
            for (const file of row.artifacts || []) {
                const link = element("a", {"result.png":"결과 이미지","source.json":"OCR JSON","target.json":"번역 JSON","input.png":"원본"}[file], links);
                link.href = api.apiURL(BASE + `/${current.id}/file/${row.id}/${row.attempt}/${file}`);
                link.target = "_blank"; link.rel = "noopener";
            }
        }
    }
    async function refresh() {
        clearTimeout(timer);
        try {
            if (!selected) return;
            current = await call("/" + selected); draw();
            const option = Array.from(projects.options).find(item => item.value === selected);
            if (option) option.textContent = current.name + " · " + label(current.status);
            if (!busy) notice.textContent = current.message;
        } catch (error) { if (!busy) notice.textContent = error.message; }
        finally { if (host.isConnected) timer = setTimeout(refresh, 2000); }
    }
    async function loadProjects() {
        const data = await call(); projects.replaceChildren();
        for (const item of data.projects) {
            const option = element("option", item.name + " · " + label(item.status), projects); option.value = item.id;
        }
        if (!data.projects.some(item => item.id === selected)) selected = data.projects[0]?.id || "";
        projects.value = selected;
    }
    projects.onchange = () => { selected = projects.value; pageOffset = 0; refresh(); };
    host.__mangaPanel = {refresh};
    act(async () => { await loadProjects(); await refresh(); });
}

app.registerExtension({
    name:"MangaTranslator.FolderProjects",
    async setup() {
        const style = document.createElement("style");
        style.textContent = `.manga-project-panel{padding:14px;overflow:auto;height:100%;box-sizing:border-box;font-size:13px;display:flex;flex-direction:column;gap:9px}.manga-project-panel>*{flex-shrink:0}.manga-project-panel hr{width:100%;border:0;border-top:1px solid var(--border-color)}.manga-project-panel h3,.manga-project-panel p{margin:0;line-height:1.5}.manga-project-panel input:not([type=checkbox]),.manga-project-panel select{width:100%;box-sizing:border-box;padding:7px;color:var(--input-text);background:var(--comfy-input-bg);border:1px solid var(--border-color)}.manga-project-panel button{padding:7px 9px;border:1px solid var(--border-color);border-radius:5px;background:var(--comfy-input-bg);color:var(--input-text);cursor:pointer}.manga-project-panel button:disabled{opacity:.5;cursor:wait}.manga-project-panel .mp-primary{background:#326150;color:#fff}.mp-actions{display:flex;flex-wrap:wrap;gap:9px}.mp-path,.mp-page p{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;opacity:.85}.mp-folders{display:flex;flex-direction:column;gap:5px;max-height:200px;overflow:auto}.mp-notice{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--input-text);border-left:3px solid #65a88d;padding-left:7px}.mp-page{padding:10px 0;border-bottom:1px solid var(--border-color)}.mp-page a{color:#80bca5}.mp-check{display:flex;align-items:center;gap:7px}`;
        document.head.append(style);
        app.extensionManager.registerSidebarTab({id:"manga-projects",icon:"pi pi-book",title:"만화 번역 프로젝트",tooltip:"만화 번역 프로젝트 · 폴더 처리",type:"custom",render:renderPanel});
    }
});
