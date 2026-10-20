"""Mixed-folder 08 simulation: real custom nodes/fonts, explicit model/API doubles."""
from argparse import ArgumentParser
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path

from PIL import Image

from run_project import Project, scan_images, workflow_bindings, DEFAULT_WORKFLOW, read_json
import simulate_integrated as S


SCENARIOS = {
    'chapter/1.png': 'normal',
    'chapter/2.png': 'recovered_seam',
    'chapter/3.png': 'unresolved_seam',
    'chapter/4.png': 'ocr_repetition',
    'chapter/5.png': 'unchanged_cleanup',
    'chapter/6.png': 'impossible_lettering',
    'chapter/7.png': 'no_selected_text',
    'chapter/8.png': 'uniform_blank',
    'chapter/9.png': 'corrupt_input',
    'chapter/10.png': 'normal_after_failures',
    'extra/1.png': 'duplicate_basename',
}


def number_slot_probe():
    """Measure a known layout gap with real font alpha, without any OCR model."""
    from integrated_simulation.lettering import core, hybrid
    import numpy as np
    from PIL import ImageDraw, ImageFont
    clean = Image.new('RGB',(360,140),'#eee8db')
    draw = ImageDraw.Draw(clean)
    draw.rectangle((22,35,57,92),fill='#777777')
    font = ImageFont.truetype(core.font_path('NanumGothic-Bold.ttf','1'),24)
    draw.text((32,43),'1',font=font,fill='white')
    original = clean.copy(); draw = ImageDraw.Draw(original)
    font = ImageFont.truetype(core.font_path('NanumGothic-Bold.ttf','BODY'),20)
    draw.multiline_text((82,35),'BODY TEXT LINE\nANOTHER BODY LINE',font=font,fill='black',spacing=8)
    a,b = np.asarray(original,np.float32)/255,np.asarray(clean,np.float32)/255
    mask = (np.max(np.abs(a-b),axis=2)>.05).astype(np.float32)
    doc = json.dumps({'schema':1,'coordinate_format':'xywh','page_size':[360,140],
        'regions':[{'id':'numbered','bbox':[18,23,320,85],
                    'source_text':'BODY TEXT LINE\nANOTHER BODY LINE',
                    'text':'본문 번역을 같은 칸 안에 배치합니다.'}]})
    plan,_,_ = hybrid.build_plan(a,b,mask,doc,line_breaks='reflow',fit_policy='readable',min_font=10)
    _,alpha,_ = hybrid.render_plan(plan)
    overlap = int(np.count_nonzero(alpha[35:93,22:58]>.01))
    return {'scenario':'number_slot_inside_shared_frame',
            'status':'known_limitation' if overlap else 'protected',
            'translated_alpha_pixels_inside_preserved_marker':overlap,
            'scope':'real_CPU_font_pixels_not_model_inference'}


def runner_for(name, destination):
    options = ({'seam_case':True,'require_recovery':True} if name == 'recovered_seam' else
               {'seam_case':True,'failed_recovery':True} if name == 'unresolved_seam' else
               {'uniform_fill':False,'failed_qwen':True} if name == 'unchanged_cleanup' else
               {'no_text':True} if name in ('uniform_blank','no_selected_text') else {})
    runner = S.GraphRunner(destination, **options)
    if name == 'uniform_blank':
        runner.original = Image.new('RGB', runner.original.size, 'white')
        runner.clean = runner.original.copy()
        runner.detector = S.DetectorOracle([],runner.original)
        runner.ocr = S.OCROracle(runner.original,[])
    if name == 'ocr_repetition':
        class Repeated:
            calls = 0
            def ocr(self,*args,**kwargs):
                self.calls += 1
                return {'text':'顔の集の集の集の集の集落'}
        runner.ocr = Repeated()
    if name == 'impossible_lettering':
        runner.records[0]['target'] = '번역문이 영역보다 매우 깁니다. '*50
    return runner


