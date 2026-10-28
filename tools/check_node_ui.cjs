/* Execute the shipped node extension in a DOM double: no network or inference. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.style={};this.events={};this.textContent='';this.value='';}
 append(...els){this.children.push(...els);}replaceChildren(){this.children=[];}
 addEventListener(name,fn){this.events[name]=fn;}fire(name,event={}){this.events[name]?.(event);}
}
const rasterCalls=[];
const context2d=new Proxy({}, {get:(_,name)=>(...args)=>rasterCalls.push([name,...args])});
Element.prototype.getContext=undefined;
const makeElement=tag=>{
 const e=new Element(tag);
 if(tag==='canvas'){
  e.getContext=()=>context2d;e.setPointerCapture=()=>{};
  e.getBoundingClientRect=()=>({left:10,top:20,width:200,height:100});
 }return e;
};
class PreviewImage {set src(value){this.onload?.();}}
const document={createElement:makeElement},listeners=new Map(),nodes=new Map();
const app={graph:{getNodeById:id=>nodes.get(String(id))},registerExtension:e=>app.extension=e};
const api={addEventListener:(name,fn)=>listeners.set(name,fn)};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../web/node_ui.js'),'utf8').replace(/^import .*;$/gm,''),{app,api,document,console,TextEncoder,Image:PreviewImage});
class Node {
 constructor(id){this.id=id;this.widgets=[{name:'edits_json',value:'{}'}];nodes.set(String(id),this);}
 addDOMWidget(name,type,element,options){const w={name,type,element,options};this.widgets.push(w);return w;}
 setDirtyCanvas(){}
}
(async()=>{
 await app.extension.beforeRegisterNodeDef(Node,{name:'MangaReviewDocument'});
 const node=new Node(1);node.onNodeCreated();
 const data={regions:[{id:'r1',source:'Original',target:'Title\n\nBody',blocks:[{id:'b1',role:'heading',source:'Heading',target:'Title'},{id:'b2',role:'body',source:'Body',target:'Body'}]}]};
 const snapshot={stage:'target',input_revision:'pageA',page_identity:'project/a/page/1',identity_verified:true,document:data};
 node.onExecuted({manga_document:[snapshot]});
 const fields=node.mangaPanelBody.children.filter(e=>e.tag==='textarea');assert.equal(fields.length,2);
 fields[1].value='수정 <img src=x>';fields[1].fire('input');
 node.mangaPanelBody.children.find(e=>e.tag==='button').fire('click');
 const edits=JSON.parse(node.widgets[0].value);assert.equal(edits.pages.pageA.r1.blocks[1].target,'수정 <img src=x>');assert.equal(edits.pages.pageA.r1.target,undefined);
 assert.equal(edits.identities.pageA,'project/a/page/1');
 node.onExecuted({manga_document:[snapshot]});
 assert.equal(node.mangaPanelBody.children.filter(e=>e.tag==='textarea')[1].value,'수정 <img src=x>');
 const longNode=new Node(2);longNode.onNodeCreated();
 const longData=JSON.parse(JSON.stringify(data));
 for(const b of longData.regions[0].blocks)b.target='가'.repeat(1024);
 longData.regions[0].target=longData.regions[0].blocks.map(b=>b.target).join('\n\n');
 longNode.onExecuted({manga_document:[{...snapshot,input_revision:'longPage',document:longData}]});
 longNode.mangaPanelBody.children.find(e=>e.tag==='button').fire('click');
 const approved=JSON.parse(longNode.widgets[0].value).pages.longPage.r1;
 assert.equal(approved.blocks.length,2);assert.equal(approved.blocks[0].target.length,1024);
 assert.equal(approved.target,undefined);
 node.onExecuted({manga_document:[{stage:'target',input_revision:'pageB',document:data}]});
 node.mangaPanelBody.children.find(e=>e.tag==='textarea').value='Other';node.mangaPanelBody.children.find(e=>e.tag==='textarea').fire('input');
 assert.ok(JSON.parse(node.widgets[0].value).pages.pageA);assert.ok(JSON.parse(node.widgets[0].value).pages.pageB);
 for(const w of node.widgets.filter(w=>w.type==='manga_node_panel')){assert.equal(w.serialize,false);assert.equal(w.options.serialize,false);}
 class EditNode extends Node {}
 await app.extension.beforeRegisterNodeDef(EditNode,{name:'MangaPageEditPlan'});
 const editNode=new EditNode(3);editNode.widgets=[{name:'review_edits_json',value:'{}'}];editNode.onNodeCreated();
 const editSnapshot={input_revision:'maskA',page_identity:'project/a/page/1',regions:[{id:'r1',action:'replace',reason:'translated_region',source:'<img src=x>',target:'본문',bbox_pixels:[10,10,110,60],preview_size:[100,50]}]};
 editNode.onExecuted({manga_edit_review:[editSnapshot]});
 const card=editNode.mangaPanelBody.children.find(e=>e.children.some(q=>q.tag==='select'));
 const select=card.children.find(e=>e.tag==='select');select.value='preserve';select.fire('change');
 const owned=JSON.parse(editNode.widgets[0].value);assert.equal(owned.pages.maskA.r1.action,'preserve');assert.equal(owned.identities.maskA,'project/a/page/1');
 const canvas=card.children.find(e=>e.tag==='canvas');
 canvas.fire('pointerdown',{clientX:110,clientY:70,pointerId:1,button:0});
 canvas.fire('pointermove',{clientX:400,clientY:200});canvas.fire('pointerup');
 const brush=JSON.parse(editNode.widgets[0].value).pages.maskA.r1.strokes[0];
 assert.deepEqual(brush,{mode:'add',radius:8,points:[[60,35],[109,59]]});
 assert.ok(rasterCalls.some(c=>c[0]==='scale'&&c[1]===1&&c[2]===1));
 const buttons=card.children.find(e=>e.children.some(q=>q.tag==='button')).children.filter(e=>e.tag==='button');
 buttons[0].fire('click');assert.equal(JSON.parse(editNode.widgets[0].value).pages.maskA.r1.strokes.length,0);
 buttons[1].fire('click');assert.deepEqual(JSON.parse(editNode.widgets[0].value).pages.maskA.r1,{});
 editNode.onExecuted({manga_edit_review:[{...editSnapshot,input_revision:'maskB',page_identity:'project/a/page/2'}]});
 assert.ok(JSON.parse(editNode.widgets[0].value).pages.maskA);assert.ok(!JSON.parse(editNode.widgets[0].value).pages.maskB);
 assert.ok(!card.children.some(e=>e.tag==='img'));
 // Valid JSON with array containers used to say "saved" while JSON.stringify
 // silently discarded named revision properties. Keep the raw input unchanged.
 for(const invalid of ['[]','{"pages":[]}','{"pages":true}','{"pages":{"pageA":[]}}','{"identities":[]}']) {
  node.widgets[0].value=invalid;
  node.onExecuted({manga_document:[snapshot]});
  const field=node.mangaPanelBody.children.find(e=>e.tag==='textarea');
  if(field){field.value='must not disappear';field.fire('input');}
  assert.equal(node.widgets[0].value,invalid);
  assert.match(node.mangaPanelStatus.textContent,/확인 필요/);
 }
 for(const invalid of ['[]','{"pages":[]}','{"pages":true}','{"pages":{"maskA":[]}}','{"identities":[]}']) {
  editNode.widgets[0].value=invalid;
  editNode.onExecuted({manga_edit_review:[editSnapshot]});
  const c=editNode.mangaPanelBody.children.find(e=>e.children.some(q=>q.tag==='select'));
  const control=c?.children.find(e=>e.tag==='select');
  if(control){control.value='preserve';control.fire('change');}
  assert.equal(editNode.widgets[0].value,invalid);
  assert.match(editNode.mangaPanelStatus.textContent,/확인 필요/);
 }
 const failedReport={regions:[],lettering_review:[{id:'r7',reason:'unsupported_translation_glyphs',diagnostic:{missing_characters:['ل','<img src=x>']}}]};
 editNode.onExecuted({manga_lettering_report:[failedReport]});
 assert.match(editNode.mangaPanelBody.children[0].textContent,/r7.*폰트.*ل.*<img src=x>/);
 assert.ok(!editNode.mangaPanelBody.children.some(e=>e.tag==='img'));
 editNode.onExecuted({manga_lettering_report:[{regions:[{id:'r1'}]}]});
 assert.equal(editNode.mangaPanelBody.children[0].textContent,'식자 1영역');
 editNode.onExecuted({manga_lettering_report:[{regions:[],lettering_review:[{id:'r1',reason:'source_below_readability_minimum',diagnostic:{code:'source_below_readability_minimum',source_cap:6,minimum_font:10}}]}]});
 assert.match(editNode.mangaPanelBody.children[0].textContent,/r1.*6px < 최소 10px/);
 for(const kind of ['MangaWorkflowInput','MangaReviewDocument','MangaPageEditPlan','MangaOCRAdaptive','MangaLetterPlan','MangaLetterApply']) {
  class SizingNode {
   constructor(){this.widgets=[];this.size=[420,600];}
   addDOMWidget(name,type,element,options){const w={name,type,element,options};this.widgets.push(w);return w;}
   computeSize(){return [300,400];}setSize(size){this.size=size;}
  }
  await app.extension.beforeRegisterNodeDef(SizingNode,{name:kind});
  const sizing=new SizingNode();sizing.onNodeCreated();sizing.onConfigure();
  const views=sizing.widgets.filter(w=>w.type==='manga_node_panel');
  assert.equal(views.length,kind==='MangaWorkflowInput'?0:1);
  assert.deepEqual(Array.from(sizing.size),[420,600]);
  for(const view of views){
   const h=kind==='MangaReviewDocument'?300:kind==='MangaPageEditPlan'?420:104;
   assert.equal(view.options.getHeight(),h);assert.equal(view.options.getMinHeight(),h);assert.equal(view.options.getMaxHeight(),h);
   assert.equal(view.computeSize(240)[0],0);assert.equal(view.computeSize(240)[1],h);
   assert.match(view.element.style.cssText,/max-width:100%/);assert.match(sizing.mangaPanelBody.style.cssText,/overflow:auto/);
   sizing.onExecuted({manga_status:[{state:'needs_review',message:'보존 검수'}]});assert.match(sizing.mangaPanelStatus.textContent,/검수 필요/);
  }
 }
 app.extension.setup();listeners.get('manga_model_progress')({detail:{node:'1',index:0,total:6,file:'weights',bytes:2097152}});
 assert.match(node.mangaPanelStatus.textContent,/2.0 MiB/);
 listeners.get('execution_error')({detail:{node_id:'1',exception_message:'Model unavailable'}});assert.match(node.mangaPanelStatus.textContent,/Model unavailable/);
 assert.ok(!node.mangaPanelBody.children.some(e=>e.tag==='img'));
 console.log('PASS: paragraph review, revision-scoped edits, approval preservation, text escaping, model progress, bounded panel sizing and nonserialized UI');
})().catch(e=>{console.error(e);process.exitCode=1;});
