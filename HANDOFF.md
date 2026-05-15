# 라이브커머스 AI 쇼츠 리디자인 — 세션 인계 문서

> **목적**: 본 세션 토큰 한도 도달 시 다른 Claude 계정으로 작업 인계용. 이 문서 전체를 복붙해서 새 세션에 붙여넣으면 동일 컨텍스트로 이어갈 수 있음.
>
> **마지막 갱신**: 2026-05-15 (Phase 0/1/2/3/4 완료, 통합 머지 진행 중. Phase 3 결과 페이지 wiring + Phase 5/6 미시작)

---

## 00. AUTO-START — 새 Claude 세션 자동 진입 절차

> 사용자가 이 문서 전체 복붙 + "**Phase N 해줘**"(N ∈ {2, 3, 4}) 라고만 말하면 아래 절차 그대로 자동 실행.

### A. 첫 행동 (질문 없이 바로)
1. 작업 디렉터리로 이동:
   ```bash
   cd "/mnt/c/Users/yes21/Desktop/_LV.UP/_LEVEL_UP/PROJECT/[HEIMDEX]/heimdex-for-livecommerce-dev"
   ```
2. 현재 상태 점검 (3개 명령 병렬):
   ```bash
   git fetch --all --quiet && git status --short
   git log --oneline -8
   ls .figma-cache/*.api.json | wc -l   # 13이면 캐시 OK, 0이면 아래 B 안내
   ```
3. 담당 브랜치 체크아웃 (Phase 번호에 따라):
   - Phase 2 → `git checkout feat/p3-axis2-wizard`
   - Phase 3 → `git checkout feat/p3-axis3-result`
   - Phase 4 → `git checkout feat/p3-axis4-saved-shorts`
4. 아래 표에서 담당 Phase의 시작 파일 + 캐시 파일 + 핵심 spec 위치 확인 후 작업 개시.

### B. 캐시 누락 시 (`.api.json` 0개)
사용자에게 한 줄 안내 후 대기:
```
.figma-cache/*.api.json 이 비어있습니다. 다음을 실행해주세요:
  export FIGMA_TOKEN="figd_xxx"
  bash .figma-cache/fetch-nodes.sh
끝나면 알려주세요.
```

### C. Phase별 진입 매핑 (이 문서 안에서 자기-참조)

**Phase 1~4는 통합 머지 완료**. 현재 활성 분담은 Phase 5 sub 4개 + Phase 6 결정 대기.

| Phase | 브랜치 (단일 정책) | 핵심 spec 섹션 | 시작 파일 | Figma 캐시 |
|---|---|---|---|---|
| 5.1 (axis5a) | `feat/marketing-p3-ai-shorts` (전원 공용) | §6.5 (이 문서) | `services/web/src/features/shorts-editor/components/{ShortsEditorPage,EditorHeader,EditorLayout,SubtitleEditor,SubtitleBlock,SubtitleTrack,SceneListPanel,TimelinePanel,TimelineRuler,PreviewPanel}.tsx` | `.figma-cache/1713-274802_phase5_editor-2.api.json` |
| 5.2 (axis5b) | `feat/marketing-p3-ai-shorts` | §6.5 | `services/web/src/features/shorts-editor/components/{TextOverlayPanel.tsx,OverlayPanel/*.tsx}` | `.figma-cache/1713-275432_phase5_editor-3.api.json` |
| 5.3 (axis5c) | `feat/marketing-p3-ai-shorts` | §6.5 | 신규 `TemplateSaveDialog.tsx` + `EditorHeader.tsx` 메뉴 영역만 (5.1 종료 후 시작) | `.figma-cache/1713-275817_phase5_editor-4.api.json` |
| 5.4 (axis5d) | `feat/marketing-p3-ai-shorts` | §6.5 | `PreviewPanel.tsx` `fullscreen` prop 확장 (5.1 종료 후 시작) | `.figma-cache/1713-275105_phase5_editor-5.api.json` |
| 6 (axis6) | `feat/marketing-p3-ai-shorts` | §6.6 | `src/features/videos/components/VideoDetailPage.tsx` (ScenesPanel 분기) + `SceneCard.tsx`/`SceneGroupCard.tsx` (세로 모드만) | `.figma-cache/1713-271669_phase5_editor-1.api.json` |

### D. 진행 중 항상 지켜야 할 규칙
1. **Co-Authored-By Claude 금지** (Heimdex 저장소 정책)
2. **마이크로 커밋** — 컴포넌트 1개 또는 디자인 토큰 1세트 단위
3. **푸시 금지** — 사용자 명시 승인 필수 (head 세션만 푸시 가능)
4. **백엔드 변경 0건** — 내보내기 API는 mock/stub만
5. **dev 서버 호출 금지** — `npm run dev` 은 지석님이 직접
6. **언어** — 한국어로 응답 (코드/식별자는 원어)
7. **figma MCP 사용 금지** — `.figma-cache/*.api.json` 으로만 작업. Figma MCP는 단일 세션 제약이라 다른 세션을 끊음. 캐시에 없는 정보면 head 세션에 보고
8. **공유 파일 수정 금지** — `tailwind.config.ts`, `globals.css`, `figma-index.ts`, `HANDOFF.md` 는 **head 세션만 수정**. sub 세션은 변경 필요 시 head에게 보고 후 대기
9. **HANDOFF.md 수정 금지** — sub 세션은 절대 HANDOFF.md를 직접 수정하지 말 것. 진행 상태는 커밋 메시지로 남기기

### D-2. 시행착오 학습 룰 (Phase 2/3/4 머지 회고, 2026-05-15)

같은 working tree에 다중 Claude가 작업할 때 발생한 사고들 → 재발 방지 룰:

1. **`git checkout` 금지 (sub 세션)** — 같은 working tree에서 `git checkout`은 모든 세션의 HEAD를 동시에 옮긴다. 다른 세션의 워크플로가 깨짐.
   - **sub 세션**: 본인이 어떤 브랜치에 있는지 확인만 (`git branch --show-current`)
   - **head 세션**: 브랜치 전환·머지·체크아웃 전권
