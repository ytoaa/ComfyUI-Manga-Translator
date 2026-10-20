"""Authored cleanup masks cannot migrate pages, destroy source checks or protection."""
from copy import deepcopy
import base64
import io
import json

import numpy as np
from PIL import Image
import pytest
import torch

from tests.test_page_edit import E, T, fixture
from tests.test_boundary_acceptance import context
from tests.test_project_runner import P, FakeComfy, make_page, graph
from tests.test_canvas_execution import C


def run(patch=None, *, ctx=None, original=None, source=None, data=None, **kwargs):
    rgb, raw, document = fixture()
    rgb = rgb if original is None else original
    raw = raw if source is None else source
    document = document if data is None else data
    return E.MangaPageEditPlan().plan(torch.from_numpy(rgb)[None], json.dumps(document),
        torch.from_numpy(raw)[None], torch.from_numpy(raw)[None],
        review_edits_json=json.dumps(patch or {}), page_context_json=ctx or context(), **kwargs)


def bind(out, edits):
    snap = out['ui']['manga_edit_review'][0]
    return {'pages': {snap['input_revision']: edits},
            'identities': {snap['input_revision']: snap['page_identity']}}


def stroke(mode='add', points=None, radius=8):
    return {'mode':mode, 'radius':radius, 'points':points or [[95,40]]}


def test_brush_adds_missing_cleanup_without_expanding_edit_owner_and_erases_only_halo():
    first = run()
    patch = bind(first, {'r1':{'strokes':[stroke(points=[[105,40]],radius=16)]}})
    out = run(patch)
    raw, mask = (a[0].numpy() > .5 for a in out['result'][1:3])
    assert raw[35:55,35:90].all() and not raw[40,100]
    assert mask[40,100] and not mask[40,108]  # Brush clipped at x=108.
    assert mask.sum() > raw.sum()
    patch['pages'][next(iter(patch['pages']))]['r1']['strokes'].append(stroke('erase',[[80,40]],32))
    erased = run(patch)['result'][2][0].numpy() > .5
    assert erased[35:55,35:90].all() and not erased[40,100]
    assert np.array_equal(erased[80:], mask[80:])  # Other region unchanged.


def test_real_cleanup_finishes_manually_marked_missing_strokes():
    rgb, raw, data = fixture()
    # A second source stroke is missed by the detector. The human adds only
    # this missing part, not the surrounding edit rectangle.
    rgb[37:52,92:100] = 0
    before = run(original=rgb)
    patch = bind(before, {'r1':{'strokes':[stroke(points=[[95,40],[95,49]],radius=5)]}})
    out = run(patch, original=rgb)
    doc, source, cleanup = out['result'][:3]
    plan = T.make_plan(rgb, source[0].numpy(), cleanup[0].numpy(), regions_json=doc)
    final, _ = T.assemble(plan, [])
    assert np.allclose(final[37:52,92:100], .7)
    permitted = plan['cleanup_mask']
    assert np.array_equal(final[~permitted], rgb[~permitted])
    assert not permitted[20,20]  # No rectangular erase permission.


@pytest.mark.parametrize('change',['page','project','pixels','subpixel','source_mask','target','geometry','ownership','policy','input_sha'])
def test_changed_evidence_never_reuses_previous_brush_or_action(change):
    first = run()
    edits = bind(first, {'r1':{'action':'preserve','strokes':[stroke()]}})
    rgb, raw, data = fixture();ctx = context();kwargs = {}
    if change == 'page':ctx = context('project/a/page/2')
    elif change == 'project':ctx = context('project/b/page/1')
    elif change == 'pixels':rgb[0,0] = 0
    elif change == 'subpixel':rgb[0,0] += .000001
    elif change == 'source_mask':raw[40,95] = 1
    elif change == 'target':data['regions'][0]['target'] = '교정'
    elif change == 'geometry':data['regions'][0]['edit_bbox_pixels'][0] += 1
    elif change == 'ownership':data['regions'][0]['source_ownership'] = {'schema':1,'cross_label_alias':True}
    elif change == 'policy':kwargs['source_review_policy'] = 'legacy'
    else:ctx = context(sha='b'*64)
    out = run(edits, ctx=ctx, original=rgb, source=raw, data=data, **kwargs)
    assert json.loads(out['result'][0])['page_edit_plan']['regions'][0]['reason'] != 'manual_source_preservation'
    assert not json.loads(out['result'][4])['brush_edits']
    if change not in ('page','project'):
        assert out['ui']['manga_edit_review'][0]['warnings']
        assert json.loads(out['result'][0])['page_edit_plan']['needs_review']


