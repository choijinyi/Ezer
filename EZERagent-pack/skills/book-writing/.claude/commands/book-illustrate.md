---
description: 편집부 그림 작업 — Higgsfield MCP로 표지·삽화 생성
---

# /book-illustrate

인자: $ARGUMENTS (형식: `<책이름> [cover | figure <설명>]`)

편집 단계의 이미지 생성. Higgsfield MCP 도구가 로드되지 않았으면 먼저 ToolSearch로 한 번에 로드한다:
`select:mcp__claude_ai_Higgsfield__generate_image,mcp__claude_ai_Higgsfield__upscale_image,mcp__claude_ai_Higgsfield__outpaint_image,mcp__claude_ai_Higgsfield__remove_background,mcp__claude_ai_Higgsfield__job_status`

## 원칙

- **도식·차트·다이어그램은 여기서 만들지 않는다** — 집필 단계의 Mermaid `<!-- fig: -->` 마커 사용 (수정 가능·결정적).
- Higgsfield 담당: 표지 원화, 장 간지 일러스트, 분위기 컷, 사진풍 삽화.
- 생성 이미지는 반드시 로컬에 저장 후 사용: 표지 → `BookTemplate/images/`, 본문 → `BookTemplate/images/figures/`.

## 표지 (`cover`)

1. `books.py`의 title/subtitle/author와 책 주제를 바탕으로 표지 컨셉 2~3안을 프롬프트로 제시하고 사용자가 고른다.
2. `generate_image`로 시안 생성. 판형 비율에 맞춘다 (신국판 152:225 ≈ 2:3, B5 188:257). 비율이 안 맞으면 `outpaint_image`로 확장.
3. 선택된 시안을 `upscale_image`(2K 이상, 인쇄 대비)로 올린 뒤 `BookTemplate/images/<책>-cover.png`로 저장.
4. `books.py`의 해당 책에 cover 설정 반영 (게이트 — 사용자 승인 후 수정):
   ```python
   "cover": {"mode": "image", "image": "<책>-cover.png", "overlay_text": True}
   ```
   - 제목·저자를 이미지에 직접 그려 넣으려면 Canva MCP로 원화 위에 타이포를 얹어 export하고 `overlay_text: False`로 설정.

## 본문 삽화 (`figure <설명>`)

1. 어느 장의 어느 위치에 넣을지 확인.
2. `generate_image` → 필요 시 `remove_background`/`upscale_image` → `BookTemplate/images/figures/<책>-<번호>-<슬러그>.png` 저장.
3. `content/<책>/NN_*.md`의 해당 위치에 삽입:
   ```markdown
   ![캡션](../images/figures/<파일명>.png)
   ```
   단, 이 삽입은 이관 시 덮어써질 수 있으므로 **오래 유지할 삽화는 manuscripts/ 원고의 figures 참조로 넣고 재이관**하는 것을 권장. 일회성 편집 컷만 content/에 직접 넣는다.
4. 같은 책의 삽화는 화풍·팔레트를 통일한다 (첫 삽화의 스타일 서술을 프롬프트에 재사용).