2. **자기 브랜치 체크아웃 시도 금지** — 위 1번과 동일 이유. Phase 2/3/4 사고: 각 세션이 `feat/p3-axis<N>` 체크아웃하려다 axis4 working tree로 모두 강제 전환됨.
3. **단일 브랜치 정책 (Phase 5+)** — 모든 sub 세션은 `feat/marketing-p3-ai-shorts` 위에서 직접 커밋. 커밋 메시지 prefix(`feat(web/p3-axis5a)` 등)로 phase 식별. 별도 sub-branch 만들지 않음.
4. **`git stash` 금지 (sub 세션)** — Phase 4 사고: stash가 다른 세션의 미커밋 변경까지 함께 stash해서 잠시 사라짐. sub 세션은 검증 전에 본인 변경을 커밋해서 워킹트리를 깨끗하게 유지. head만 stash 사용 가능.
5. **워킹트리에 modified 파일 발견 시** — 본인 변경이 아니면 절대 건드리지 말 것. head에게 즉시 보고 (파일 경로 + 첫 몇 줄 diff). head가 소유 세션 확인 후 처리.
6. **파일 영역 lock** — 각 sub는 §00.C 매핑표의 자기 시작 파일만 수정. 공유 파일(`figma-index.ts`, `tailwind.config.ts`, `globals.css`)은 head 권한.
7. **순서 의존성 준수** — Phase 5는 5.1(베이스) 완료 후 5.3/5.4 시작. 5.2는 5.1과 동시 가능 (파일 영역이 다름).
8. **5분 idle 시 보고** — sub 세션이 5분 이상 작업 없이 대기하면 head에게 "idle, 다음 지시 대기" 한 줄 보고. head가 새 task 할당하거나 종료 지시.

### E. 완료 기준
- `cd services/web && npx tsc --noEmit` exit 0
- `npx vitest run` 신규/관련 테스트 통과 + 기존 회귀 0건
- HANDOFF.md §11 진행 상태 갱신
- 마지막 커밋 메시지에 Phase 완료 명시 (`feat(web/p3-axisN): complete Phase N — <요약>`)

### F. 캐시 활용 패턴 (토큰 절약)
```ts
// 1) 전체 raw JSON 부분 읽기로 구조 파악
Read(".figma-cache/1713-288216_phase2_wizard-criteria.api.json", offset=0, limit=200)

// 2) jq로 특정 필드 추출 (Bash)
jq '.document.children[] | {name, absoluteBoundingBox}' .figma-cache/<file>.api.json

// 3) 텍스트만 추출
jq '.. | objects | select(.type=="TEXT") | .characters' .figma-cache/<file>.api.json

// 4) 색 fill 만 추출
jq '.. | objects | select(.fills?) | {name, fills}' .figma-cache/<file>.api.json
```

---

## 0. 즉시 알아야 할 것

- **작업 경로**: `/mnt/c/Users/yes21/Desktop/_LV.UP/_LEVEL_UP/PROJECT/[HEIMDEX]/heimdex-for-livecommerce-dev/services/web`
- **저장소**: heimdex-for-livecommerce-dev (Heimdex 조직, branch=main)
- **커밋 규칙**: ⚠️ **Co-Authored-By Claude 절대 금지** (Heimdex 저장소 정책)
- **커밋 단위**: **마이크로 커밋** — 컴포넌트 1개 또는 토큰 1세트 단위로 작게 자주
- **푸시 금지**: git push는 사용자 명시 승인 필수, 자동 푸시 금지
- **백엔드 변경 0건**: 프론트엔드만 작업. 내보내기 백엔드 API는 미정이므로 mock/stub
- **로컬 테스트 우선**: 지석님이 `npm run dev` 직접 실행. claude는 dev 서버 호출 금지(토큰 절약)
- **언어**: 한국어로 응답 (코드 식별자/기술용어는 원어 유지)

---

## 1. 프로젝트 컨텍스트

### 1.1 무엇을 하는가
Heimdex 라이브커머스 제품의 AI 쇼츠 생성 flow + 내 쇼츠 페이지를 Figma `P3 - Marketing` 디자인(fileKey `PYDMMAvFq7PmhjyVTftiU6`)에 맞춰 리디자인.

### 1.2 핵심 노드 ID (Figma)
| 화면 | 노드 ID |
|---|---|
| 동영상 상세 / 개요 탭 | 1713:270773 |
| Wizard - 옵션 설정 | 1713:288216 |
| Wizard - 상품 선택 (single) | 1713:288149 |
| Wizard - 상품 선택 (multi) | 1713:288182 |
| Wizard - 인덱싱 진행 | 1713:288103 |
| Wizard - 결과 | 1713:288042 |
| 내 쇼츠 (저장된 쇼츠 목록) | 1713:287987 |
| 생성 취소 Dialog | 1602:36895 |
| 편집 페이지 (Phase 5, 후속) | 1713:271669, 274802, 275432, 275817, 275105 |

### 1.3 스택
- Next.js 14.1 (App Router) + React 18 + TypeScript 5.3
- Tailwind 3.4 (디자인 토큰 확장 완료)
- lucide-react 1.16
- Vitest 4.0
- Auth0 (Auth0 enabled 시) / Dev login (NEXT_PUBLIC_AUTH0_ENABLED=false 시)

---

## 2. Phase 0 — 완료된 작업 (검증됨)

