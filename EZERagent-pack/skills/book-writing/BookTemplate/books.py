"""
책별 메타 + 챕터 매핑의 단일 진실 원천.

`convert_manuscript.py` 와 `build_book.py` 가 함께 import 합니다.

각 책 항목 구조:
    title        : 표지·헤더에 들어갈 책 제목
    subtitle     : 표지 부제 (없으면 "")
    author       : 표지 저자
    pdf_filename : 빌드 결과 PDF 기본 파일명
    chapters     : 챕터 매핑 리스트. 각 원소는 7-tuple:
        (source_filename, output_filename, label, number, title, verse, verse_ref)

        source_filename = None 인 경우 = 손으로 유지하는 파일.
            convert_manuscript.py 가 스킵하지만, build_book.py 는 파일이
            content/ 에 존재하면 빌드 순서에 포함합니다. (예: 목차)

        label / number / title 등도 None 가능(손으로 유지하는 행에서만).
"""

BOOKS = {
    "soccer-mission-book": {
        "title": "축구가 선교가 되다",
        "subtitle": "스포츠 문화로서 축구 선교 활동이 교회에 미치는 영향",
        "author": "김태진 박사 저",
        "pdf_filename": "축구가_선교가_되다.pdf",
        # overlay_text=False: 표지 이미지에 제목·저자가 이미 그려져 있어 템플릿 텍스트를 끔
        # half_title=True: 표지 다음에 부제를 담은 속표지(반표제지) 페이지를 삽입
        "cover": {
            "mode": "image",
            "image": "cover.png",
            "overlay_text": False,
            "half_title": True,
            "half_title_label": "· 선 교 ·",
        },
        "chapters": [
            # 손으로 유지(추천사): 속표지 다음, 책 맨 앞에 배치
            (None,                 "00_02_추천사.md",                      None,         None,     None,                                  None, None),
            # 손으로 유지(지은이 소개): 추천사 다음, 본문 맨 앞에 배치
            (None,                 "00_00_지은이소개.md",                  None,         None,     None,                                  None, None),
            ("00-abstract.md",     "00_0_초록.md",                         "ABSTRACT",   "&nbsp;", "초 록",                              "", ""),
            ("00b-abstract-en.md", "00_0a_Abstract.md",                    "ABSTRACT",   "&nbsp;", "Abstract",                           "", ""),
            # 손으로 유지(목차): convert 가 스킵하고 build 는 파일이 있으면 포함
            (None,                 "00_목차.md",                           None,         None,     None,                                  None, None),
            # 손으로 유지(머리말): 목차 다음, 본문(1장) 앞에 배치
            (None,                 "00_05_머리말.md",                      None,         None,     None,                                  None, None),
            ("01-collapse.md",     "01_장_무너지는_교회_앞에서.md",        "CHAPTER",    "1",      "무너지는 교회 앞에서",               "", ""),
            ("02-sport.md",        "02_장_스포츠라는_문화.md",             "CHAPTER",    "2",      "스포츠라는 문화",                    "", ""),
            ("03-culture.md",      "03_장_문화로_전하는_복음.md",          "CHAPTER",    "3",      "문화로 전하는 복음",                 "", ""),
            ("04-incarnation.md",  "04_장_성육신과_선교적_교회.md",        "CHAPTER",    "4",      "성육신과 선교적 교회",               "", ""),
            ("05-soccer.md",       "05_장_세상이_사랑하는_게임.md",        "CHAPTER",    "5",      "세상이 사랑하는 게임",               "", ""),
            ("06-mission.md",      "06_장_축구가_선교가_되다.md",          "CHAPTER",    "6",      "축구가 선교가 되다",                 "", ""),
            ("07-fellow.md",       "07_장_함께_뛴_사람들.md",              "CHAPTER",    "7",      "함께 뛴 사람들",                     "", ""),
            ("08-missional.md",    "08_장_선교적_교회와_축구.md",          "CHAPTER",    "8",      "선교적 교회와 축구",                 "", ""),
            ("09-method.md",       "09_장_연구의_길.md",                   "CHAPTER",    "9",      "연구의 길",                          "", ""),
            ("10-voices.md",       "10_장_현장의_이야기.md",               "CHAPTER",    "10",     "현장의 이야기",                      "", ""),
            ("11-numbers.md",      "11_장_숫자가_말하는_것.md",            "CHAPTER",    "11",     "숫자가 말하는 것",                   "", ""),
            ("12-answers.md",      "12_장_일곱_가지_질문에_답하다.md",     "CHAPTER",    "12",     "일곱 가지 질문에 답하다",            "", ""),
            ("13-next.md",         "13_장_다음_세대로_이어지는_발걸음.md", "CHAPTER",    "13",     "다음 세대로 이어지는<br>발걸음",     "", ""),
            ("14-forward.md",      "14_장_책을_닫으며.md",                 "CHAPTER",    "14",     "책을 닫으며<br>— 더 멀리 차는 공",   "", ""),
            ("98-appendix.md",     "15_부록.md",                           "APPENDIX",   "&nbsp;", "부 록",                              "", ""),
            ("99-references.md",   "16_참고문헌.md",                       "REFERENCES", "&nbsp;", "참고문헌",                           "", ""),
        ],
    },

    # ===== 스포츠선교학개론 — 「축구가 선교가 되다」 후속 개론서 (김태진) =====
    "sports-mission-intro": {
        "title": "스포츠선교학개론",
        "subtitle": "문화로서의 스포츠 선교, 그리고 축구선교학",
        "author": "김태진 박사 저",
        "pdf_filename": "스포츠선교학개론.pdf",
        # 정식 표지: Higgsfield 원화(A2 새벽 햇살 들판)에 제목·저자 타이포를 각인한 완성 이미지
        # overlay_text=False: 표지 이미지에 제목·저자가 이미 그려져 있어 템플릿 텍스트를 끔
        "cover": {
            "mode": "image",
            "image": "sports-mission-intro-cover.png",
            "overlay_text": False,
            "half_title": True,
            "half_title_label": "· 스포츠 선교학 ·",
        },
        "chapters": [
            ("00-preface.md",          "00_1_여는_글.md",                    "PREFACE",    "&nbsp;", "여는 글",                            "", ""),
            ("01-culture.md",          "01_장_문화란_무엇인가.md",           "CHAPTER",    "1",      "문화란 무엇인가",                    "", ""),
            ("02-sport.md",            "02_장_스포츠란_무엇인가.md",         "CHAPTER",    "2",      "스포츠란 무엇인가",                  "", ""),
            ("03-mission.md",          "03_장_선교란_무엇인가.md",           "CHAPTER",    "3",      "선교란 무엇인가",                    "", ""),
            ("04-theology.md",         "04_장_신학이란_무엇인가.md",         "CHAPTER",    "4",      "신학이란 무엇인가",                  "", ""),
            ("05-sportsmissiology.md", "05_장_스포츠선교학이란_무엇인가.md", "CHAPTER",    "5",      "스포츠선교학이란<br>무엇인가",       "", ""),
            ("06-bible-body.md",       "06_장_성경_속의_몸과_경기.md",       "CHAPTER",    "6",      "성경 속의 몸과 경기",                "", ""),
            ("07-incarnation.md",      "07_장_성육신과_선교적_교회.md",      "CHAPTER",    "7",      "성육신과 선교적 교회",               "", ""),
            ("08-ethics.md",           "08_장_스포츠선교의_정당성과_윤리.md","CHAPTER",    "8",      "스포츠선교의<br>정당성과 윤리",      "", ""),
            ("09-soccer.md",           "09_장_축구란_무엇인가.md",           "CHAPTER",    "9",      "축구란 무엇인가<br>— 세상이 사랑하는 게임", "", ""),
            ("10-soccermissiology.md", "10_장_축구선교학이란_무엇인가.md",   "CHAPTER",    "10",     "축구선교학이란<br>무엇인가",         "", ""),
            ("11-identity.md",         "11_장_축구인_선교인_축구선교인.md",  "CHAPTER",    "11",     "축구인 · 선교인 ·<br>축구선교인",    "", ""),
            ("12-field.md",            "12_장_축구선교의_현장.md",           "CHAPTER",    "12",     "축구선교의 현장<br>— 사례와 간증",   "", ""),
            ("13-method.md",           "13_장_스포츠선교의_방법론과_사역_모델.md", "CHAPTER", "13",  "스포츠선교의<br>방법론과 사역 모델", "", ""),
            ("14-future.md",           "14_장_다음_세대와_스포츠선교의_미래.md",   "CHAPTER", "14",  "다음 세대와<br>스포츠선교의 미래",   "", ""),
            ("98-glossary.md",         "15_용어정리.md",                     "APPENDIX",   "&nbsp;", "용어 정리",                          "", ""),
            ("99-references.md",       "16_참고문헌.md",                     "REFERENCES", "&nbsp;", "참고문헌",                           "", ""),
        ],
    },

    # ===== 하베스 미용그룹 — AI 역량 기본 교육 워크북 =====
    "harves-ai-basic": {
        "title": "미용실 AI 활용<br>실무 워크북",
        "subtitle": "헤어·OC 두피케어 전문샵 원장을 위한 AI 역량 기본 교육",
        "author": "하베스 미용그룹",
        "pdf_filename": "미용실_AI_활용_실무_워크북.pdf",
        "cover": {
            "mode": "image",
            "image": "harves-cover-wave.png",  # 수채 웨이브 아트워크(글자 없음) — 2026-07 교체
            "overlay_text": True,    # 제목·부제·저자는 템플릿 타이포로 얹음
            "kicker": "AI PRACTICAL WORKBOOK",  # 제목 위 영어 아이브로우 라인
            "theme": "plum",          # 간지·표 색상 테마(플럼+로즈골드) — cover.mode와 분리
        },
        "chapters": [
            # 손-유지(목차): convert 가 스킵하고 build 는 파일이 있으면 포함
            (None,            "00_목차.md",                            None,     None,     None,                                  None, None),
            ("00-guide.md",   "00_1_시작하기.md",                      "GUIDE",  "&nbsp;", "교재 사용 설명서",                     "", ""),
            ("01-chapter.md", "01_강_AI_기초와_우리_샵_이해.md",       "LESSON", "1",      "AI 기초와<br>우리 샵 이해",            "", ""),
            ("02-chapter.md", "02_강_고객_페르소나와_콘텐츠_기획.md",  "LESSON", "2",      "고객 페르소나와<br>콘텐츠 기획",       "", ""),
            ("03-chapter.md", "03_강_AI_이미지와_비포애프터.md",       "LESSON", "3",      "AI 이미지와<br>Before · After",       "", ""),
            ("04-chapter.md", "04_강_인스타_블로그_플레이스_기초.md",  "LESSON", "4",      "인스타 · 블로그 ·<br>플레이스 기초",   "", ""),
            ("05-chapter.md", "05_강_브랜드와_개인_브랜딩.md",         "LESSON", "5",      "브랜드와<br>디자이너 개인 브랜딩",     "", ""),
            ("06-chapter.md", "06_강_AI_영상_콘텐츠_기초.md",          "LESSON", "6",      "AI 영상 콘텐츠 기초",                 "", ""),
            ("07-chapter.md", "07_강_숏폼_제작.md",                    "LESSON", "7",      "숏폼(릴스 · 쇼츠) 제작",              "", ""),
            ("08-chapter.md", "08_강_유튜브_채널_운영.md",             "LESSON", "8",      "유튜브 채널 운영",                    "", ""),
            ("09-chapter.md", "09_강_네이버_플레이스와_광고_규정.md",  "LESSON", "9",      "네이버 플레이스 최적화와<br>광고 규정", "", ""),
            ("10-chapter.md", "10_강_AI_예약_응대_자동화.md",          "LESSON", "10",     "AI 예약 · 응대 자동화",               "", ""),
            ("11-chapter.md", "11_강_데이터_분석과_재방문_전략.md",    "LESSON", "11",     "데이터 분석과<br>재방문 전략",         "", ""),
            ("12-chapter.md", "12_강_매출_연결과_단골_만들기.md",      "LESSON", "12",     "매출 연결과<br>단골 만들기",           "", ""),
            ("13-chapter.md", "13_강_강사_양성_트랙.md",               "LESSON", "13",     "강사 양성 트랙<br>(심화)",            "", ""),
        ],
    },

    # ===== 하베스 뷰티그룹 — 올리베타 OC 전문점 디자이너 시술 교육 교재 =====
    "oc-designer-manual": {
        "title": "OC 전문점 디자이너<br>시술 교육 교재",
        "subtitle": "올리베타 에너지 OC · 21종 시술 상세 프로토콜",
        "author": "하베스 뷰티그룹 · 올리베타 OC 전문점 네트워크",
        "pdf_filename": "OC_전문점_디자이너_시술_교육_교재.pdf",
        "cover": {
            "mode": "image",
            "image": "oc-designer-manual-cover.png",  # Higgsfield 플럼·로즈골드 웨이브 원화 (2026-07)
            "overlay_text": True,     # 제목·부제·저자는 템플릿 타이포로 얹음
            "kicker": "OLIVETTA ENERGY OC · TRAINING MANUAL",
            "theme": "plum",          # 간지·표 색상 테마 — harves 계열과 통일
        },
        "chapters": [
            # 손-유지(목차): convert 가 스킵하고 build 는 파일이 있으면 포함
            (None,             "00_목차.md",                            None,       None,     None,                                              None, None),
            ("00-guide.md",    "00_1_시작하기.md",                      "GUIDE",    "&nbsp;", "교재 사용 설명서",                                 "", ""),
            ("01-chapter.md",  "01_강_OC_시스템의_이해.md",             "LESSON",   "1",      "OC 시스템의 이해",                                 "", ""),
            ("02-chapter.md",  "02_강_두피_모발_기초_이론.md",          "LESSON",   "2",      "두피·모발 기초 이론",                              "", ""),
            ("03-chapter.md",  "03_강_상담_진단_고객_차트.md",          "LESSON",   "3",      "상담·진단·고객 차트",                              "", ""),
            ("04-chapter.md",  "04_강_위생_안전_표현_규정.md",          "LESSON",   "4",      "위생·안전·표현 규정",                              "", ""),
            ("05-chapter.md",  "05_강_OC_커트.md",                      "LESSON",   "5",      "OC 커트",                                          "", ""),
            ("06-chapter.md",  "06_강_두피_케어_프로그램.md",           "LESSON",   "6",      "두피 케어 프로그램<br>스파 · 케어 · 집중 관리",    "", ""),
            ("07-chapter.md",  "07_강_모발_케어_프로그램.md",           "LESSON",   "7",      "모발 케어 프로그램<br>헤어 SPA · 클리닉",          "", ""),
            ("08-chapter.md",  "08_강_컬러_시술.md",                    "LESSON",   "8",      "컬러 시술<br>염색 · 탈색 · 블랙빼기",              "", ""),
            ("09-chapter.md",  "09_강_펌_시술.md",                      "LESSON",   "9",      "펌 시술<br>일반펌 · 열펌 · 셋팅펌",                "", ""),
            ("10-chapter.md",  "10_강_매직_시술.md",                    "LESSON",   "10",     "매직 시술<br>매직 · 볼륨매직 · 매직셋팅",          "", ""),
            ("11-chapter.md",  "11_강_대상별_케어_라인.md",             "LESSON",   "11",     "대상별 케어 라인<br>웨딩 · 키즈 · 남성 · 여성 · 실버", "", ""),
            ("12-chapter.md",  "12_강_프리미엄_토탈_케어.md",           "LESSON",   "12",     "프리미엄 토탈 케어",                               "", ""),
            ("13-chapter.md",  "13_강_고객_안내_홈케어_재방문_설계.md", "LESSON",   "13",     "고객 안내 · 홈케어 ·<br>재방문 설계",              "", ""),
            ("14-chapter.md",  "14_강_검수_평가_트레이닝_로드맵.md",    "LESSON",   "14",     "검수 · 평가 ·<br>트레이닝 로드맵",                 "", ""),
            ("98-appendix.md", "15_부록.md",                            "APPENDIX", "&nbsp;", "부 록<br>빠른 참조표와 양식",                      "", ""),
        ],
    },

    # ===== 소상공인 — AI 역량 기본 교육 워크북 (미용실 워크북에서 업종 확장) =====
    "sosanggongin-ai-basic": {
        "title": "소상공인 AI 활용<br>실무 워크북",
        "subtitle": "어떤 가게든 바로 쓰는 1인 사장님 AI 역량 기본 교육",
        "author": "저자 마상욱 · 김세광",
        "pdf_filename": "소상공인_AI_활용_실무_워크북.pdf",
        "cover": {
            "mode": "tech-navy",        # 표지 이미지 없이 빌드되는 텍스트 표지(추후 image 교체 가능)
            "kicker": "소상공인 · AI 역량 기본 교육",
            "badge": "AI",
            "host": "주최 · 대전대학교 RISE 사업단",   # 겉표지 하단 주최 기관
        },
        "chapters": [
            # 손-유지(목차): convert 가 스킵하고 build 는 파일이 있으면 포함
            (None,            "00_목차.md",                                None,     None,     None,                                         None, None),
            ("00-guide.md",   "00_1_시작하기.md",                          "GUIDE",  "&nbsp;", "교재 사용 설명서",                            "", ""),
            ("01-chapter.md", "01_강_AI_기초와_우리_가게_이해.md",         "LESSON", "1",      "AI 기초와<br>우리 가게 이해",                "", ""),
            ("02-chapter.md", "02_강_고객_페르소나와_콘텐츠_기획.md",      "LESSON", "2",      "고객 페르소나와<br>콘텐츠 기획",             "", ""),
            ("03-chapter.md", "03_강_AI_이미지와_상품_매장_사진.md",       "LESSON", "3",      "AI 이미지와<br>상품 · 매장 사진",            "", ""),
            ("04-chapter.md", "04_강_인스타_블로그_플레이스_기초.md",      "LESSON", "4",      "인스타 · 블로그 ·<br>플레이스 기초",         "", ""),
            ("05-chapter.md", "05_강_브랜드와_사장님_개인_브랜딩.md",      "LESSON", "5",      "브랜드와<br>사장님 개인 브랜딩",             "", ""),
            ("06-chapter.md", "06_강_AI_영상_콘텐츠_기초.md",              "LESSON", "6",      "AI 영상 콘텐츠 기초",                       "", ""),
            ("07-chapter.md", "07_강_숏폼_제작.md",                        "LESSON", "7",      "숏폼(릴스 · 쇼츠) 제작",                    "", ""),
            ("08-chapter.md", "08_강_유튜브_채널_운영.md",                 "LESSON", "8",      "유튜브 채널 운영",                          "", ""),
            ("09-chapter.md", "09_강_네이버_플레이스와_광고_규정.md",      "LESSON", "9",      "네이버 플레이스 최적화와<br>광고 · 표시 규정", "", ""),
            ("10-chapter.md", "10_강_AI_예약_주문_응대_자동화.md",         "LESSON", "10",     "AI 예약 · 주문 ·<br>응대 자동화",            "", ""),
            ("11-chapter.md", "11_강_데이터_분석과_재방문_전략.md",        "LESSON", "11",     "데이터 분석과<br>재방문 · 재구매 전략",      "", ""),
            ("12-chapter.md", "12_강_매출_연결과_단골_만들기.md",          "LESSON", "12",     "매출 연결과<br>단골 만들기",                 "", ""),
            ("13-chapter.md", "13_강_강사_양성_트랙.md",                   "LESSON", "13",     "강사 양성 트랙<br>(심화)",                  "", ""),
            # 손-유지(저자 소개): 본문 맨 뒤에 배치 — 목차 하드코딩 페이지번호를 건드리지 않도록 후미 삽입
            (None,            "14_저자_소개.md",                           None,     None,     None,                                         None, None),
        ],
    },

    "cbs-ai-training-manual": {
        "title": "생성형 AI 콘텐츠 제작<br>실무 매뉴얼",
        "subtitle": "CBS M&C 전사교육 40시간(10회) 과정 교재",
        "author": "CBS M&C 뉴럴웨이브",
        "pdf_filename": "생성형_AI_콘텐츠_제작_실무_매뉴얼.pdf",
        "cover": {
            "mode": "tech-navy",
            "kicker": "CBS M&C · TRAINING MANUAL",
            "badge": "AI",
        },
        "chapters": [
            ("00-preface.md",    "00_1_머리말.md",                              "PREFACE",  "&nbsp;", "머리말",                                "", ""),
            ("01-chapter.md",    "01_장_AI_기초와_미디어_산업의_변화.md",       "CHAPTER",  "1",      "AI 기초와<br>미디어 산업의 변화",       "", ""),
            ("02-chapter.md",    "02_장_생성형_AI_도구_활용_기초.md",           "CHAPTER",  "2",      "생성형 AI 도구 활용 기초",              "", ""),
            ("03-chapter.md",    "03_장_LLM_기반_콘텐츠_작성_심화.md",          "CHAPTER",  "3",      "LLM 기반<br>콘텐츠 작성 심화",          "", ""),
            ("04-chapter.md",    "04_장_AI_기반_이미지_음성_콘텐츠_제작.md",    "CHAPTER",  "4",      "AI 기반<br>이미지·음성 콘텐츠 제작",    "", ""),
            ("05-chapter.md",    "05_장_AI_영상_편집_보조_도구_활용.md",        "CHAPTER",  "5",      "AI 영상 편집<br>보조 도구 활용",        "", ""),
            ("06-chapter.md",    "06_장_업무_자동화_시나리오_설계.md",          "CHAPTER",  "6",      "업무 자동화 시나리오 설계",             "", ""),
            ("07-chapter.md",    "07_장_데이터_분석_시각화_AI_활용.md",         "CHAPTER",  "7",      "데이터 분석·시각화<br>AI 활용",         "", ""),
            ("08-chapter.md",    "08_장_CBS_업무_적용_워크숍_1.md",             "CHAPTER",  "8",      "CBS M&C 업무 적용<br>워크숍 (1)",       "", ""),
            ("09-chapter.md",    "09_장_CBS_업무_적용_워크숍_2.md",             "CHAPTER",  "9",      "CBS M&C 업무 적용<br>워크숍 (2)",       "", ""),
            ("10-chapter.md",    "10_장_종합_발표_및_핵심역량교육_연계.md",     "CHAPTER",  "10",     "종합 발표 및<br>핵심역량교육 연계",     "", ""),
            ("99-references.md", "11_부록_참고자료.md",                         "APPENDIX", "&nbsp;", "부 록<br>도구 인덱스와 참고자료",       "", ""),
        ],
    },

    "cbs-core-competency-manual": {
        "title": "AI 뉴스 콘텐츠 자동화<br>실무 매뉴얼",
        "subtitle": "CBS M&C 핵심역량교육 80시간(7회) 과정 교재",
        "author": "CBS M&C 뉴럴웨이브",
        "pdf_filename": "AI_뉴스_콘텐츠_자동화_실무_매뉴얼.pdf",
        "cover": {
            "mode": "tech-navy",
            "kicker": "CBS M&C · CORE COMPETENCY",
            "badge": "AI",
        },
        "chapters": [
            ("00-preface.md",    "00_1_머리말.md",                                "PREFACE",  "&nbsp;", "머리말",                                  "", ""),
            ("01-chapter.md",    "01_장_AI_기술_심화와_프롬프트_엔지니어링.md",   "CHAPTER",  "1",      "AI 기술 심화와<br>프롬프트 엔지니어링",   "", ""),
            ("02-chapter.md",    "02_장_음성_AI와_STT_기술_실무.md",              "CHAPTER",  "2",      "음성 AI와<br>STT 기술 실무",              "", ""),
            ("03-chapter.md",    "03_장_영상_분석_AI와_멀티모달_처리.md",         "CHAPTER",  "3",      "영상 분석 AI와<br>멀티모달 처리",         "", ""),
            ("04-chapter.md",    "04_장_데이터_분석과_검색_추천_기술.md",         "CHAPTER",  "4",      "데이터 분석과<br>검색·추천 기술",         "", ""),
            ("05-chapter.md",    "05_장_AI_기반_영상_제작과_기사_생성_자동화.md", "CHAPTER",  "5",      "AI 기반 영상 제작과<br>기사 생성 자동화", "", ""),
            ("06-chapter.md",    "06_장_PBL_프로젝트_CBS_업무_과제_해결.md",      "CHAPTER",  "6",      "PBL 프로젝트<br>— CBS 업무 과제 해결",    "", ""),
            ("07-chapter.md",    "07_장_CBL_도전_과제_AI_업무_효율화_설계.md",    "CHAPTER",  "7",      "CBL 도전 과제<br>— AI 업무 효율화 설계",  "", ""),
            ("99-references.md", "08_부록_참고자료.md",                           "APPENDIX", "&nbsp;", "부 록<br>도구·코드 인덱스와 참고자료",     "", ""),
        ],
    },

    # ===== 커리큘럼(교육과정 설계서) — 위 두 교재에서 파생 =====
    "cbs-curriculum-foundation": {
        "title": "생성형 AI 콘텐츠 제작 실무<br>교육 커리큘럼",
        "subtitle": "CBS M&C 전사교육 40시간(10회) 과정 · 교육과정 설계서",
        "author": "CBS M&C 뉴럴웨이브",
        "pdf_filename": "전사교육_커리큘럼_생성형_AI_콘텐츠_제작_실무.pdf",
        "cover": {
            "mode": "tech-navy",
            "kicker": "CBS M&C · CURRICULUM",
            "badge": "40H",
        },
        "chapters": [
            ("00-preface.md",   "00_1_머리말.md",           "PREFACE", "&nbsp;", "머리말",                          "", ""),
            ("01-overview.md",  "01_장_과정_총괄.md",       "PART",    "1",      "과정 총괄<br>· 학습 경로",        "", ""),
            ("02-sessions.md",  "02_장_회차별_커리큘럼.md", "PART",    "2",      "회차별 상세<br>커리큘럼",         "", ""),
            ("03-operation.md", "03_장_평가_운영.md",       "PART",    "3",      "평가 · 수료 기준<br>· 운영 안내", "", ""),
        ],
    },

    "cbs-curriculum-core": {
        "title": "AI 뉴스 콘텐츠 자동화 실무<br>교육 커리큘럼",
        "subtitle": "CBS M&C 핵심역량교육 80시간(7회) 과정 · 교육과정 설계서",
        "author": "CBS M&C 뉴럴웨이브",
        "pdf_filename": "핵심역량교육_커리큘럼_AI_뉴스_콘텐츠_자동화_실무.pdf",
        "cover": {
            "mode": "tech-navy",
            "kicker": "CBS M&C · CURRICULUM",
            "badge": "80H",
        },
        "chapters": [
            ("00-preface.md",   "00_1_머리말.md",           "PREFACE", "&nbsp;", "머리말",                          "", ""),
            ("01-overview.md",  "01_장_과정_총괄.md",       "PART",    "1",      "과정 총괄<br>· 학습 경로",        "", ""),
            ("02-sessions.md",  "02_장_회차별_커리큘럼.md", "PART",    "2",      "회차별 상세<br>커리큘럼",         "", ""),
            ("03-operation.md", "03_장_평가_운영.md",       "PART",    "3",      "평가 · 수료 기준<br>· 운영 안내", "", ""),
        ],
    },
}

DEFAULT_BOOK = "soccer-mission-book"
