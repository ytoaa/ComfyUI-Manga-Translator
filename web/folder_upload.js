import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const IMAGE_RE = /\.(png|jpe?g|webp|bmp|tiff?|gif)$/i;

function findWidget(node, name) {
    return node.widgets?.find(widget => widget.name === name);
}

function cleanParts(value) {
    const parts = String(value || "").replaceAll("\\", "/").split("/").filter(Boolean);
    if (!parts.length || parts.some(part => part === "." || part === "..")) {
        throw new Error("업로드 폴더 경로가 올바르지 않습니다.");
    }
    return parts;
}

function uploadId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID().replaceAll("-", "");
    return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
}

async function uploadOne(file, subfolder) {
    const form = new FormData();
    form.append("image", file, file.name);
    form.append("type", "input");
    form.append("subfolder", subfolder);
    form.append("overwrite", "false");
    const response = await api.fetchApi("/upload/image", { method: "POST", body: form });
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok || data.type !== "input") {
        throw new Error(data.error || data.message || `이미지 업로드 실패 (HTTP ${response.status})`);
    }
    return data;
}

async function chooseAndUpload(node, button) {
    const picker = document.createElement("input");
    picker.type = "file";
    picker.multiple = true;
    picker.setAttribute("webkitdirectory", "");
    picker.accept = ".png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.gif,image/*";

    const files = await new Promise(resolve => {
        picker.onchange = () => resolve(Array.from(picker.files || []));
        picker.oncancel = () => resolve([]);
        picker.click();
    });
    if (!files.length) return;

    const images = files.filter(file => IMAGE_RE.test(file.name));
    if (!images.length) throw new Error("선택한 폴더에 지원되는 이미지가 없습니다.");

    const firstParts = cleanParts(images[0].webkitRelativePath || images[0].name);
    const selectedRoot = firstParts.length > 1 ? firstParts[0] : "folder";
    for (const file of images) {
        const parts = cleanParts(file.webkitRelativePath || file.name);
        if (parts.length > 1 && parts[0] !== selectedRoot) {
            throw new Error("한 번에 하나의 폴더만 업로드할 수 있습니다.");
        }
    }

    const targetRoot = `manga_uploads/${uploadId()}/${selectedRoot}`;
    const originalLabel = button.label || button.name || "PC 폴더 업로드";
    button.disabled = true;
    try {
        for (let index = 0; index < images.length; index++) {
            const file = images[index];
            const parts = cleanParts(file.webkitRelativePath || file.name);
            const relativeParts = parts.length > 1 ? parts.slice(1, -1) : [];
            const subfolder = [targetRoot, ...relativeParts].join("/");
            button.label = `업로드 ${index + 1}/${images.length}`;
            node.setDirtyCanvas?.(true, true);
            await uploadOne(file, subfolder);
        }

        const mode = findWidget(node, "input_mode");
        const folder = findWidget(node, "input_folder");
        const project = findWidget(node, "project_name");
        if (!mode || !folder) throw new Error("워크플로우 입력 위젯을 찾을 수 없습니다.");
        mode.value = "폴더 프로젝트";
        folder.value = targetRoot;
        if (project && (!String(project.value || "").trim() || project.value === "book_01")) {
            project.value = selectedRoot.slice(0, 80);
        }
        button.label = `${images.length}개 업로드 완료`;
        node.setDirtyCanvas?.(true, true);
        setTimeout(() => {
            button.label = originalLabel;
            node.setDirtyCanvas?.(true, true);
        }, 1800);
    } catch (error) {
        button.label = "업로드 실패 · 다시 선택";
        node.setDirtyCanvas?.(true, true);
        throw error;
    } finally {
        button.disabled = false;
    }
}

app.registerExtension({
    name: "MangaTranslator.WorkflowFolderUpload",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "MangaWorkflowInput") return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            const button = this.addWidget("button", "PC 폴더 업로드", null, async () => {
                try {
                    await chooseAndUpload(this, button);
                } catch (error) {
                    console.error("Manga folder upload failed", error);
                    window.alert(`폴더 업로드 실패: ${error.message || error}`);
                }
            }, { serialize: false });
            // ComfyUI has separate workflow and prompt serialization flags.
            // Keep this helper control out of both and append it after all real widgets.
            button.serialize = false;
            button.options = { ...(button.options || {}), serialize: false };
            return result;
        };
    },
});
