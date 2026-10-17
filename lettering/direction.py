"""Book-wide output direction; independent of source OCR orientation."""

POLICIES = {
    '가로 통일': 'horizontal',
    '세로 통일 · 오른쪽 열부터': 'vertical_rtl',
    '세로 통일 · 왼쪽 열부터': 'vertical_ltr',
    '원문 따라 자동': 'auto',
}


def resolve(value):
    if not isinstance(value, str) or value not in POLICIES:
        raise ValueError('올바른 번역문 방향을 선택하세요: 가로 통일 / 세로 통일 / 원문 따라 자동')
    return POLICIES[value]


class MangaLetteringDirection:
    CATEGORY = 'Manga Translator/스타일 식자'
    DESCRIPTION = '폴더 전체의 번역문 방향을 선택합니다. 식자에만 연결하므로 방향 변경이 검출·OCR·번역·제거의 캐시를 무효화하지 않습니다.'
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'lettering_direction': (list(POLICIES), {'default': '가로 통일',
            'tooltip': '가로/세로 통일은 영역별 방향 설정보다 우선합니다. 원문 OCR 방향은 바꾸지 않습니다.'})}}
    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('번역문_방향',)
    FUNCTION = 'select'

    def select(self, lettering_direction='가로 통일'):
        return (resolve(lettering_direction),)
