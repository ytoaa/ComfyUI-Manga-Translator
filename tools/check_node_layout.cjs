/* Actual Chromium CSS layout; node/widget APIs are a bounded frontend harness. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const code=name=>fs.readFileSync(path.join(root,'web',name),'utf8').replace(/^import .*;$/gm,'');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.MANGA_LAYOUT_CHROMIUM || (fs.existsSync(chromium.executablePath()) ? chromium.executablePath() : undefined),headless:true,args:['--no-sandbox']});
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const result=await page.evaluate(async ({nodeCode,flowCode})=>{
  const extensions=[];
  window.app={graph:{getNodeById:()=>null},registerExtension:e=>extensions.push(e)};
  window.api={addEventListener(){}};
  (0,eval)(`(()=>{${nodeCode}\n})();`);(0,eval)(`(()=>{${flowCode}\n})();`);
  const checks=[];
  for(const order of [extensions,[...extensions].reverse()])for(const kind of ['MangaWorkflowInput','MangaReviewDocument','MangaLetterPlan','MangaOCRModel','MangaCleanupCheckpoint'])for(const width of [240,420,600]) {
   class Node {
    constructor(){this.widgets=[];this.properties={};this.size=[width,300];this.id=1;this.type=this.comfyClass=kind;this.host=document.createElement('section');this.host.style.cssText=`box-sizing:border-box;width:${width}px;padding:15px;background:#152333;color:white`;document.body.append(this.host);}
    addWidget(type,name,value,callback,options){const w={type,name,value,callback,options};this.widgets.push(w);return w;}
    addDOMWidget(name,type,element,options){const h=options.getHeight?.()||50;const slot=document.createElement('div');slot.style.cssText=`box-sizing:border-box;width:100%;height:${h}px;min-width:0;position:relative`;slot.append(element);this.host.append(slot);const w={name,type,element,options,slot};this.widgets.push(w);return w;}
    computeSize(){return [width,80+this.widgets.reduce((n,w)=>n+(w.options?.getMinHeight?.()||20),0)];}
    setSize(size){this.size=size;}setDirtyCanvas(){}
   }
   for(const extension of order)await extension.beforeRegisterNodeDef(Node,{name:kind});
   const node=new Node();node.onNodeCreated();node.onConfigure?.();
   if(node.mangaPanelStatus)node.mangaPanelStatus.textContent='긴상태문자열'.repeat(200);
   if(kind==='MangaReviewDocument') {
    node.widgets.push({name:'edits_json',value:'{}'});
    node.onExecuted({manga_document:[{stage:'target',input_revision:'A',identity_verified:true,page_identity:'page/A',document:{regions:Array.from({length:20},(_,i)=>({id:'r'+i,target:'긴 번역문 '.repeat(200)}))}}]});
   }
   const dom=node.widgets.filter(w=>w.element);
   if(dom.length!==1)throw Error(`${kind}: duplicate panels (${dom.length})`);
   for(const widget of dom){
    const rect=widget.element.getBoundingClientRect(),slot=widget.slot.getBoundingClientRect();
    if(rect.left<slot.left-.1||rect.right>slot.right+.1||rect.top<slot.top-.1||rect.bottom>slot.bottom+.1)throw Error(`${kind}/${width}: DOM escapes allocated slot`);
    if(widget.element.scrollWidth>widget.element.clientWidth+1)throw Error(`${kind}/${width}: horizontal overflow`);
    if(widget.computeSize?.(width)[0]!==0)throw Error('Widget forces node width');
   }
   if(node.mangaPanelBody && kind==='MangaReviewDocument' && node.mangaPanelBody.scrollHeight<=node.mangaPanelBody.clientHeight)throw Error('Review must scroll internally');
   checks.push({kind,width,domWidgets:dom.length});node.host.remove();
  }
  return checks;
 },{nodeCode:code('node_ui.js'),flowCode:code('workflow_execution.js')});
 assert.equal(result.length,30);console.log('PASS: Chromium layout, 30 node/width/extension-order cases; no duplicate panel or slot overflow');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