def test_manual_replace_still_preserves_protected_neighbour_and_ink():
    _, _, data = fixture()
    data['boundary_review'] = {'schema':1,'policy':'preserve_review','needs_review':True,
                               'protected_boxes_pixels':[[100,35,110,50]]}
    first = run(data=data)
    out = run(bind(first, {'r1':{'action':'replace','strokes':[stroke(radius=32)]}}), data=data)
    plan = json.loads(out['result'][0])['page_edit_plan']
    assert plan['regions'][0]['action'] == 'preserve'
    assert plan['regions'][0]['reason'] == 'protected_region_overlap'
    assert not out['result'][2][0,:70].any()


@pytest.mark.parametrize('bad',[stroke(points=[[108,40]]),stroke(points=[[95.5,40]]),
    stroke(radius=True),stroke(radius=33),stroke(mode='fill'),stroke(points=[[95,40]]*257)])
def test_invalid_brush_rejected_before_cleanup(bad):
    patch = bind(run(), {'r1':{'strokes':[bad]}})
    with pytest.raises(ValueError):run(patch)


def test_revision_provenance_cannot_be_modified_after_planning():
    doc = json.loads(run()['result'][0])
    doc['page_edit_review']['selected_edits'] = {'r1':{'action':'replace'}}
    with pytest.raises(ValueError, match='stale'):E.validate(doc,360,160)


def test_standalone_image_ownership_and_png_cards_are_bounded():
    out = run(ctx='{}');snap = out['ui']['manga_edit_review'][0]
    assert snap['page_identity'].startswith('image/')
    for row in snap['regions']:
        assert row['preview_size'][0] <= 320 and row['preview_size'][1] <= 192
        for key in ('image','overlay','source_overlay'):
            picture = Image.open(io.BytesIO(base64.b64decode(row[key].split(',')[1])))
            picture.load();assert list(picture.size) == row['preview_size']
    own = run(bind(out, {'r1':{'action':'preserve'}}),ctx='{}')
    assert json.loads(own['result'][0])['page_edit_plan']['regions'][0]['action'] == 'preserve'


def test_folder_reprocesses_only_the_page_that_owns_cleanup_edits(tmp_path):
    client = FakeComfy()
    for name in ('1.png','2.png'):make_page(tmp_path/'input'/name)
    book = P.Project(tmp_path/'input',tmp_path/'project',graph(),client);book.run()
    edited = graph()
    node = next(n for n in edited.values() if n['class_type']=='MangaPageEditPlan')
    node['inputs']['review_edits_json'] = json.dumps({'pages':{'revision':{'r1':{'action':'preserve'}}},
        'identities':{'revision':f'project/{book.project_id}/page/{book.pages[0]["id"]}'}})
    assert P.workflow_fingerprint(edited) == P.workflow_fingerprint(graph())
    resumed = P.Project(tmp_path/'input',tmp_path/'project',edited,client);resumed._prepare_project()
    engine = C.CanvasExecution()
    assert engine._eligible(resumed,resumed.pages[0],False)
    assert not engine._eligible(resumed,resumed.pages[1],False)
    resumed.run();assert len(client.submissions) == 3
    assert C._run_settings(edited) != C._run_settings(graph())  # Running batches freeze brush edits too.


def test_shipped_workflow_binds_cleanup_review_to_input_page_identity():
    g = graph();load = P.workflow_bindings(g)['load']
    node = next(n for n in g.values() if n['class_type']=='MangaPageEditPlan')
    assert node['inputs']['page_context_json'] == [load,2]
    assert node['inputs']['review_edits_json'] == '{}'
