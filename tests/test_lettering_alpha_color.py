"""Independent pigment oracle: disabled outlines must not add white edges."""
import numpy as np
import pytest
from tests.test_lettering import core, fixture


@pytest.mark.parametrize('color',[[.42,.42,.42],[.1,.3,.7]])
@pytest.mark.parametrize('supersample',[1,2,4])
@pytest.mark.parametrize('rotation',[0,11])
def test_disabled_outline_preserves_pigment_at_every_alpha(fixture,color,supersample,rotation):
    style={**fixture[3],'foreground':color,'outline_width':0.,'texture_strength':0.,
           'shadow_x':0.,'shadow_y':0.,'shadow_blur':0.}
    layer,alpha,_=core.render_text('색상 확인',style,max_font=42,supersample=supersample,rotation=rotation)
    assert ((alpha>0)&(alpha<1)).any()
    background=np.full_like(layer,.62)
    actual=layer*alpha[...,None]+background*(1-alpha[...,None])
    expected=np.asarray(color)*alpha[...,None]+background*(1-alpha[...,None])
    assert np.max(np.abs(actual-expected))<2e-5
