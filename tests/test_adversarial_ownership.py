"""Adversarial geometry with independently known pixel ownership."""
from copy import deepcopy
import numpy as np
import pytest
import torch
from tools.simulate_ownership_scenarios import module, encode_mask
S = module('source_partition')

@pytest.mark.parametrize('axis',[0,1])
@pytest.mark.parametrize('gap',[0,1,2,3])
@pytest.mark.parametrize('background',[0.,.35,1.])
def test_ocr_isolation_does_not_admit_neighbor_at_owner_edge(axis,gap,background):
    page=torch.full((1,40,60,3),background)
    ink=1-background
    page[:,10:20,10:15]=ink
    page[:,10:20,30+gap:33+gap]=ink
    owner=np.zeros((40,60),bool);owner[:,:30]=True
    if axis:
        page=page.transpose(1,2).contiguous();owner=owner.T
    h,w=owner.shape
    raw,_=encode_mask(owner,0,0)
    before=page.clone()
    output,allowed=S.isolate_crop(page,raw,[0,0,w,h],w,h)
    assert torch.equal(page,before)
    assert np.array_equal(allowed,owner)
    assert output[0,torch.from_numpy(~owner)].eq(background).all()
    assert torch.equal(output[0,torch.from_numpy(owner)],page[0,torch.from_numpy(owner)])

@pytest.mark.parametrize('seed',range(100))
def test_random_partition_preserves_each_pixel_exactly_once_and_inputs(seed):
    rng=np.random.default_rng(seed);h=int(rng.integers(30,100));w=int(rng.integers(40,120));cut=w//2
    source=rng.random((h,w))<.08
    source[:,cut-1:cut+1]=False
    m,b=encode_mask(source,0,0)
    item={'label':'text','bbox':b,'score':.9,'mask':m}
    bubbles=[]
    for left,right in [(0,cut),(cut,w)]:
        mask,box=encode_mask(np.ones((h,right-left),bool),left,0)
        bubbles.append({'label':'bubble','bbox':box,'mask':mask})
    before=deepcopy((item,bubbles))
    for owners in (bubbles,list(reversed(bubbles)),bubbles+bubbles):
        parts,audit=S.partition_by_bubbles([item],owners,w,h)
        accumulated=np.zeros((h,w),np.int32)
        assert len(parts)==2
        for part in parts:
            decoded,(x,y,a,c)=S._decode_mask(part['mask'],w,h)
            accumulated[y:y+c,x:x+a]+=decoded.astype(np.int32)
        assert np.array_equal(accumulated,source.astype(np.int32))
    assert (item,bubbles)==before

@pytest.mark.parametrize('hole_size',[1,2,3,4,7])
@pytest.mark.parametrize('background',[0.,.35,1.])
def test_small_excluded_holes_are_not_filled_by_ocr_support(hole_size,background):
    owner=np.ones((40,60),bool)
    owner[15:15+hole_size,25:25+hole_size]=False
    page=torch.full((1,40,60,3),background)
    page[0,torch.from_numpy(~owner)]=1-background
    page[:,5:10,5:10]=1-background
    raw,_=encode_mask(owner,0,0)
    output,allowed=S.isolate_crop(page,raw,[0,0,60,40],60,40)
    assert np.array_equal(allowed,owner)
    assert output[0,torch.from_numpy(~owner)].eq(background).all()
    assert torch.equal(output[:,5:10,5:10],page[:,5:10,5:10])

@pytest.mark.parametrize('edge',['left','right','top','bottom'])
def test_clipped_bubble_interior_does_not_certify_source(edge):
    m,b=encode_mask(np.ones((10,10),bool),15,15)
    item={'label':'text','bbox':b,'mask':m}
    mask,box=encode_mask(np.ones((30,30),bool),5,5)
    bubble={'mask':mask,'bbox':box,'tile_provenance':{'clipped_edges':[edge]}}
    result,audit=S.partition_by_bubbles([item],[bubble],100,100)
    assert result==[item] and not audit
