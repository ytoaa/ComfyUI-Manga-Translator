"""ComfyUI boundaries for source-preserving hybrid lettering."""
from . import core, hybrid
from .nodes import image, mask, tensor, field


def save_fit_failure(plan,diagnostic):
    """Small replay metadata; do not serialize page tensors or model masks."""
    import json,logging,uuid
    from pathlib import Path
    try:
        import folder_paths
        rows=[]
        for region in plan['regions']:
            rows.append({key:region[key] for key in ('id','parent_id','source','text','font','cap','floor',
                'fallback_floor','fit_policy','mode','options','phases','frame_quad','profile','bubble_containment')
                if key in region})
        payload={'schema':1,'code':'no_safe_lettering_fit','failure':diagnostic,
            'regions':rows,'page_size':[plan['cleaned'].shape[1],plan['cleaned'].shape[0]],
            'protected_boxes_pixels':plan.get('protected_boxes_pixels',[]),
            'scope':'layout metadata; original pixels, detector masks and OCR source are separate inputs'}
        raw=json.dumps(payload,ensure_ascii=False,allow_nan=False,indent=2)
        if len(raw.encode())>2*1024*1024:raise ValueError('Lettering failure metadata exceeds 2 MiB')
        root=Path(folder_paths.get_output_directory())/'manga_translator'/'lettering_failures'
        root.mkdir(parents=True,exist_ok=True)
        path=root/('lettering_'+uuid.uuid4().hex+'.json')
        path.write_text(raw,encoding='utf-8')
        return str(path)
    except (ImportError,AttributeError,OSError,ValueError,TypeError,KeyError) as exc:
        logging.getLogger(__name__).warning('Lettering diagnostics unavailable: %s',exc)
        return 'unavailable'


class MangaLetterPlan:
    CATEGORY='Manga Translator/스타일 식자'
    DESCRIPTION='원문 크기 상한과 영역 폭에 맞춰 배치합니다. reflow는 단일 줄바꿈을 풀고 가용 폭을 먼저 씁니다. 폰트와 애매한 방향은 직접 지정하세요.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'original':field('IMAGE','지우기 전 원본'),
            'cleaned':field('IMAGE','원문 제거가 끝난 같은 크기 배경'),
            'source_mask':field('MASK','스타일 측정용 원문 획 마스크'),
            'regions_json':field('STRING','MangaLetterPrepare 출력',forceInput=True),
            'default_font':field(list(core.fonts()) or ['NanumGothic-Bold.ttf'],'한글을 지원하는 폰트 선택',default='NanumGothic-Bold.ttf'),
            'mode':field(list(hybrid.MODES),'source=원래 영역에서 축소·재배치, bubble=실제 내부 마스크 안에서 확장, strict=원문 행/열 수 제한',default='source'),
            'direction':field(list(hybrid.DIRECTIONS),'auto는 원문 픽셀의 방향 추정. 영역별 JSON으로 덮어쓸 수 있습니다.',default='auto'),
            'min_font':field('INT','가독성 최소 크기. 맞지 않으면 저장 전에 중단',default=10,min=4,max=128),
            'min_scale':field('FLOAT','원문 기준 최소 축소 비율',default=.55,min=.2,max=1.,step=.05),
            'padding':field('INT','글자·외곽선 여백(px)',default=2,min=0,max=32),
            'region_options_json':field('STRING','영역 ID별 설정. 예: {"r1":{"direction":"vertical_rtl","font_cap":28},"r2":{"rotation":8,"bend":12}}. bend는 수동 곡선(px).',default='{}',multiline=True)},
            'optional':{'oriented_fit':field('BOOLEAN','회전된 로컬 프레임 안에서 맞춘 뒤 페이지로 변환합니다.',default=False),'bubble_mask':field('MASK','선택: 테두리·꼬리·그림을 제외한 실제 말풍선 내부. 자동 검출 마스크보다 우선합니다.'),
                        'detection_result':field('MANGA_DETECTION','선택: RF-DETR의 실제 bubble segmentation을 자동 재사용. 명시적 내부 마스크가 우선합니다.'),
                        'line_breaks':field(list(hybrid.LINE_BREAKS),'preserve=입력 줄바꿈 유지. reflow=단일 줄바꿈을 풀고 가용 폭을 먼저 채움; 빈 줄 문단/strict/세로는 유지.',default='preserve'),
                        'fit_policy':field(list(hybrid.FIT_POLICIES),'readable=원문 비율 제한으로 맞지 않으면 min_font까지 추가 축소. source_ratio/strict/영역별 min_scale은 비율 제한 유지.',default='source_ratio'),
                        'respect_bubbles':field('BOOLEAN','확인된 말풍선의 실제 픽셀 마스크 밖에 글자 알파가 생기면 거부합니다. 단순 사각형 경계와 다릅니다.',default=False),
                        'page_direction':field('STRING','번역문 방향 노드 출력. 가로/세로 통일은 모든 영역의 방향 설정보다 우선합니다.',forceInput=True),
                        'bubble_failure_policy':field(['preserve_review','stop'],'말풍선 소유권이 불확실하면 해당 영역과 겹친 이웃만 원본 복원·검수합니다. stop은 페이지를 중단합니다. require_bubble은 항상 중단합니다.',default='preserve_review')}}
    RETURN_TYPES=('MANGA_LETTER_PLAN','IMAGE','STRING')
    RETURN_NAMES=('식자_계획','배치_검수','계획_보고서')
    FUNCTION='plan'
    def plan(self,original,cleaned,source_mask,regions_json,default_font='NanumGothic-Bold.ttf',
             mode='source',direction='auto',min_font=10,min_scale=.55,padding=2,
             region_options_json='{}',bubble_mask=None,detection_result=None,line_breaks='preserve',fit_policy='source_ratio',
             respect_bubbles=False,page_direction=None,oriented_fit=False,bubble_failure_policy='preserve_review'):
        plan,preview,report=hybrid.build_plan(image(original),image(cleaned),mask(source_mask),regions_json,
            default_font,mode,direction,min_font,min_scale,padding,region_options_json,
            mask(bubble_mask) if bubble_mask is not None else None,detection_result,line_breaks,fit_policy,respect_bubbles,page_direction,oriented_fit,bubble_failure_policy)
        return plan,tensor(preview),report


class MangaLetterApply:
    CATEGORY='Manga Translator/스타일 식자'
    DESCRIPTION='원문 크기 상한·비례 외곽선·영역별 방향·충돌 검사를 적용합니다. 세로쓰기는 CJK 정립, 라틴 회전, 두 자리 숫자 가로 배치, 지원되는 세로 문장부호를 사용합니다.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'plan':field('MANGA_LETTER_PLAN','MangaLetterPlan 출력')}}
    RETURN_TYPES=('IMAGE','MASK','STRING')
    RETURN_NAMES=('최종_페이지','새_글자_알파','식자_보고서')
    FUNCTION='render'
    def render(self,plan):
        import json
        try:result,alpha,report=hybrid.render_plan(plan)
        except hybrid.LetteringFitError as exc:
            path=save_fit_failure(plan,exc.diagnostic)
            raise hybrid.LetteringFitError(str(exc)+'; diagnostics='+path,exc.diagnostic) from None
        diagnostic=json.loads(report)
        return {'ui':{'manga_lettering_report':[diagnostic],
                      'manga_status':[{'state':'needs_review' if diagnostic['needs_review'] else 'completed',
                          'message':f"원본 보존·검수 {len(diagnostic.get('lettering_review',[]))}개 영역" if diagnostic.get('lettering_review') else '식자 완료'}]},
                'result':(tensor(result),tensor(alpha),report)}
