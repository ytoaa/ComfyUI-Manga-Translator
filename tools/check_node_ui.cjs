/* Execute the shipped node extension in a DOM double: no network or inference. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.style={};this.events={};this.textContent='';this.value='';}
 append(...els){this.children.push(...els);}replaceChildren(){this.children=[];}
 addEventListener(name,fn){this.events[name]=fn;}fire(name){this.events[name]?.();}
}
const document={createElement:tag=>new Element(tag)},listeners=new Map(),nodes=new Map();
const app={graph:{getNodeById:id=>nodes.get(String(id))},registerExtension:e=>app.extension=e};
const api={addEventListener:(name,fn)=>listeners.set(name,fn)};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../web/node_ui.js'),'utf8').replace(/^import .*;$/gm,''),{app,api,document,console});
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
 node.onExecuted({manga_document:[{stage:'target',input_revision:'pageB',document:data}]});
 node.mangaPanelBody.children.find(e=>e.tag==='textarea').value='Other';node.mangaPanelBody.children.find(e=>e.tag==='textarea').fire('input');
 assert.ok(JSON.parse(node.widgets[0].value).pages.pageA);assert.ok(JSON.parse(node.widgets[0].value).pages.pageB);
 for(const w of node.widgets.filter(w=>w.type==='manga_node_panel')){assert.equal(w.serialize,false);assert.equal(w.options.serialize,false);}
 app.extension.setup();listeners.get('manga_model_progress')({detail:{node:'1',index:0,total:6,file:'weights',bytes:2097152}});
 assert.match(node.mangaPanelStatus.textContent,/2.0 MiB/);
 listeners.get('execution_error')({detail:{node_id:'1',exception_message:'Model unavailable'}});assert.match(node.mangaPanelStatus.textContent,/Model unavailable/);
 assert.ok(!node.mangaPanelBody.children.some(e=>e.tag==='img'));
 console.log('PASS: paragraph review, revision-scoped edits, approval preservation, text escaping, model progress and nonserialized UI');
})().catch(e=>{console.error(e);process.exitCode=1;});