class SimulatedServer:
    """The standard project runner sees API-shaped data from actual graph runs."""
    base = 'simulation://explicit-api-and-model-doubles'
    def __init__(self, cases):
        self.cases, self.uploads, self.jobs, self.submissions = cases, {}, {}, 0
        self.graph_reports = {}
    def object_info(self):
        return {node['class_type']:{} for node in read_json(DEFAULT_WORKFLOW).values()}
    def upload(self, data, name, subfolder):
        self.uploads[subfolder+'/'+name] = data
        return {'name':name,'subfolder':subfolder,'type':'input'}
    def submit(self, prompt, ident, token):
        self.submissions += 1
        name, runner = self.cases[token['page']]
        runner.graph = deepcopy(prompt)
        binding = workflow_bindings(prompt)
        encoded = self.uploads[prompt[binding['load']]['inputs']['image']]
        assert Image.open(BytesIO(encoded)).convert('RGB').tobytes() == runner.original.tobytes()
        try:
            report = runner.execute()
            status = {'status_str':'success','completed':True,'messages':[]}
        except ValueError as exc:
            expected = {'unresolved_seam':'unresolved clipped text','ocr_repetition':'short_repetition',
                        'unchanged_cleanup':'retained nearly all source ink','impossible_lettering':'no safe lettering fit'}
            assert name in expected and expected[name] in str(exc), (name,str(exc))
            status = {'status_str':'error','completed':False,'messages':[['execution_error',{
                'exception_type':type(exc).__name__,'exception_message':str(exc),
                'node_type':list(runner.calls)[-1]}]]}
            report = {'expected_failure':True,'message':str(exc),'final_saved':False}
        self.graph_reports[name] = {'scenario':name,'detector_calls':runner.detector.calls,
            'ocr_calls':runner.ocr.calls,'qwen_calls':runner.qwen_calls,
            'final_saved':bool(runner.saved),'simulation_only':True,
            'rendered_regions':len(report.get('lettering',{}).get('regions',[])),
            'preserved_lettering_regions':len(report.get('lettering',{}).get('lettering_review',[])),
            **{key:report[key] for key in ('outside_mask_unchanged','selected_regions','expected_failure','needs_review') if key in report}}
        self.jobs[ident] = {'history':{'outputs':deepcopy(runner.ui_outputs),'status':status},
                            'image':runner.saved[0].read_bytes() if runner.saved else None,
                            'descriptor':runner.ui_outputs.get(binding['final'],{}).get('images',[None])[0]}
        return {'prompt_id':ident,'number':self.submissions,'node_errors':{}}
    def history(self, ident): return self.jobs[ident]['history'] if ident in self.jobs else None
    def queue(self): return {'queue_running':[],'queue_pending':[]}
    def download(self, descriptor):
        return next(job['image'] for job in self.jobs.values() if job['descriptor']==descriptor)


def simulate(destination):
    destination = Path(destination).resolve()
    if (destination/'project/project.json').exists():
        raise ValueError('Use a new simulation destination; existing project evidence is preserved')
    inputs = destination/'inputs'
    traces = destination/'graph-traces'
    prepared = {}
    for relative, name in SCENARIOS.items():
        path = inputs/relative; path.parent.mkdir(parents=True,exist_ok=True)
        if name == 'corrupt_input': path.write_bytes(b'not an image'); continue
        runner = runner_for(name,traces/name)
        runner.original.save(path)
        prepared[relative] = (name,runner)
    cases = {page['id']:prepared[page['relative_path']] for page in scan_images(inputs)
             if page['relative_path'] in prepared}
    server = SimulatedServer(cases)
    project = Project(inputs,destination/'project',read_json(DEFAULT_WORKFLOW),server)
    report = project.run()
    assert report['counts'] == {'completed':4,'failed':2,'needs_review':4,'unchanged_blank':1}
    assert server.submissions == 10
    expected = {'unresolved_seam':'needs_review','ocr_repetition':'needs_review','unchanged_cleanup':'failed',
                'impossible_lettering':'needs_review','corrupt_input':'failed',
                'no_selected_text':'needs_review','uniform_blank':'unchanged_blank'}
    for page in report['pages']:
        name = SCENARIOS[page['relative_path']]
        assert page['status'] == expected.get(name,'completed')
        if page['status'] == 'failed': assert 'result' not in page
    assert server.graph_reports['unresolved_seam']['selected_regions']==2
    assert server.graph_reports['unresolved_seam']['final_saved']
    assert server.graph_reports['ocr_repetition']['qwen_calls'] == 0
    unfit=server.graph_reports['impossible_lettering']
    assert unfit['final_saved'] and unfit['needs_review']
    assert unfit['preserved_lettering_regions']==1 and unfit['rendered_regions']==5
    assert server.graph_reports['ocr_repetition']['final_saved'] and server.graph_reports['ocr_repetition']['needs_review']
    rejected=next(p for p in report['pages'] if SCENARIOS[p['relative_path']]=='ocr_repetition')
    assert Image.open(destination/'project'/rejected['result']).convert('RGB').tobytes()==prepared[rejected['relative_path']][1].original.tobytes()
    assert server.graph_reports['uniform_blank']['ocr_calls'] == server.graph_reports['uniform_blank']['qwen_calls'] == 0
    assert project.run()['counts'] == report['counts'] and server.submissions == 10
    summary = {'simulation_only':True,'model_inference':'RF-DETR/Hayai/vLLM/Qwen replaced by explicit doubles',
               'pipeline':'shipped 08 API graph + real nodes, CPU tensors, fonts, masks and file writes',
               'counts':report['counts'],'submitted_pages':10,'resume_extra_submissions':0,
               'page_order':[p['relative_path'] for p in report['pages']],
               'layout_boundary_probe':number_slot_probe(),
               'scenarios':list(server.graph_reports.values()),
               'known_limits':['styled_cover_auto_detection_unresolved',
                   'number_gutter_not_separately_protected','mixed_heading_layout_requires_refinement',
                   'model_semantic_accuracy_not_verified','no_cross_page_translation_context']}
    path = destination/'simulation-summary.json'
    path.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(path),'counts':report['counts'],'resume_extra_submissions':0},ensure_ascii=False))
    return summary


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--destination',required=True)
    simulate(parser.parse_args().destination)