### 2.1 디자인 토큰 (tailwind.config.ts:11-82)
- `heimdex-navy.{400,500,600,700}` (#496a94 ~ #1a3d61), primary=500=#234c77
- `grayscale.{10,100,200,300,400,500,800}` (#fcfcff ~ #272833)
- `neutral-h.{50~800}`, `red-h.{50,400,500}`, `green-h.{50,400,500}`, `amber-h.{50,500}`
- `boxShadow.card` = `0px 4px 20px 0px rgba(232,233,248,1)`
- `boxShadow.dialog` = `2px 2px 20px 0px rgba(0,0,0,0.25)`
- `borderRadius.card` = 10px, `borderRadius.dialog` = 20px
- 폰트: Pretendard (`var(--font-pretendard)`)

### 2.2 신규 컴포넌트 (Phase 0)
**아이콘** (`src/components/icons/figma/`):
- `HeimdexBrand.tsx`, `HeimdexSymbol.tsx`, `HeimdexWordmark.tsx`
- `WarningIcon.tsx`, `TooltipArrow.tsx`
- `index.ts` (re-export)

**공통 UI** (`src/components/ui/`):
- `Button.tsx` (primary/secondary/ghost × sm/md)
- `Snackbar.tsx` (bottom-center | top-right)
- `Stepper.tsx` (3-step indicator)
- `Dialog.tsx` (확인 다이얼로그)
- `Popover.tsx` (⋮ 메뉴)
- `figma-index.ts` (re-export)

**자산**: `public/figma-assets/icons/` 에 SVG 복사 완료

**레이아웃**: `Sidebar.tsx`, `TopHeader.tsx` 의 로고/토글만 신규 자산으로 교체. 메뉴 구조는 유지.

### 2.3 검증 상태
- `npm run type-check` exit 0 (3회)
- 기존 vitest 60+ 테스트 회귀 통과
- dev 서버 실행 확인은 지석님 직접

---

## 3. Phase 1 — 동영상 상세 / 개요 탭 (현재 작업 시작점)

### 3.1 파일
- 대상: `src/app/videos/[videoId]/page.tsx`
- 관련 컴포넌트: `src/features/videos/`, `src/features/preedit/` (탭 영역)

### 3.2 디자인 매핑 (1713:270773)
- **좌측 동영상 카드** (341px 폭)
  - 썸네일 + 컨트롤 + 메타데이터: 파일 위치/폴더/재생 시간/업로드 일자
- **우측 탭 영역**
  - 탭: 개요 / 장면 분석 / 인물 관리
  - 우상단: "AI 쇼츠 생성" 버튼 (primary navy/500) + "장면 재분석" 버튼 (secondary)
- **개요 탭 본문**
  - 행동 요약 카드
  - 스크립트: 화자 A = `text-red-h-400`, 화자 B = `text-green-h-400`
  - 메시지 = 타임스탬프 (00:00:02) + 텍스트 + 복사 아이콘
- **인터랙션**
  - "AI 쇼츠 생성" 클릭 → 우측 영역만 `InlineWizardContainer`로 swap (left 동영상 카드는 유지)

### 3.3 작업 순서
1. `src/app/videos/[videoId]/page.tsx` Read → 현재 구조 파악
2. 좌측 동영상 카드 컴포넌트 디자인 적용
3. 우측 탭 헤더 + AI 쇼츠 생성/장면 재분석 버튼 적용
4. 개요 탭: 행동 요약 + 스크립트 (화자 색 구분)
5. type-check → 마이크로 커밋

---

## 4. Phase 2 — Inline Wizard

### 4.1 파일
- `src/features/shorts-auto-product-wizard/components/InlineWizardContainer.tsx`
- `InlineWizardCriteriaPanel.tsx` (1713:288216)
- `InlineWizardProductPanel.tsx` (1713:288149, 288182)
- 신규: `IndexingProgressPanel.tsx` (1713:288103)

### 4.2 Stepper (1713:288216 상단)
- 3-step: `1.옵션 설정 → 2.상품 선택 → 3.AI 쇼츠 생성`
- active = navy/500 원 + 검정 텍스트, inactive = `neutral-h.300` 원 + 회색 텍스트
- 구분자 = `chevron-right` (24px, lucide)
- 마운트 위치: GNB 아래, 컨텐츠 위 (디자인 좌표 top:28px)

### 4.3 InlineWizardCriteriaPanel 리디자인 (1713:288216)
- 카드 폭 578px, padding 20, gap 60
- 헤더: "옵션 설정" + 우측 "다음" 버튼 (primary navy)
- **생성 유형 카드 2개** (single / multi 토글)
- **영상 구간** 슬라이더: 양끝 핸들 + tooltip (왼=시작, 오=종료)
- **쇼츠 길이** 5개 카드: 15 / 30 / 60 / 90 / 120
- **쇼츠 개수** 10개 카드: 1~10 + 동적 안내 칩 (예: "15:40 영상에서 60초 쇼츠라면 5~7개가 적합")
- **LanguageToggle 제거** (디자인에 없음)

### 4.4 InlineWizardProductPanel 리디자인 (1713:288149/288182)
- 상단: 옵션 요약 칩 + "다음" 버튼 (모든 상태 표시, ready=활성)
- 안내 박스 (single/multi 분기):
  - single: "선택한 상품을 모두 포함한 쇼츠 N개를 생성합니다."
  - multi: "선택한 상품마다 하나씩, 별도의 쇼츠 N개를 생성합니다. 상품은 최대 4개까지 선택 가능합니다."
- 그리드: `flex flex-wrap justify-between gap-y-[20px]`, 카드 200×200
- 카드 보더: 1px `grayscale.100` / 선택 시 2px `heimdex-navy.500`, 체크박스 우상단
- Cap 분기: single=4개 고정, multi=`requested_count`
- Cap 초과 시 `Snackbar` (하단 중앙): "최대 N개까지 선택할 수 있어요 / 적게 고르면 나머지는 AI가 자동으로 채워줘요"
- 다음 클릭 → `/export/shorts/auto/wizard/{videoId}/result/{parentJobId}` push (현행 유지)

### 4.5 IndexingProgressPanel 신규 (1713:288103)
- 4단계 파이프라인 칩 (queued / current / completed):
  - 한국어 라벨: "동영상 분석" / "상품 인식" / "장면 조립" / "렌더링"
  - 백엔드 ScanStage 매핑: enumerating → tracking → assembling → rendering
- 현재 단계: navy/500 보더 + 스피너 + 진행 텍스트
- 완료 단계: navy/600 배경 + 흰 체크
- 큰 38% 텍스트 (navy/500) + "약 40초 남았습니다" (계산: 잔여 children × 평균 렌더 시간)
- 상단: 옵션 요약 칩 + 비활성 다음 버튼
- 마운트 조건: result 페이지에서 `children_total === 0` 또는 어떤 child도 `render_status === "completed"` 아닐 때

---

## 5. Phase 3 — 결과 화면 (1713:288042)

### 5.1 파일
- `WizardStepResult.tsx` (또는 `src/app/export/shorts/auto/wizard/[videoId]/result/[parentJobId]/page.tsx`)
- `src/features/shorts-auto-product-wizard/components/ExportShortsButton.tsx`

### 5.2 디자인
- **헤더**: "생성된 쇼츠 N개" + "모두 저장하기" (secondary) + "모두 내보내기" (primary navy)
- **카드 4상태** (ScanStage + render_status 조합):
  - 대기 중: stage ∈ {queued, enumerating, tracking} → gray 칩
  - 생성 중: stage ∈ {assembling, rendering} OR render_status=rendering → `amber-h` (#ffefda 배경 / #e07f00 텍스트) 칩
  - 완료: render_status=completed → `green-h.50` 배경 / `green-h.500` 텍스트 칩
  - 실패: stage ∈ {failed, cancelled} → `red-h.50` / `red-h.500` 칩
- **카드 구조** (287×253):
  - 좌 썸네일 150×253 + 좌하단 상품 태그 (1개 또는 2개+)
    - 상품 태그 산출: `criteria.product_distribution` + `selected catalog_entry_ids`
  - 우 메타: 제목 / 길이 / 진행률 / 캡션(`RenderJobResponse.summary` 50자 truncate) / 상태 칩
  - 우상단: ⋮ 메뉴 Popover
- **메뉴 분기**:
  - 진행률 < 100%: 제목 변경 / 생성 취소(red)
  - 진행률 = 100%: 제목 변경 / 저장하기 / 내보내기 / 생성 취소(red)
- **생성 취소** 클릭 → 확인 Dialog (디자인 1602:36895 문구 적용)

---

## 6. Phase 4 — 내 쇼츠 페이지 (1713:287987)

### 6.1 파일
- `src/app/shorts/page.tsx` 또는 `src/features/shorts/SavedShortsPage.tsx`

### 6.2 디자인
- **헤더**: "저장된 쇼츠 목록 N개" + "새 쇼츠 생성" (secondary + plus 아이콘) + "내보내기" (primary navy)
- **검색바**: lucide `Search` + placeholder "찾고 싶은 영상을 제목으로 검색해보세요."
- **정렬 드롭다운**: "생성 일자 순" + chevron-down
- **카드 그리드**: 9:16 (200×337 + 라벨 영역)
- **페이지네이션**: double-left / left / 숫자 / right / double-right (디자인 그대로)

### 6.3 Export 진행 Snackbar
- `useExportBatch` 훅의 `exportState` Map watch
- 진행 중인 batch 있으면 우상단 토스트
- 내용: 스피너 + "쇼츠 저장 중" + "X% · 남은 시간" + X 닫기
- 진행률: `completed / total` (Map status=completed 카운트). 남은 시간 = 평균 렌더 속도 기반
- ⚠️ 내보내기 백엔드 미정 → `// NOTE(export-backend-tbd):` 주석으로 wiring 지점 표시

---

## 6.5 Phase 5 — 쇼츠 편집 페이지 (Head 명령서)

> **Head 세션이 작성한 명령서**. sub 세션 4개에게 분담. 의문점은 head에게 묻고 작업 시작 전 본인 task ID 확인.

### 6.5.0 개요
- Figma "2-5.a~d" 4개 state — 동일 레이아웃 + 우측 패널만 다름
- 기존 코드 `src/features/shorts-editor/` 광범위 구현 → **디자인 적용만**, 백엔드 0건, 새 컴포넌트 최소화
- 작업 전 필수: `bash .figma-cache/fetch-nodes.sh` 로 raw API JSON 13개 보유 확인 (sub 세션은 fetch 명령 실행 금지 — head만)

### 6.5.1 Sub 분담표 (단일 브랜치 `feat/marketing-p3-ai-shorts`)

| Sub | 담당 영역 | 시작 가능 시점 | 파일 (수정 권한 lock) |
|---|---|---|---|
| **5.1 axis5a** | 베이스 레이아웃 + 자막 패널 | 즉시 | `ShortsEditorPage.tsx`, `EditorHeader.tsx`, `EditorLayout.tsx`, `SubtitleEditor.tsx`, `SubtitleBlock.tsx`, `SubtitleTrack.tsx`, `SceneListPanel.tsx`, `TimelinePanel.tsx`, `TimelineRuler.tsx`, `PreviewPanel.tsx` (단 `fullscreen` prop은 5.4 담당) |
| **5.2 axis5b** | 텍스트/배경 오버레이 패널 | 즉시 (5.1과 동시 가능 — 파일 영역 다름) | `TextOverlayPanel.tsx`, `OverlayPanel/**/*.tsx` |
| **5.3 axis5c** | 템플릿 저장 dialog (기존 `usePresets` 훅 + `refinement_service.py` 백엔드 재사용) | **5.1 완료 후** | `OverlayPanel/PresetSection.tsx` 디자인 적용 + 신규 `TemplateSaveDialog.tsx` (Phase 0 `Dialog` primitive 재사용). 백엔드 변경 0건 |
| **5.4 axis5d** | 전체보기 fullscreen overlay (새 라우트 아님) | **5.1 완료 후** | `PreviewPanel.tsx` 의 `fullscreen` prop + 신규 `FullscreenOverlay.tsx` (LNB/GNB 위 `position: fixed`, iPhone mockup 352×626 확대, 우상단 lucide `X`로 닫기) |

### 6.5.2 공통 디자인 매핑 (4 state 동일)
- LNB(`Sidebar`) + GNB(`TopHeader`) → Phase 0 결과물 그대로 유지
- 중앙 iPhone 13/14 mockup (`PreviewPanel` 내부)
- 우측 패널: state별 다름 (5.1 자막 / 5.2 오버레이 / 5.3 템플릿 / 5.4 전체보기)
- 하단 타임라인: 배속 `1.0x` / `1.5x`, 마커 `0s` ~ `10s`, 진행 `00:00:00 - 00:00:03` 형식, 총 길이 `00:59:56 / 01:05:23` 형식
- 색: primary `heimdex-navy-500`, 화자 칩 `red-h-400` / `green-h-400` (Phase 1과 일관)
- 배경: `bg-grayscale-10` (#fcfcff), 카드 `shadow-card` + `rounded-card`

### 6.5.3 핵심 텍스트 (캐시에서 식별됨)
- 자막 번호 chip: `#1` ~ `#7` (선택 시 navy 보더)
- 배속 토글: `1.0x` / `1.5x`
- 타임라인 마커: `0s`, `10s`
- 재생 진행 카운터: `00:00:00 - 00:00:03` / `00:59:56 / 01:05:23`

### 6.5.4 sub 세션 작업 순서 (각자)
1. **헤드 task 확인** — head 세션에게 "axis5a 시작합니다" 보고 후 응답 대기 (head가 task ID 부여)
2. **현재 브랜치 확인만** (`git branch --show-current` → `feat/marketing-p3-ai-shorts` 여야 함). 체크아웃 금지
3. **워킹트리 깨끗 확인** (`git status --short`). 본인 게 아닌 modified 발견 시 즉시 head 보고
4. **캐시에서 spec 추출** — `jq` 로 본인 노드의 TEXT/RECTANGLE/auto-layout/색 추출 (HANDOFF §14.4)
5. **기존 파일 Read** → diff 단위 변경 (구조 유지, 색·여백·폰트만)
6. **type-check** — `cd services/web && npx tsc --noEmit` exit 0 확인
7. **vitest** — `npx vitest run src/features/shorts-editor` (관련 영역만)
8. **마이크로 커밋** — 컴포넌트 1개씩 분리. 메시지 prefix: `feat(web/p3-axis5{a|b|c|d}): ...`
9. **완료 보고** — head에게 마지막 커밋 SHA + 변경 요약 (단어 200개 이내)

### 6.5.4-b sub별 상세 결정사항 (지석님 2026-05-15)

- **5.3 백엔드**: ✅ 기 구현 (`usePresets` 훅 + `PresetSection.tsx` 프론트 + `refinement_service.py` 백엔드 `template_id`/`style_template` 처리). sub5c는 디자인만 적용 + `TemplateSaveDialog.tsx` 신규 (Phase 0 `Dialog` primitive 재사용). 백엔드 변경 0건
- **5.4 형식**: ✅ fullscreen **overlay** (새 라우트 아님). `PreviewPanel`에 `fullscreen` prop → true 시 `FullscreenOverlay` (`position: fixed` LNB/GNB 위에 덮음, viewport 전체). 우상단 lucide `X` 클릭 또는 ESC 키로 fullscreen off. iPhone mockup 352×626으로 확대
- **PR/푸시**: 지석님이 직접 — head 세션은 머지까지만, push/PR 권한 없음. 모든 Phase(5 + 6) 완료 후 시각 검증 → 지석님이 직접 PR

### 6.5.5 위험 영역 (반드시 주의)
- ⚠️ `ShortsEditorPage.tsx` 의 기존 TODO (`.stop-guard-ignore` 등록) **제거 금지**
- ⚠️ `PreviewPanel.tsx`, `TimelinePanel.tsx` 의 드래그/플레이헤드/시크 로직 **구조 변경 금지** — Tailwind class만
- ⚠️ `OverlayPanel/` 는 dnd-kit sortable → 핸들 클래스명 변경 시 드래그 깨짐. Read 후 신중히
- ⚠️ `SubtitleEditor.tsx` 8KB — 텍스트 입력·편집 로직 보존
- ⚠️ `ShortsEditorPage.tsx` 17KB — 큰 파일이므로 sub 5.3/5.4가 헤더만 만지더라도 같은 파일 동시 수정 금지 (반드시 5.1 종료 후)

### 6.5.6 충돌 방지 매트릭스

| 5.1 | 5.2 | 5.3 | 5.4 |
|---|---|---|---|
| `EditorHeader.tsx` 전체 | - | `EditorHeader.tsx` 메뉴만 (5.1 후) | - |
| `PreviewPanel.tsx` 기본 | - | - | `PreviewPanel.tsx` fullscreen prop (5.1 후) |
| `SubtitleEditor.tsx` | - | - | - |
| - | `TextOverlayPanel.tsx`, `OverlayPanel/` | - | - |
| - | - | 신규 `TemplateSaveDialog.tsx` | 신규 `FullscreenOverlay.tsx` |

`EditorHeader.tsx`, `PreviewPanel.tsx` 두 파일이 5.1과 5.3/5.4 모두 만지므로 **순차 작업 필수**.

### 6.5.7 sub 세션 → head 보고 양식 (필수)

```
axis5{a|b|c|d} 보고
- status: started / progress / blocked / done
- branch HEAD: <sha>
- 변경 파일: <files>
- 다음 단계: <next>
- 의문점: <question> (있으면)
```

head는 보고를 받고 task 진행 상태 업데이트 + 다음 지시.

---

## 6.6 Phase 6 (axis6) — 장면분석 "세로 썸네일 모드" 디자인

### 6.6.0 정체 (확정 — 지석님 2026-05-15)
- Figma "2-3.a 장면분석(세로)" (노드 1713:271669)
- **모바일 viewport 아님, 별도 라우트 아님**
- 의미: `orgSettings.thumbnail_aspect_ratio === "portrait"` 설정 시 표시되는 **세로 썸네일 카드 디자인**
- 토글 위치: 우상단 프로필 → 설정 → 가로/세로 모드 선택 (기존 UI 보존, 변경 없음)
- 가로 모드 디자인은 아직 UI/UX팀이 미작성 → **가로 모드는 현재 디자인 그대로 유지**, 세로 모드만 P3 디자인 적용

### 6.6.1 작업 위치
- 파일: `src/features/videos/components/VideoDetailPage.tsx` 내 `ScenesPanel` (`view === "scenes"` 분기)
- 관련 컴포넌트: `SceneCard.tsx`, `SceneGroupCard.tsx` (이미 `aspectRatio` prop 받음)
- 캐시: `.figma-cache/1713-271669_phase5_editor-1.api.json`

### 6.6.2 분담 (sub 6 / axis6) — Phase 5.2와 동시 가능 (파일 영역 다름)
- 단일 브랜치 `feat/marketing-p3-ai-shorts` 위에서 작업
- 커밋 prefix: `feat(web/p3-axis6): ...`
- 시작 가능 시점: 즉시 (Phase 5와 독립)

### 6.6.3 작업 룰 (Phase 5 sub와 동일)
- `git checkout` 금지, `git stash` 금지, HANDOFF 수정 금지
- 본인 영역만 수정 — `SceneCard.tsx`, `SceneGroupCard.tsx`, `ScenesPanel` (VideoDetailPage 내부)
- 가로 모드(`aspectRatio === "landscape"`)는 **건드리지 말 것** — UI/UX팀 미작성, 임의 변경 금지
- 세로 모드(`aspectRatio === "portrait"`) 분기에서만 P3 디자인 적용

### 6.6.4 캐시 spec 추출 (예시)
```bash
# 세로 카드 레이아웃 좌표/크기
jq '.. | objects | select(.name | test("Scene|장면|썸네일"; "i")) | {name, w: .absoluteBoundingBox.width, h: .absoluteBoundingBox.height}' \
  .figma-cache/1713-271669_phase5_editor-1.api.json | head -40

# 페이지네이션
jq '.. | objects | select(.type=="TEXT" and (.characters | test("^[0-9]+$"))) | {characters, x: .absoluteBoundingBox.x}' \
  .figma-cache/1713-271669_phase5_editor-1.api.json | head -20
```

### 6.6.5 head 보고 양식 (HANDOFF §6.5.7과 동일)
```
axis6 보고
- status: started / progress / blocked / done
- branch HEAD: <sha>
- 변경 파일: <files>
- 다음 단계: <next>
- 의문점: <question>
```

---

## 7. 확정 결정사항 (지석님 2026-05-15)

1. 기존 코드 검토 후 적용 — `features/shorts-auto-product-wizard/` 광범위 구현, 새로 만들지 말 것
2. Tailwind theme.colors 확장 + CSS 변수 병행 (Phase 0 완료)
3. AI 쇼츠 생성 flow 먼저(Phase 1-4), 편집 페이지 후속(Phase 5+)
4. 백엔드 변경 0건 (이미 디자인과 1:1 매칭)
5. `InlineWizardContainer` 기반 리디자인 (풀스크린 `WizardLayout` 대신)
6. 로고/사이드바 토글만 자산 교체
7. lucide-react 패키지 사용 (커스텀 = 로고/Warning/TooltipArrow만 inline SVG)
8. 결과 화면 4상태 = ScanStage + render_status 조합 (백엔드 변경 없음)
9. 내보내기 백엔드 미정 → 프론트만 Figma대로 mock 구성
10. 결과 카드: 100% 미만 메뉴 ⋮ = 2개(제목/취소), 100% = 4개. 좌하단 상품 태그 + 우측 캡션 50자 truncate. 생성 취소 dialog = 1602:36895 패턴

---

## 8. 인증 우회 (preview용)

### 8.1 현재 상태
- `src/components/layout/AppLayout.tsx` 에서 미인증 시 `/login` redirect
- `NO_LAYOUT_ROUTES = ["/login", "/auth/"]` 만 우회 가능
- 환경변수 `NEXT_PUBLIC_AUTH0_ENABLED=false` 면 dev login으로 전환되나 여전히 토큰 필요

### 8.2 권장 방안 (지석님께 제안)
**옵션 A: dev login으로 1회 로그인** (가장 빠름)
- `.env.local` 에 `NEXT_PUBLIC_AUTH0_ENABLED=false` 설정
- `npm run dev` → `localhost:3000` → /login 화면에서 dev 계정 입력
- 세션이 남아있는 동안 모든 페이지 접근 가능

**옵션 B: `/preview` 라우트 추가** (Phase 후 추가 작업)
- `AppLayout.tsx` `NO_LAYOUT_ROUTES` 에 `/preview` 추가
- `src/app/preview/[...slug]/page.tsx` 로 mock 데이터 주입하는 wrapper 페이지 작성
- ⚠️ 사이드바/헤더 없어짐 → 디자인 검수 용도라면 OK

→ 지석님 선택 대기

### 8.3 페이지별 URL (인증 후)
| 페이지 | URL |
|---|---|
| 동영상 목록 | `/videos` |
| 동영상 상세 / 개요 (Phase 1) | `/videos/[videoId]` |
| 장면 분석 / 세로 썸네일 (Phase 1 + axis6) | `/videos/[videoId]?view=scenes` (설정에서 세로 모드 토글) |
| AI 쇼츠 Wizard - 옵션 (Phase 2) | `/export/shorts/auto/wizard/[videoId]/criteria` |
| AI 쇼츠 Wizard - 상품 선택 (Phase 2) | `/export/shorts/auto/wizard/[videoId]/select-product` |
| AI 쇼츠 Wizard - 인덱싱 진행 (Phase 2 + axis7a) | `/export/shorts/auto/wizard/[videoId]/result/[parentJobId]` (children 없을 때) |
| AI 쇼츠 Wizard - 결과 (Phase 3) | `/export/shorts/auto/wizard/[videoId]/result/[parentJobId]` (children 있을 때) |
| 내 쇼츠 (Phase 4) | `/shorts` |
| 쇼츠 편집 (Phase 5) | `/shorts/editor?clip=[renderJobId]` 또는 `/export/shorts/auto/wizard/[videoId]/result/[parentJobId]/edit-clips?clip=[id]` |

### 8.4 빈 DB일 때 mock 데이터 시드
편집·결과·내쇼츠 페이지를 보려면 DB에 영상/씬/주문 데이터가 필요. 빈 DB일 경우 다음 중 하나:

**A. docker-compose 환경 (권장 — Makefile 타겟)**
```bash
cd "/mnt/c/Users/yes21/Desktop/_LV.UP/_LEVEL_UP/PROJECT/[HEIMDEX]/heimdex-for-livecommerce-dev"
make seed
# 내부적으로:
#   docker compose exec -T api alembic upgrade head
#   docker compose exec -T api python -m app.seed
```

**B. 호스트에서 직접 실행 (uvicorn으로 API 띄울 때)**
```bash
cd services/api
alembic upgrade head
python -m app.seed
```

**시드 산출물** (`services/api/app/seed.py` + `services/api/app/db/seed/fixtures/`):
- Org / User / Library / Profile / DriveConnection 기본 세트
- 사람(People) 식별 + face exemplar mock
- 영상(DriveFile) + Scene + 화자 transcript mock
- text_templates 기본 셋
- OpenSearch 임베딩은 `generate_mock_embedding` 으로 mock

**시드 실패 시**:
- alembic 마이그레이션 충돌 → `docker compose down -v` 로 DB 볼륨 초기화 후 재시도
- OpenSearch 인덱스 누락 → API 기동 시 자동 생성, 첫 검색 호출까지 대기

---

## 9. 검증 정책 (지석님 요구)

- 기능 개발 = **로컬 테스트 → EC2 검증 → PR** 순서 필수
- `npm run dev` 은 **지석님 직접** 실행 (claude 호출 금지)
- 기존 vitest 60+ 테스트 회귀 통과 유지
- 백엔드 변경 시 계획 공유 → 승인 후 실행
- Heimdex 저장소 커밋 = **Co-Authored-By Claude 금지**
- 커밋 = 마이크로 단위 (컴포넌트 1개 / 토큰 1세트)
- 푸시 = 명시적 승인 필수

---

## 10. 새 세션 시작 시 체크리스트

새 Claude에게 인계할 때 다음 순서로 진행:

1. 이 HANDOFF.md 전체 복붙
2. 새 세션에서 다음 명령 실행:
   ```bash
   cd "/mnt/c/Users/yes21/Desktop/_LV.UP/_LEVEL_UP/PROJECT/[HEIMDEX]/heimdex-for-livecommerce-dev/services/web"
   git status
   git log --oneline -10
   ```
3. Phase 1 시작점: `src/app/videos/[videoId]/page.tsx` Read
4. Figma 노드 fetch (1713:270773) — 새 세션에서 figma MCP `get_design_context` 호출
5. 마이크로 커밋으로 진행 (Co-Authored-By 금지 재확인)

---

## 11. 마지막 커밋 / 진행 상태

**현재 시점 (2026-05-15 통합 머지 후)**:
- **Phase 0**: ✅ 완료 (커밋 9fe5d2e ~ 6f001c5)
- **Phase 1**: ✅ 완료 (화자 색/탭 nav/AI badge/AutoShortsCTA navy, vitest 330 pass)
- **Phase 2**: ✅ 완료 (커밋 0226700, fd680a8, 7c10c68, 01fafdb, 7799b3d, 9a7956d) — branch `feat/p3-axis2-wizard` (사실상 axis4에 누적)
  - InlineWizardBreadcrumb → heimdex-navy stepper 토큰 (lucide ChevronRight)
  - 3 inline selector (Distribution / Length / Count) → navy 활성 보더, CountSelector suggestion 정책은 "10분당 1개" 유지
  - InlineWizardCriteriaPanel → shadow-card + rounded-card, 다음 버튼 = 공통 `Button`
  - InlineWizardProductPanel → cap 동적 안내문구, Lucide Check 체크박스, multi-mode cap 도달 시 `Snackbar` (2.5s auto-dismiss)
  - IndexingProgressPanel 신규 (Figma 1713:288103) — 4 stage chip + navy % + ETA
  - 백엔드 컨트랙트 무변경, tsc + wizard vitest exit 0
- **Phase 3**: ✅ 완료 (커밋 37bf058, a0e9a90, f68cd13, bd2afb9, def7eda, 08e3e0b) — branch `feat/p3-axis3-result` (사실상 axis4에 누적)
  - CancelGenerationDialog (Figma 1602:36895), ResultStatusChip 4상태, ResultCardMenu (stage-driven), ResultCard 287×253
  - result 페이지 grid 리팩터 + auto-redirect 제거
  - IndexingProgressPanel 마운트 위치 NOTE 마커 (Phase 2 머지 후 wire 예정)
- **Phase 4**: ✅ 완료 (커밋 fc101eb, 8779678, 7780448) — branch `feat/p3-axis4-saved-shorts`
  - Pagination active 색 indigo → heimdex-navy-500
  - SavedShortsPage 전체 리디자인 (Figma 1713:287987): 헤더/Searchbar/정렬 dropdown/9:16 카드 그리드/lucide 아이콘
  - Export 진행 Snackbar (top-right, mock) — `NOTE(export-backend-tbd)`
- **통합 머지**: ✅ axis4 → `feat/marketing-p3-ai-shorts` (이 머지 커밋)
- **남은 작업**:
  - Phase 3 result 페이지 IndexingProgressPanel wiring (NOTE 마커 위치)
  - Phase 5/6 (편집 페이지 + 장면분석 세로) 미시작
- **Figma 캐시**: 13개 노드 `.figma-cache/*.api.json` 로컬 저장 완료 (gitignore, fetch-nodes.sh로 재현)

---

## 14. Figma 캐시 디렉터리 사용법

위치: `.figma-cache/` (로컬 전용, `.gitignore`. `fetch-nodes.sh`만 git tracking)

### 14.1 캐시 생성/갱신
```bash
# 최초 1회 또는 디자인 갱신 시
export FIGMA_TOKEN="figd_xxx"           # Figma 본인 PAT
bash .figma-cache/fetch-nodes.sh         # 13개 노드 한 번에 fetch
# 옵션: PNG/SVG 렌더 URL 함께
IMAGES=1 SVG=1 bash .figma-cache/fetch-nodes.sh
# 옵션: 기존 파일 덮어쓰기
FORCE=1 bash .figma-cache/fetch-nodes.sh
```

### 14.2 파일 명명
`{nodeId-hyphen}_{phase}_{slug}.api.json` 예) `1713-288216_phase2_wizard-criteria.api.json`

### 14.3 파일 내용 = Figma REST API raw 응답
- `.document` = 노드 트리 (재귀적)
- 각 노드: `id`, `name`, `type`, `absoluteBoundingBox{x,y,width,height}`, `fills[]`, `strokes[]`, `effects[]`, `characters` (TEXT), `style`, `constraints`, `layoutMode`, `itemSpacing`, `children[]`
- 추가: `.componentSets`, `.components`, `.styles` (스타일 ID → 이름 매핑)

### 14.4 jq 추출 예시
```bash
# 최상위 구조 파악
jq '.document | {name, type, childCount: (.children | length)}' .figma-cache/<file>.api.json

# 모든 텍스트 노드 (행동 요약/스크립트 카피 등)
jq '.. | objects | select(.type=="TEXT") | {name, characters}' .figma-cache/<file>.api.json

# 카드/버튼 등 RECTANGLE 좌표/색 추출
jq '.. | objects | select(.type=="RECTANGLE") | {name, x: .absoluteBoundingBox.x, w: .absoluteBoundingBox.width, fills}' .figma-cache/<file>.api.json

# auto-layout (Flex) 검출
jq '.. | objects | select(.layoutMode) | {name, layoutMode, itemSpacing, padding: {l:.paddingLeft, r:.paddingRight, t:.paddingTop, b:.paddingBottom}}' .figma-cache/<file>.api.json
```

### 14.5 컬러 토큰 매핑 (Figma 변수 → Tailwind class)
| Figma 변수 | Tailwind |
|---|---|
| `Heimdex Navy/400` (#496a94) | `heimdex-navy-400` |
| `Heimdex Navy/500` (#234c77) | `heimdex-navy-500` |
| `Heimdex Navy/600` (#1c456f) | `heimdex-navy-600` |
| `Grayscale/{10,100,200,400,500,800}` | `grayscale-{...}` |
| `Neutral/{50,100,200,300,400,500,600,700,800}` | `neutral-h-{...}` |
| `Red/400` (#d53b49) | `red-h-400` |
| `Green/400` (#3fb675) | `green-h-400` |
| `Amber/500` (#e07f00) | `amber-h-500` |

### 14.6 토큰 절약 팁
- 절대 `cat .figma-cache/<file>.api.json` 전체 출력 금지 (500KB~2.6MB)
- 항상 `jq` 로 필요한 노드/필드만 추출
- 또는 `Read` 도구의 `offset`/`limit` 으로 부분만 읽기 (한 번에 ~500줄)

---

## 13. 병렬 작업 (다중 Claude 계정) 운영 가이드

### 13.1 브랜치 토폴로지
모두 `feat/marketing-p3-ai-shorts` (Phase 0/1 일부) 시점에서 분기:

```
feat/marketing-p3-ai-shorts  (Phase 0 + Phase 1 partial, 현재 HEAD)
├── feat/p3-axis2-wizard       (Phase 2 작업용 - 비어 있음)
├── feat/p3-axis3-result       (Phase 3 작업용 - 비어 있음)
└── feat/p3-axis4-saved-shorts (Phase 4 작업용 - 비어 있음)
```

### 13.2 파일 영역 분담 (충돌 없음)

| Phase | 브랜치 | 주요 수정 파일 |
|---|---|---|
| 1 (잔여) | `feat/marketing-p3-ai-shorts` (이 세션이 점유) | `src/features/videos/components/VideoDetailPage.tsx`, `src/lib/speaker-transcript.ts` |
| 2 | `feat/p3-axis2-wizard` | `src/features/shorts-auto-product-wizard/components/InlineWizard*.tsx` + 신규 `IndexingProgressPanel.tsx` |
| 3 | `feat/p3-axis3-result` | `src/features/shorts-auto-product-wizard/components/ExportShortsButton.tsx`, `src/app/export/shorts/auto/wizard/[videoId]/result/...` (WizardStepResult) |
| 4 | `feat/p3-axis4-saved-shorts` | `src/app/shorts/page.tsx`, `src/features/shorts/SavedShortsPage.tsx`, `src/features/shorts-auto-product-wizard/hooks/useExportBatch.ts` |

**공유 파일** (수정 시 모든 세션이 알아야 함):
- `tailwind.config.ts` — 토큰 추가 시 분리 PR로 먼저
- `src/app/globals.css` — 동일
- `src/components/ui/figma-index.ts` — 신규 UI 추가 시 export 라인 충돌 가능 (rebase 시 충돌 해소)
- `src/components/ui/` 의 기존 컴포넌트 — 시그니처 변경 금지

### 13.3 다른 Claude 계정 세션 시작 명령

새 터미널/세션에서 아래를 그대로 실행:

```bash
# 1. 작업 디렉터리 진입
cd "/mnt/c/Users/yes21/Desktop/_LV.UP/_LEVEL_UP/PROJECT/[HEIMDEX]/heimdex-for-livecommerce-dev"

# 2. 최신 main 동기화 (선택)
git fetch origin

# 3. 담당 Phase 브랜치 체크아웃 (택1)
git checkout feat/p3-axis2-wizard   # Phase 2 담당
# git checkout feat/p3-axis3-result   # Phase 3 담당
# git checkout feat/p3-axis4-saved-shorts # Phase 4 담당

# 4. HANDOFF 확인
cat HANDOFF.md | head -100
```

이후 새 세션에서 첫 메시지로 **이 HANDOFF.md 전체를 복붙** + "Phase N 진행해줘"라고 요청.

### 13.4 코디네이션 룰

1. **각 세션은 자기 브랜치에서만 커밋** — 다른 phase 파일은 절대 수정 금지
2. **공유 파일(tailwind.config.ts 등) 수정 필요 시**:
   - 슬랙 등으로 알리거나 `HANDOFF.md`에 "@공유" 섹션 추가
   - 또는 따로 `feat/p3-axis0b-tokens-extra` 브랜치 만들어 PR
3. **커밋 메시지 prefix**:
   - Phase 1: `feat(web/p3-axis1): ...`
   - Phase 2: `feat(web/p3-axis2): ...`
   - Phase 3: `feat(web/p3-axis3): ...`
   - Phase 4: `feat(web/p3-axis4): ...`
4. **Co-Authored-By Claude 금지** (Heimdex 규칙)
5. **푸시는 사용자 명시 승인 시에만**
6. **마이크로 커밋** — 컴포넌트 1개 또는 토큰 1세트 단위

### 13.5 머지 순서 (모든 Phase 완료 후)
1. `feat/marketing-p3-ai-shorts` (Phase 1) → `main` (PR 머지)
2. `feat/p3-axis2-wizard` rebase onto main → PR 머지
3. `feat/p3-axis3-result` rebase onto main → PR 머지
4. `feat/p3-axis4-saved-shorts` rebase onto main → PR 머지

각 PR은 시각 검증 (지석님 직접 `npm run dev`) 후 머지.

### 13.6 다른 세션이 첫 작업할 때 보내는 메시지 템플릿

```
다음 HANDOFF.md 컨텍스트로 작업해주세요.
브랜치는 이미 feat/p3-axis<N>-<name>으로 체크아웃 되어 있습니다.

<HANDOFF.md 전체 붙여넣기>

이번 세션에서는 Phase <N>만 진행합니다.
- 시작 파일: <위 13.2 표의 주요 수정 파일>
- 디자인 노드: <위 1.2 표의 Figma 노드 ID>
- 신규 컴포넌트: <Phase 별 신규 컴포넌트 — Phase 2면 IndexingProgressPanel.tsx 등>
- Figma MCP get_design_context 호출은 토큰 절약 위해 한 노드씩, 필요 시에만
- 마이크로 커밋 + Co-Authored-By 금지 + 푸시 금지
- 완료 후 type-check exit 0 + HANDOFF.md 진행 상태 업데이트 + 변경 사항 요약
```

---

## 12. 메모리 참조 (~/.claude-company/projects/-mnt-c-...-LEVEL-UP/memory/)

다음 파일이 자동 로드되어 있음 (새 세션에도 동일):
- `project_livecommerce_redesign.md` — 10개 결정사항 + Phase 로드맵
- `project_livecommerce_export_pending.md` — 내보내기 백엔드 미정 정책
- `feedback_commit_style.md` — Co-Authored-By 금지
- `feedback_local_test_first.md` — 로컬 → EC2 → PR 순서
- `feedback_no_push_without_approval.md` — 푸시 승인 필수
- `feedback_plan_before_server_changes.md` — 서버 변경 시 계획 공유
- `feedback_ai_coding_principles.md` — matklad 원칙 (경계는 직접, 구현만 위임)
