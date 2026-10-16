"""ComfyUI boundaries for source-preserving hybrid lettering."""
from . import core, hybrid
from .nodes import image, mask, tensor, field


class MangaLetterPlan:
    CATEGORY='Manga Translator/스타일 식자'
    DESCRIPTION='원문 크기를 상한으로 축소 → 줄바꿈 → 검증된 말풍선 내부 확장을 계획합니다. 원문 폰트를 복제하지 않으며 폰트와 애매한 방향은 직접 지정하세요.'
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
            'optional':{'bubble_mask':field('MASK','선택: 테두리·꼬리·그림을 제외한 실제 말풍선 내부. 없으면 영역 확장하지 않습니다.'),
                        'detection_result':field('MANGA_DETECTION','선택: RF-DETR의 실제 bubble segmentation을 자동 재사용. 명시적 내부 마스크가 우선합니다.')}}
    RETURN_TYPES=('MANGA_LETTER_PLAN','IMAGE','STRING')
    RETURN_NAMES=('식자_계획','배치_검수','계획_보고서')
    FUNCTION='plan'
    def plan(self,original,cleaned,source_mask,regions_json,default_font='NanumGothic-Bold.ttf',
             mode='source',direction='auto',min_font=10,min_scale=.55,padding=2,
             region_options_json='{}',bubble_mask=None,detection_result=None):
        plan,preview,report=hybrid.build_plan(image(original),image(cleaned),mask(source_mask),regions_json,
            default_font,mode,direction,min_font,min_scale,padding,region_options_json,
            mask(bubble_mask) if bubble_mask is not None else None,detection_result)
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
        result,alpha,report=hybrid.render_plan(plan)
        return tensor(result),tensor(alpha),report
